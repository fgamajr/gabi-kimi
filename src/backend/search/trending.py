"""Dynamic trending topic computation with cache support."""

from __future__ import annotations

import argparse
import logging
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from src.backend.core.config import settings
from src.backend.data.db import MongoDB

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "trending_topics"
_CACHE_DOC_ID = "latest"
_MIN_RECENT_DOCS = 50
_RECENT_WINDOWS = (7, 14, 30)
_BASELINE_DAYS = 90
_MIN_RATIO_DOC_COUNT = 6
_MIN_SIGNIFICANT_SCORE = 0.01
_SIGNAL_QUALITY_WEIGHTS: dict[str, float] = {
    "edital": 1.3,
    "lei": 1.25,
    "decreto": 1.2,
    "decreto-lei": 1.2,
    "instrucao normativa": 1.1,
    "resolucao": 1.1,
    "ministerio da educacao": 1.1,
    "ministerio da saude": 1.1,
    "anpd": 1.15,
    "anvisa": 1.1,
    "banco central": 1.1,
    "cvm": 1.1,
    "portaria": 0.85,
    "aviso": 0.6,
}


@dataclass(frozen=True)
class TrendingTopic:
    label: str
    query: str
    doc_count_7d: int
    trend_score: float
    icon: str = "trending"
    signal_type: str | None = None
    signal_key: str | None = None
    window_days: int | None = None
    pinned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicProfile:
    label: str
    query: str
    aliases: tuple[str, ...]
    icon: str
    art_types: tuple[str, ...]


TOPIC_PROFILES: tuple[TopicProfile, ...] = (
    TopicProfile(
        label="Concursos Públicos",
        query="concursos publicos",
        aliases=("concurso", "concursos", "concursos publicos", "concurso publico"),
        icon="fire",
        art_types=("edital", "portaria"),
    ),
    TopicProfile(
        label="Nomeações",
        query="nomeacao",
        aliases=("nomeacao", "nomeacoes", "nomeação", "nomeações"),
        icon="spark",
        art_types=("portaria",),
    ),
    TopicProfile(
        label="Licitações",
        query="licitacao",
        aliases=("licitacao", "licitacoes", "licitação", "licitações", "pregao", "pregão"),
        icon="hammer",
        art_types=("edital", "aviso"),
    ),
    TopicProfile(
        label="Portarias",
        query="portaria",
        aliases=("portaria", "portarias"),
        icon="document",
        art_types=("portaria",),
    ),
    TopicProfile(
        label="Decretos",
        query="decreto",
        aliases=("decreto", "decretos"),
        icon="scale",
        art_types=("decreto", "decreto-lei"),
    ),
    TopicProfile(
        label="Resoluções",
        query="resolucao",
        aliases=("resolucao", "resolucoes", "resolução", "resoluções"),
        icon="book",
        art_types=("resolucao",),
    ),
)

_ART_TYPE_SIGNAL_TO_TOPIC: dict[str, dict[str, str]] = {
    "edital": {"label": "Concursos e Editais", "icon": "clipboard", "query": "edital concurso"},
    "resolucao": {"label": "Novas Resoluções", "icon": "scale", "query": "resolucao"},
    "decreto": {"label": "Decretos Recentes", "icon": "scroll", "query": "decreto"},
    "decreto-lei": {"label": "Decretos Recentes", "icon": "scroll", "query": "decreto"},
    "instrucao normativa": {
        "label": "Instruções Normativas",
        "icon": "ruler",
        "query": "instrucao normativa",
    },
    "lei": {"label": "Novas Leis", "icon": "book", "query": "lei"},
    "portaria": {"label": "Portarias em Destaque", "icon": "document", "query": "portaria"},
    "aviso": {"label": "Avisos e Chamamentos", "icon": "megaphone", "query": "aviso chamamento"},
}

_ORGAN_SIGNAL_TO_TOPIC: dict[str, dict[str, str]] = {
    "anpd": {"label": "Proteção de Dados (ANPD)", "icon": "shield", "query": "ANPD proteção dados"},
    "banco central": {"label": "Banco Central", "icon": "bank", "query": "banco central"},
    "anvisa": {"label": "Regulação Sanitária", "icon": "health", "query": "ANVISA"},
    "aneel": {"label": "Energia Elétrica", "icon": "bolt", "query": "ANEEL"},
    "cvm": {"label": "Mercado de Capitais", "icon": "chart", "query": "CVM"},
    "ministerio da educacao": {"label": "Educação (MEC)", "icon": "graduation", "query": "MEC educação"},
    "ministerio da saude": {"label": "Saúde Pública", "icon": "health", "query": "saúde pública"},
    "ministerio da fazenda": {"label": "Fazenda", "icon": "bank", "query": "Ministério da Fazenda"},
    "presidencia da republica": {"label": "Atos da Presidência", "icon": "scroll", "query": "presidência da república"},
    "tcu": {"label": "Controle Externo (TCU)", "icon": "scale", "query": "TCU"},
}

