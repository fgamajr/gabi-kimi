"""Curated trending topics and cache helpers for the GABI DOU search API."""

from __future__ import annotations

import argparse
import logging
import math
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


@dataclass(frozen=True)
class TrendingTopic:
    label: str
    query: str
    doc_count_7d: int
    trend_score: float
    icon: str = "trending"


@dataclass(frozen=True)
class TopicProfile:
    label: str
    query: str
    aliases: tuple[str, ...]
    icon: str
    art_types: tuple[str, ...]
    keywords: tuple[str, ...]


TOPIC_PROFILES: tuple[TopicProfile, ...] = (
    TopicProfile(
        label="Concursos Públicos",
        query="concursos publicos",
        aliases=("concurso", "concursos", "concursos publicos", "concurso publico"),
        icon="fire",
        art_types=("edital", "portaria"),
        keywords=("concurso", "concursos", "edital", "homologacao", "resultado", "nomeacao"),
    ),
    TopicProfile(
        label="Nomeações",
        query="nomeacao",
        aliases=("nomeacao", "nomeacoes", "nomeação", "nomeações"),
        icon="spark",
        art_types=("portaria",),
        keywords=("nomeacao", "nomeacoes", "designacao", "exoneracao", "posse"),
    ),
    TopicProfile(
        label="Licitações",
        query="licitacao",
        aliases=("licitacao", "licitacoes", "licitação", "licitações", "pregao", "pregão"),
        icon="hammer",
        art_types=("edital", "aviso"),
        keywords=("licitacao", "licitacoes", "pregao", "pregao eletronico", "registro de precos"),
    ),
    TopicProfile(
        label="Portarias",
        query="portaria",
        aliases=("portaria", "portarias"),
        icon="document",
        art_types=("portaria",),
        keywords=("portaria", "portarias"),
    ),
    TopicProfile(
        label="Decretos",
        query="decreto",
        aliases=("decreto", "decretos"),
        icon="scale",
        art_types=("decreto", "decreto-lei"),
        keywords=("decreto", "decretos", "decreto legislativo"),
    ),
    TopicProfile(
        label="Resoluções",
        query="resolucao",
        aliases=("resolucao", "resolucoes", "resolução", "resoluções"),
        icon="book",
        art_types=("resolucao",),
        keywords=("resolucao", "resolucoes"),
    ),
    TopicProfile(
        label="LGPD e Privacidade",
        query="lgpd",
        aliases=("lgpd", "lei geral de protecao de dados", "protecao de dados"),
        icon="shield",
        art_types=("lei", "resolucao", "instrucao normativa"),
        keywords=("lgpd", "dados pessoais", "tratamento de dados", "privacidade", "anpd"),
    ),
    TopicProfile(
        label="Aposentadorias",
        query="aposentadoria",
        aliases=("aposentadoria", "aposentadorias", "pensao", "pensões", "pensão"),
        icon="clock",
        art_types=("portaria",),
        keywords=("aposentadoria", "aposentadorias", "pensao", "pensoes"),
    ),
)

PINNED_TOPICS: list[dict[str, Any]] = [
    asdict(TrendingTopic(label=profile.label, query=profile.query, doc_count_7d=0, trend_score=1.0, icon=profile.icon))
    for profile in TOPIC_PROFILES[:6]
]


def _normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _topic_query(profile: TopicProfile) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []

    if profile.keywords:
        clauses.append(
            {
                "simple_query_string": {
                    "query": " | ".join(f'"{keyword}"' if " " in keyword else keyword for keyword in profile.keywords),
                    "fields": ["identifica^4", "ementa^3", "body_plain"],
                    "default_operator": "or",
                }
            }
        )

    for alias in profile.aliases:
        clauses.extend(
            [
                {"match_phrase": {"identifica": {"query": alias, "boost": 5}}},
                {"match_phrase": {"ementa": {"query": alias, "boost": 4}}},
                {"match_phrase": {"body_plain": {"query": alias, "boost": 2}}},
            ]
        )

    for art_type in profile.art_types:
        clauses.append({"term": {"art_type_normalized": art_type}})

    return {"bool": {"should": clauses, "minimum_should_match": 1}}


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


def compute_trending(es_client: httpx.Client, top_n: int = 10) -> list[TrendingTopic]:
    aggs: dict[str, Any] = {}

    for idx, profile in enumerate(TOPIC_PROFILES):
        query = _topic_query(profile)
        aggs[f"topic_{idx}_7d"] = {
            "filter": {
                "bool": {
                    "filter": [
                        {"range": {"pub_date": {"gte": "now-7d/d"}}},
                        query,
                    ]
                }
            }
        }
        aggs[f"topic_{idx}_30d"] = {
            "filter": {
                "bool": {
                    "filter": [
                        {"range": {"pub_date": {"gte": "now-30d/d"}}},
                        query,
                    ]
                }
            }
        }

    response = es_client.post(
        f"{settings.ES_URL}/{settings.es_target_index}/_search",
        json={"size": 0, "aggs": aggs, "timeout": "800ms"},
        timeout=30,
    )
    response.raise_for_status()
    buckets = response.json().get("aggregations", {})

    scored: list[TrendingTopic] = []
    for idx, profile in enumerate(TOPIC_PROFILES):
        count_7d = int(buckets.get(f"topic_{idx}_7d", {}).get("doc_count", 0))
        count_30d = int(buckets.get(f"topic_{idx}_30d", {}).get("doc_count", 0))

        if count_7d <= 0 and count_30d <= 0:
            continue

        older_count = max(count_30d - count_7d, 0)
        baseline_daily = max(older_count / 23 if older_count else count_30d / 30, 0.2)
        recent_daily = count_7d / 7
        spike_ratio = recent_daily / baseline_daily
        score = round(math.log1p(count_7d) * spike_ratio, 2)

        scored.append(
            TrendingTopic(
                label=profile.label,
                query=profile.query,
                doc_count_7d=count_7d,
                trend_score=score,
                icon=profile.icon,
            )
        )

    scored.sort(key=lambda topic: (topic.trend_score, topic.doc_count_7d), reverse=True)

    if len(scored) < top_n:
        seen = {topic.query for topic in scored}
        for pinned in PINNED_TOPICS:
            if pinned["query"] in seen:
                continue
            scored.append(
                TrendingTopic(
                    label=pinned["label"],
                    query=pinned["query"],
                    doc_count_7d=pinned["doc_count_7d"],
                    trend_score=pinned["trend_score"],
                    icon=pinned["icon"],
                )
            )
            if len(scored) >= top_n:
                break

    return scored[:top_n]


def get_cached_trending(mongo_db: Any) -> list[dict[str, Any]]:
    doc = mongo_db[_COLLECTION_NAME].find_one({"_id": _CACHE_DOC_ID}, {"topics": 1})
    topics = (doc or {}).get("topics")
    if isinstance(topics, list) and topics:
        return topics
    return PINNED_TOPICS


def update_trending_cache(
    es_client: httpx.Client,
    mongo_db: Any,
    *,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    topics = [asdict(topic) for topic in compute_trending(es_client, top_n=top_n)]
    payload = {
        "_id": _CACHE_DOC_ID,
        "topics": topics,
        "updated_at": datetime.now(timezone.utc),
    }
    mongo_db[_COLLECTION_NAME].replace_one({"_id": _CACHE_DOC_ID}, payload, upsert=True)
    return topics


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute and cache trending GABI DOU topics.")
    parser.add_argument("--update", action="store_true", help="Compute trending topics and write Mongo cache")
    parser.add_argument("--top-n", type=int, default=10, help="Number of topics to keep")
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
