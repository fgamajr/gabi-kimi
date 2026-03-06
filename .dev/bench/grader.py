from __future__ import annotations

from typing import Any


def grade_case(case: dict[str, Any], results: list[dict[str, Any]], *, top_k: int = 10) -> dict[str, Any]:
    hints = case.get("relevance_hints") or {}
    expected_title_terms = [str(x).casefold() for x in hints.get("title_contains") or []]
    expected_body_terms = [str(x).casefold() for x in hints.get("body_contains") or []]
    exact_phrase = str(hints.get("exact_phrase") or "").casefold()
    filters = case.get("filters") or {}
    category = str(case.get("category") or "")

    judged_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(results[:top_k], start=1):
        rel = _row_relevance(
            row=row,
            filters=filters,
            expected_title_terms=expected_title_terms,
            expected_body_terms=expected_body_terms,
            exact_phrase=exact_phrase,
            category=category,
        )
        rel["rank"] = rank
        judged_rows.append(rel)

    relevant_ranks = [row["rank"] for row in judged_rows if row["relevant"]]
    p_at_1 = 1.0 if relevant_ranks and relevant_ranks[0] == 1 else 0.0
    p_at_3 = sum(1 for row in judged_rows[:3] if row["relevant"]) / max(1, min(3, len(judged_rows)))
    p_at_5 = sum(1 for row in judged_rows[:5] if row["relevant"]) / max(1, min(5, len(judged_rows)))
    hits_at_10 = 1.0 if relevant_ranks else 0.0
    mrr = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
    avg_relevance = (
        sum(float(row["score"]) for row in judged_rows) / len(judged_rows) if judged_rows else 0.0
    )
    return {
        "p_at_1": round(p_at_1, 4),
        "p_at_3": round(p_at_3, 4),
        "p_at_5": round(p_at_5, 4),
        "hits_at_10": round(hits_at_10, 4),
        "mrr": round(mrr, 4),
        "avg_relevance": round(avg_relevance, 4),
        "relevant_ranks": relevant_ranks,
        "judged_rows": judged_rows,
    }


def aggregate_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {
            "cases": 0.0,
            "p_at_1": 0.0,
            "p_at_3": 0.0,
            "p_at_5": 0.0,
            "hits_at_10": 0.0,
            "mrr": 0.0,
            "avg_relevance": 0.0,
        }
    keys = ["p_at_1", "p_at_3", "p_at_5", "hits_at_10", "mrr", "avg_relevance"]
    return {
        "cases": float(len(rows)),
        **{key: round(sum(float(row.get(key, 0.0)) for row in rows) / len(rows), 4) for key in keys},
    }


def _row_relevance(
    *,
    row: dict[str, Any],
    filters: dict[str, Any],
    expected_title_terms: list[str],
    expected_body_terms: list[str],
    exact_phrase: str,
    category: str,
) -> dict[str, Any]:
    title = str(row.get("identifica") or "").casefold()
    ementa = str(row.get("ementa") or "").casefold()
    snippet = str(row.get("snippet") or row.get("vector_snippet") or "").casefold()
    body_plain = str(row.get("body_plain") or "").casefold()
    issuing_organ = str(row.get("issuing_organ") or "").casefold()
    blob = " ".join([title, ementa, snippet, body_plain, issuing_organ])

    hard_match = _matches_filters(row, filters)
    title_hits = [term for term in expected_title_terms if term and term in title]
    body_hits = [term for term in expected_body_terms if term and term in blob]
    phrase_hit = bool(exact_phrase and exact_phrase in blob)

    score = 0.0
    if hard_match:
        score += 0.4
    if phrase_hit:
        score += 0.4
    if expected_title_terms:
        score += 0.1 * (len(title_hits) / max(1, len(expected_title_terms)))
    if expected_body_terms:
        score += 0.1 * (len(body_hits) / max(1, len(expected_body_terms)))

    if not expected_title_terms and not expected_body_terms and not exact_phrase:
        score = 1.0 if hard_match else 0.0

    filter_led_case = category == "organ_type_filters"
    relevant = hard_match and (
        phrase_hit
        or bool(title_hits)
        or bool(body_hits)
        or filter_led_case
        or (not expected_title_terms and not expected_body_terms and not exact_phrase)
    )
    return {
        "doc_id": row.get("doc_id"),
        "title": row.get("identifica"),
        "score": round(min(score, 1.0), 4),
        "relevant": relevant,
        "retrieval_mode": row.get("retrieval_mode", row.get("backend", "")),
        "title_hits": title_hits,
        "body_hits": body_hits,
        "phrase_hit": phrase_hit,
        "hard_match": hard_match,
    }


def _matches_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    if not filters:
        return True
    section = str(filters.get("section") or "").strip().casefold()
    art_type = str(filters.get("art_type") or "").strip().casefold()
    organ = str(filters.get("issuing_organ") or "").strip().casefold()
    row_section = str(row.get("edition_section") or "").strip().casefold()
    row_type = str(row.get("art_type") or "").strip().casefold()
    row_organ = str(row.get("issuing_organ") or "").strip().casefold()
    if section and row_section != section:
        return False
    if art_type and row_type != art_type:
        return False
    if organ and row_organ != organ:
        return False
    return True