FALLBACK_TOPICS: list[dict[str, Any]] = [
    asdict(TrendingTopic(label=profile.label, query=profile.query, doc_count_7d=0, trend_score=1.0, icon=profile.icon))
    for profile in TOPIC_PROFILES
]

PINNED_TOPICS: list[TrendingTopic] = [
    TrendingTopic(
        label="Diário Oficial Recente",
        query="decreto portaria edital resolucao lei",
        doc_count_7d=0,
        trend_score=99.0,
        icon="newspaper",
        signal_type="pinned",
        signal_key="diario_oficial_recente",
        pinned=True,
    )
]


def _normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _range_clause(latest_pub_date: str, days: int) -> dict[str, Any]:
    return {"range": {"pub_date": {"gte": f"{latest_pub_date}||-{days}d/d", "lte": latest_pub_date}}}


def _post_search(es_client: httpx.Client, body: dict[str, Any]) -> dict[str, Any]:
    response = es_client.post(
        f"{settings.ES_URL}/{settings.es_target_index}/_search",
        json={**body, "timeout": "800ms"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _get_latest_pub_date(es_client: httpx.Client) -> str | None:
    data = _post_search(
        es_client,
        {"size": 1, "sort": [{"pub_date": {"order": "desc"}}], "_source": ["pub_date"]},
    )
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None
    return hits[0].get("_source", {}).get("pub_date")


def _count_docs_in_window(es_client: httpx.Client, latest_pub_date: str, days: int) -> int:
    data = _post_search(
        es_client,
        {
            "size": 0,
            "track_total_hits": True,
            "query": _range_clause(latest_pub_date, days),
        },
    )
    return int(data.get("hits", {}).get("total", {}).get("value", 0))


def _choose_recent_window(es_client: httpx.Client, latest_pub_date: str) -> tuple[int, int]:
    chosen_days = _RECENT_WINDOWS[-1]
    chosen_count = 0
    for days in _RECENT_WINDOWS:
        count = _count_docs_in_window(es_client, latest_pub_date, days)
        chosen_days = days
        chosen_count = count
        if count >= _MIN_RECENT_DOCS:
            break
    return chosen_days, chosen_count


def _build_topic_from_mapping(
    *,
    signal_key: str,
    signal_type: str,
    mapping: dict[str, str],
    score: float,
    count_recent: int,
    window_days: int,
) -> TrendingTopic:
    adjusted_score = score * _SIGNAL_QUALITY_WEIGHTS.get(signal_key, 1.0)
    return TrendingTopic(
        label=mapping["label"],
        query=mapping["query"],
        doc_count_7d=count_recent,
        trend_score=round(adjusted_score, 2),
        icon=mapping["icon"],
        signal_type=signal_type,
        signal_key=signal_key,
        window_days=window_days,
    )


def _match_signal_mapping(
    signal_key: str,
    signal_type: str,
) -> tuple[str, dict[str, str]] | None:
    normalized = _normalize_text(signal_key)
    if signal_type == "art_type":
        for key, mapping in _ART_TYPE_SIGNAL_TO_TOPIC.items():
            if normalized == key or normalized.startswith(f"{key}-") or key in normalized:
                return key, mapping
    else:
        for key, mapping in _ORGAN_SIGNAL_TO_TOPIC.items():
            if normalized == key or key in normalized:
                return key, mapping
    return None


def _significant_terms_topics(
    es_client: httpx.Client,
    latest_pub_date: str,
    recent_days: int,
) -> list[TrendingTopic]:
    recent_range = _range_clause(latest_pub_date, recent_days)
    baseline_range = _range_clause(latest_pub_date, _BASELINE_DAYS)
    data = _post_search(
        es_client,
        {
            "size": 0,
            "query": recent_range,
            "aggs": {
                "trending_art_types": {
                    "significant_terms": {
                        "field": "art_type_normalized",
                        "size": 15,
                        "min_doc_count": 5,
                        "background_filter": baseline_range,
                    }
                },
                "trending_organs": {
                    "significant_terms": {
                        "field": "issuing_organ.keyword",
                        "size": 15,
                        "min_doc_count": 3,
                        "background_filter": baseline_range,
                    }
                },
            },
        },
    )
    aggs = data.get("aggregations", {})
    topics: list[TrendingTopic] = []

    for bucket in aggs.get("trending_art_types", {}).get("buckets", []):
        score = float(bucket.get("score", 0.0))
        if score < _MIN_SIGNIFICANT_SCORE:
            continue
        matched = _match_signal_mapping(str(bucket.get("key", "")), "art_type")
        if not matched:
            continue
        matched_key, mapping = matched
        topics.append(
            _build_topic_from_mapping(
                signal_key=matched_key,
                signal_type="art_type",
                mapping=mapping,
                score=score,
                count_recent=int(bucket.get("doc_count", 0)),
                window_days=recent_days,
            )
        )

    for bucket in aggs.get("trending_organs", {}).get("buckets", []):
        score = float(bucket.get("score", 0.0))
        if score < _MIN_SIGNIFICANT_SCORE:
            continue
        matched = _match_signal_mapping(str(bucket.get("key", "")), "organ")
        if not matched:
            continue
        matched_key, mapping = matched
        topics.append(
            _build_topic_from_mapping(
                signal_key=matched_key,
                signal_type="organ",
                mapping=mapping,
                score=score,
                count_recent=int(bucket.get("doc_count", 0)),
                window_days=recent_days,
            )
        )

    return topics


def _ratio_fallback_topics(
    es_client: httpx.Client,
    latest_pub_date: str,
    recent_days: int,
) -> list[TrendingTopic]:
    data = _post_search(
        es_client,
        {
            "size": 0,
            "aggs": {
                "recent_types": {
                    "filter": _range_clause(latest_pub_date, recent_days),
                    "aggs": {"buckets": {"terms": {"field": "art_type_normalized", "size": 50}}},
                },
                "baseline_types": {
                    "filter": _range_clause(latest_pub_date, _BASELINE_DAYS),
                    "aggs": {"buckets": {"terms": {"field": "art_type_normalized", "size": 50}}},
                },
                "recent_organs": {
                    "filter": _range_clause(latest_pub_date, recent_days),
                    "aggs": {"buckets": {"terms": {"field": "issuing_organ.keyword", "size": 50}}},
                },
                "baseline_organs": {
                    "filter": _range_clause(latest_pub_date, _BASELINE_DAYS),
                    "aggs": {"buckets": {"terms": {"field": "issuing_organ.keyword", "size": 50}}},
                },
            },
        },
    )
    aggs = data.get("aggregations", {})

    def to_bucket_map(path: str) -> dict[str, int]:
        buckets = aggs.get(path, {}).get("buckets", {}).get("buckets", [])
        return {str(bucket["key"]): int(bucket["doc_count"]) for bucket in buckets}

    recent_types = to_bucket_map("recent_types")
    baseline_types = to_bucket_map("baseline_types")
    recent_organs = to_bucket_map("recent_organs")
    baseline_organs = to_bucket_map("baseline_organs")

    topics: list[TrendingTopic] = []
    normalization = _BASELINE_DAYS / recent_days

    for signal_key, count_recent in recent_types.items():
        if count_recent < _MIN_RATIO_DOC_COUNT:
            continue
        matched = _match_signal_mapping(signal_key, "art_type")
        if not matched:
            continue
        matched_key, mapping = matched
        baseline_count = baseline_types.get(signal_key, 0)
        baseline_week = baseline_count / normalization if baseline_count else 0.1
        ratio = count_recent / max(baseline_week, 0.1)
        if ratio < 1.5:
            continue
        topics.append(
            _build_topic_from_mapping(
                signal_key=matched_key,
                signal_type="art_type",
                mapping=mapping,
                score=min(ratio, 25.0),
                count_recent=count_recent,
                window_days=recent_days,
            )
        )

    for signal_key, count_recent in recent_organs.items():
        if count_recent < _MIN_RATIO_DOC_COUNT:
            continue
        matched = _match_signal_mapping(signal_key, "organ")
        if not matched:
            continue
        matched_key, mapping = matched
        baseline_count = baseline_organs.get(signal_key, 0)
        baseline_week = baseline_count / normalization if baseline_count else 0.1
        ratio = count_recent / max(baseline_week, 0.1)
        if ratio < 1.5:
            continue
        topics.append(
            _build_topic_from_mapping(
                signal_key=matched_key,
                signal_type="organ",
                mapping=mapping,
                score=min(ratio, 25.0),
                count_recent=count_recent,
                window_days=recent_days,
            )
        )

    return topics


def _dedupe_topics(topics: list[TrendingTopic], top_n: int) -> list[TrendingTopic]:
    ordered: list[TrendingTopic] = []
    seen_labels: set[str] = set()
    seen_signals: set[tuple[str, str]] = set()

    dynamic_topics = sorted(
        [topic for topic in topics if not topic.pinned],
        key=lambda topic: (topic.trend_score, topic.doc_count_7d),
        reverse=True,
    )

    for topic in PINNED_TOPICS:
        ordered.append(topic)
        seen_labels.add(topic.label)

    for topic in dynamic_topics:
        if topic.label in seen_labels:
            continue
        if topic.signal_type and topic.signal_key and (topic.signal_type, topic.signal_key) in seen_signals:
            continue
        ordered.append(topic)
        seen_labels.add(topic.label)
        if topic.signal_type and topic.signal_key:
            seen_signals.add((topic.signal_type, topic.signal_key))
        if len(ordered) >= top_n:
            break

    if len(ordered) == len(PINNED_TOPICS):
        for fallback in FALLBACK_TOPICS:
            if fallback["label"] in seen_labels:
                continue
            ordered.append(TrendingTopic(**fallback))
            seen_labels.add(fallback["label"])
            if len(ordered) >= top_n:
                break

    return ordered[:top_n]


def get_topic_metadata(query: str) -> dict[str, Any] | None:
    norm = _normalize_text(query)
    if not norm:
        return None

    for profile in TOPIC_PROFILES:
        norm_aliases = [_normalize_text(alias) for alias in profile.aliases]
        if norm == _normalize_text(profile.query) or norm in norm_aliases or any(norm in alias for alias in norm_aliases):
            return {
                "label": profile.label,
                "query": profile.query,
                "icon": profile.icon,
                "art_types": list(profile.art_types),
            }
    return None


def compute_trending(es_client: httpx.Client, top_n: int = 8) -> list[TrendingTopic]:
    latest_pub_date = _get_latest_pub_date(es_client)
    if not latest_pub_date:
        return _dedupe_topics([], top_n)

    recent_days, recent_count = _choose_recent_window(es_client, latest_pub_date)
    logger.info("trending latest_pub_date=%s recent_window=%sd recent_count=%d", latest_pub_date, recent_days, recent_count)

    topics = _significant_terms_topics(es_client, latest_pub_date, recent_days)
    if len(topics) < 4:
        ratio_topics = _ratio_fallback_topics(es_client, latest_pub_date, recent_days)
        topics.extend(ratio_topic for ratio_topic in ratio_topics if ratio_topic.label not in {topic.label for topic in topics})

    deduped = _dedupe_topics(topics, top_n)
    result: list[TrendingTopic] = []
    for topic in deduped:
        if topic.pinned:
            result.append(
                TrendingTopic(
                    label=topic.label,
                    query=topic.query,
                    doc_count_7d=recent_count,
                    trend_score=topic.trend_score,
                    icon=topic.icon,
                    signal_type=topic.signal_type,
                    signal_key=topic.signal_key,
                    window_days=recent_days,
                    pinned=True,
                )
            )
        else:
            result.append(topic)
    return result[:top_n]


def get_cached_trending(mongo_db: Any) -> list[dict[str, Any]]:
    doc = mongo_db[_COLLECTION_NAME].find_one({"_id": _CACHE_DOC_ID}, {"topics": 1})
    topics = (doc or {}).get("topics")
    if isinstance(topics, list) and topics:
        return topics
    return []


def update_trending_cache(
    es_client: httpx.Client,
    mongo_db: Any,
    *,
    top_n: int = 8,
) -> list[dict[str, Any]]:
    latest_pub_date = _get_latest_pub_date(es_client)
    recent_days = None
    if latest_pub_date:
        recent_days, _ = _choose_recent_window(es_client, latest_pub_date)

    topics = [topic.to_dict() for topic in compute_trending(es_client, top_n=top_n)]
    payload = {
        "_id": _CACHE_DOC_ID,
        "topics": topics,
        "latest_pub_date": latest_pub_date,
        "recent_window_days": recent_days,
        "baseline_days": _BASELINE_DAYS,
        "updated_at": datetime.now(timezone.utc),
    }
    mongo_db[_COLLECTION_NAME].replace_one({"_id": _CACHE_DOC_ID}, payload, upsert=True)
    return topics


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute and cache trending GABI DOU topics.")
    parser.add_argument("--update", action="store_true", help="Compute trending topics and write Mongo cache")
    parser.add_argument("--top-n", type=int, default=8, help="Number of topics to keep")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if not args.update:
        raise SystemExit("Use --update to compute and cache trending topics.")

    mongo_db = MongoDB.get_db()
    with httpx.Client() as client:
        topics = update_trending_cache(client, mongo_db, top_n=args.top_n)
    logger.info("Updated %d trending topics", len(topics))


if __name__ == "__main__":
    main()
