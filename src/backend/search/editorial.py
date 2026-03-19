"""Daily editorial highlights: curated DOU documents by category."""

from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from src.backend.core.config import settings
from src.backend.data.db import MongoDB

logger = logging.getLogger(__name__)

_COLLECTION = "editorial_highlights"
_CACHE_DOC_ID = "latest"
_BRT = ZoneInfo("America/Sao_Paulo")

_SOURCE_FIELDS = [
    "doc_id", "identifica", "ementa", "art_type", "art_type_normalized",
    "pub_date", "section", "edition_section", "edition_number", "page_number",
    "issuing_organ", "organization_path",
]

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, dict[str, Any]] = {
    "destaque": {
        "badge": "DESTAQUE DO DIA",
        "query": {
            "bool": {
                "should": [
                    {"terms": {"section": ["DO1", "do1"]}},
                    {"terms": {"art_type_normalized": [
                        "decreto", "lei", "medida-provisoria", "resolucao",
                        "instrucao-normativa", "edital",
                    ]}},
                ],
                "minimum_should_match": 1,
            }
        },
    },
    "concursos": {
        "badge": "EM ALTA",
        "query": {
            "bool": {
                "must": [{"bool": {
                    "should": [
                        {"term": {"art_type_normalized": "edital"}},
                        {"match": {"identifica": "concurso"}},
                        {"match": {"ementa": "concurso"}},
                        {"match": {"ementa": "vagas"}},
                        {"match": {"identifica": "seleção"}},
                    ],
                    "minimum_should_match": 1,
                }}],
            }
        },
    },
    "economia": {
        "badge": "ECONOMIA",
        "query": {
            "bool": {
                "must": [{"bool": {
                    "should": [
                        {"match_phrase": {"issuing_organ": "Ministério da Fazenda"}},
                        {"match_phrase": {"issuing_organ": "Banco Central"}},
                        {"match_phrase": {"issuing_organ": "Receita Federal"}},
                        {"match_phrase": {"issuing_organ": "Secretaria da Receita Federal"}},
                        {"match_phrase": {"issuing_organ": "CVM"}},
                        {"match": {"ementa": "fiscal tributário orçamento imposto taxa arrecadação"}},
                    ],
                    "minimum_should_match": 1,
                }}],
            }
        },
    },
    "politica": {
        "badge": "POLÍTICA",
        "query": {
            "bool": {
                "must": [{"bool": {
                    "should": [
                        {"match_phrase": {"issuing_organ": "Presidência da República"}},
                        {"terms": {"art_type_normalized": ["decreto", "lei", "medida-provisoria"]}},
                    ],
                    "minimum_should_match": 1,
                }}],
                "should": [
                    {"terms": {"section": ["DO1", "do1"]}},
                ],
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Noise / boost tables (shared with main.py scoring logic)
# ---------------------------------------------------------------------------

_NOISE_TERMS = {
    "nomeacao", "nomeação", "nomeacoes", "nomeações",
    "exoneracao", "exoneração", "designacao", "designação",
    "aposentadoria", "pensao", "pensão", "ferias", "férias",
    "licenca", "licença", "substituicao", "substituição",
    "portaria de pessoal", "extrato", "apostila", "cessao", "cessão",
}

_ART_TYPE_BOOSTS: dict[str, float] = {
    "edital": 7.0, "resolucao": 6.0, "instrucao-normativa": 6.0,
    "decreto": 5.5, "lei": 5.0, "medida-provisoria": 5.0,
    "aviso": 3.0, "portaria": 1.5,
}

# Category-specific extra boosts
_CATEGORY_BOOSTS: dict[str, dict[str, float]] = {
    "destaque": {
        "presidencia": 10.0, "ministerio": 5.0, "decreto": 6.0,
        "medida provisoria": 8.0, "lei": 7.0, "regulamenta": 4.0,
    },
    "concursos": {"concurso": 8.0, "vagas": 5.0, "seleção": 5.0, "selecao": 5.0},
    "economia": {"fiscal": 5.0, "tributario": 5.0, "orcamento": 5.0, "imposto": 4.0},
    "politica": {"regulamenta": 5.0, "altera": 3.0, "aprova": 3.0},
}

_CONCURSO_NOISE = {"credenciamento": -6.0}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    lowered = text.lower().strip()
    normalized = unicodedata.normalize("NFD", lowered)
    return re.sub(r"\s+", " ", "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn"))


def _section_fe(es_val: str | None) -> str:
    if not es_val:
        return ""
    mapping = {"DO1": "1", "DO2": "2", "DO3": "3", "DOE": "e", "DO1a": "e"}
    return mapping.get(es_val.upper(), es_val.upper().replace("DO", "").lower() or es_val)


def _post_search(es_client: httpx.Client, body: dict[str, Any]) -> dict[str, Any]:
    resp = es_client.post(
        f"{settings.ES_URL}/{settings.es_target_index}/_search",
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _get_latest_pub_date(es_client: httpx.Client) -> str | None:
    data = _post_search(
        es_client,
        {"size": 1, "sort": [{"pub_date": {"order": "desc"}}], "_source": ["pub_date"]},
    )
    hits = data.get("hits", {}).get("hits", [])
    return hits[0].get("_source", {}).get("pub_date") if hits else None


def _days_since(pub_date: str, latest: str) -> int:
    try:
        pub = datetime.fromisoformat(pub_date[:10])
        lat = datetime.fromisoformat(latest[:10])
        return max((lat.date() - pub.date()).days, 0)
    except (ValueError, TypeError):
        return 999


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_candidate(hit: dict[str, Any], category: str, latest_pub_date: str) -> float:
    src = hit.get("_source", {})
    title = src.get("identifica") or ""
    ementa = src.get("ementa") or ""
    organ = src.get("issuing_organ") or ""
    art_type = _normalize(src.get("art_type_normalized") or src.get("art_type") or "")
    section = _section_fe(src.get("section") or src.get("edition_section"))
    days = _days_since(src.get("pub_date") or "", latest_pub_date)
    text = _normalize(f"{title} {ementa} {organ}")

    # Recency (shared across all categories)
    score = max(settings.EDITORIAL_LOOKBACK_DAYS - days, 0) * 1.2
    if days == 0:
        score += 8
    elif days <= 1:
        score += 6
    elif days <= 3:
        score += 4

    # Section boost (category-dependent)
    if category == "concursos":
        # Editais often in Section 3
        if section == "3":
            score += 2
        elif section == "1":
            score += 1
    else:
        if section == "1":
            score += 4
        elif section == "3":
            score -= 2

    # Art type boost
    score += _ART_TYPE_BOOSTS.get(art_type, 0)

    # Penalize low-impact art types for destaque
    if category == "destaque" and art_type in ("aviso", "portaria"):
        score -= 5

    # Organ boost (high-impact organs)
    organ_norm = _normalize(organ)
    if any(p in organ_norm for p in ("presidencia", "ministerio", "banco central", "congresso")):
        score += 4

    # Noise penalty
    for noise in _NOISE_TERMS:
        if noise in text:
            score -= 8
            break

    # Category-specific boosts
    for term, boost in _CATEGORY_BOOSTS.get(category, {}).items():
        if term in text:
            score += boost

    # Concursos: penalize credenciamento
    if category == "concursos":
        for term, penalty in _CONCURSO_NOISE.items():
            if term in text:
                score += penalty

    # Title quality: very short titles with no "nº" are usually noise
    if len(title.split()) <= 4 and "nº" not in _normalize(title):
        score -= 3

    return score


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def _fetch_candidates(
    es_client: httpx.Client,
    category: str,
    latest_pub_date: str,
) -> list[dict[str, Any]]:
    cat_config = CATEGORIES[category]
    query = {
        "bool": {
            **cat_config["query"].get("bool", {}),
            "filter": [
                {"range": {"pub_date": {
                    "gte": f"{latest_pub_date}||-{settings.EDITORIAL_LOOKBACK_DAYS}d/d",
                    "lte": latest_pub_date,
                }}},
            ],
        }
    }
    body = {
        "size": 50,
        "track_total_hits": False,
        "sort": [{"pub_date": {"order": "desc"}}],
        "_source": _SOURCE_FIELDS,
        "query": query,
    }
    data = _post_search(es_client, body)
    return data.get("hits", {}).get("hits", [])


def _select_best_per_category(
    es_client: httpx.Client,
    latest_pub_date: str,
) -> dict[str, dict[str, Any] | None]:
    """Select top-1 document per category, deduplicating across categories."""
    used_doc_ids: set[str] = set()
    results: dict[str, dict[str, Any] | None] = {}
    # Ranked candidates per category for backfill
    ranked: dict[str, list[tuple[float, dict[str, Any]]]] = {}

    # Score all candidates per category
    for cat in ("destaque", "concursos", "economia", "politica"):
        hits = _fetch_candidates(es_client, cat, latest_pub_date)
        scored = []
        for hit in hits:
            s = _score_candidate(hit, cat, latest_pub_date)
            if s > 0:
                scored.append((s, hit))
        scored.sort(key=lambda x: x[0], reverse=True)
        ranked[cat] = scored

    # Greedy allocation: destaque first, then others
    for cat in ("destaque", "concursos", "economia", "politica"):
        selected = None
        for score, hit in ranked[cat]:
            src = hit.get("_source", {})
            doc_id = src.get("doc_id") or hit.get("_id", "")
            if doc_id not in used_doc_ids:
                selected = hit
                used_doc_ids.add(doc_id)
                break
        results[cat] = selected

    return results


def _hit_to_highlight(hit: dict[str, Any], badge: str) -> dict[str, Any]:
    src = hit.get("_source", {})
    section = _section_fe(src.get("edition_section") or src.get("section"))
    return {
        "doc_id": src.get("doc_id") or hit.get("_id", ""),
        "title": src.get("identifica") or "",
        "summary": (src.get("ementa") or "")[:300],
        "why": "",
        "pub_date": src.get("pub_date") or "",
        "section": section,
        "edition_number": src.get("edition_number"),
        "issuing_organ": src.get("issuing_organ") or "",
        "art_type": src.get("art_type") or "",
        "badge": badge,
    }


# ---------------------------------------------------------------------------
# LLM enrichment (uses httpx directly, no SDK dependency)
# ---------------------------------------------------------------------------

_LLM_PROMPT = """Você é um editor de notícias do Diário Oficial da União (DOU).
Para cada documento abaixo, escreva em português brasileiro:
1. "summary": resumo jornalístico de 2 frases, claro e factual.
2. "why": 1 frase explicando por que é relevante para o público.

IMPORTANTE: Não invente informações. Use apenas o que está no texto do documento.

{documents}

Responda APENAS em JSON válido:
{{"destaque": {{"summary": "...", "why": "..."}}, "concursos": {{"summary": "...", "why": "..."}}, "economia": {{"summary": "...", "why": "..."}}, "politica": {{"summary": "...", "why": "..."}}}}"""


def _enrich_with_llm(
    categories: dict[str, dict[str, Any] | None],
    es_client: httpx.Client,
) -> bool:
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set, skipping LLM enrichment")
        return False

    # Build prompt with body_plain for selected docs
    doc_texts = []
    for cat, highlight in categories.items():
        if not highlight:
            continue
        # Fetch body_plain for this doc
        doc_id = highlight["doc_id"]
        try:
            resp = es_client.get(
                f"{settings.ES_URL}/{settings.es_target_index}/_doc/{doc_id}",
                params={"_source": "body_plain"},
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json().get("_source", {}).get("body_plain") or ""
        except Exception:
            body = ""

        doc_texts.append(
            f"--- Categoria: {cat} ---\n"
            f"Título: {highlight['title']}\n"
            f"Ementa: {highlight['summary']}\n"
            f"Corpo (trecho): {body[:1500]}\n"
            f"Órgão: {highlight['issuing_organ']}\n"
            f"Tipo: {highlight['art_type']}\n"
            f"Data: {highlight['pub_date']}"
        )

    if not doc_texts:
        return False

    prompt_text = _LLM_PROMPT.format(documents="\n\n".join(doc_texts))

    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.EDITORIAL_LLM_MODEL,
                "max_tokens": 1024,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt_text}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("content", [{}])[0].get("text", "")

        # Extract JSON from response (may be wrapped in markdown)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            logger.warning("LLM response has no JSON: %s", text[:200])
            return False

        enrichment = json.loads(json_match.group())

        for cat, highlight in categories.items():
            if not highlight or cat not in enrichment:
                continue
            e = enrichment[cat]
            summary = re.sub(r"<[^>]+>", "", str(e.get("summary", "")))[:400]
            why = re.sub(r"<[^>]+>", "", str(e.get("why", "")))[:200]
            if summary:
                highlight["summary"] = summary
            if why:
                highlight["why"] = why

        logger.info("LLM enrichment succeeded")
        return True

    except Exception:
        logger.exception("LLM enrichment failed")
        return False


def _apply_fallback(categories: dict[str, dict[str, Any] | None]) -> None:
    """Ensure summary and why have values even without LLM."""
    generic_why = {
        "destaque": "Publicação de alto impacto no Diário Oficial.",
        "concursos": "Oportunidade de concurso público ou seleção.",
        "economia": "Ato relevante na área econômica e fiscal.",
        "politica": "Ato político ou legislativo de destaque.",
    }
    for cat, highlight in categories.items():
        if not highlight:
            continue
        if not highlight.get("why"):
            highlight["why"] = generic_why.get(cat, "Publicação relevante.")


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

def get_cached_editorial(mongo_db: Any) -> dict[str, Any] | None:
    doc = mongo_db[_COLLECTION].find_one({"_id": _CACHE_DOC_ID})
    if not doc:
        return None
    doc.pop("_id", None)
    doc.pop("generated_at", None)
    return doc


def update_editorial_cache(es_client: httpx.Client, mongo_db: Any) -> dict[str, Any]:
    latest_pub_date = _get_latest_pub_date(es_client)
    if not latest_pub_date:
        logger.warning("No documents in ES index, cannot generate editorial highlights")
        return {}

    logger.info("Computing editorial highlights, latest_pub_date=%s", latest_pub_date)

    # Select best candidate per category
    selected = _select_best_per_category(es_client, latest_pub_date)

    # Build highlight dicts
    categories: dict[str, dict[str, Any] | None] = {}
    for cat in ("destaque", "concursos", "economia", "politica"):
        hit = selected.get(cat)
        if hit:
            categories[cat] = _hit_to_highlight(hit, CATEGORIES[cat]["badge"])
        else:
            categories[cat] = None

    # LLM enrichment (optional)
    llm_used = _enrich_with_llm(categories, es_client)
    _apply_fallback(categories)

    today_brt = datetime.now(_BRT).strftime("%Y-%m-%d")
    payload = {
        "_id": _CACHE_DOC_ID,
        "generated_for": today_brt,
        "generated_at": datetime.now(timezone.utc),
        "llm_used": llm_used,
        "categories": {k: v for k, v in categories.items() if v is not None},
    }
    mongo_db[_COLLECTION].replace_one({"_id": _CACHE_DOC_ID}, payload, upsert=True)

    filled = sum(1 for v in categories.values() if v)
    logger.info("Editorial highlights updated: %d/4 categories, llm_used=%s", filled, llm_used)
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Compute and cache GABI DOU editorial highlights.")
    parser.add_argument("--update", action="store_true", help="Compute highlights and write Mongo cache")
    args = parser.parse_args()

    if not args.update:
        raise SystemExit("Use --update to compute and cache editorial highlights.")

    mongo_db = MongoDB.get_db()
    with httpx.Client() as client:
        update_editorial_cache(client, mongo_db)


if __name__ == "__main__":
    main()
