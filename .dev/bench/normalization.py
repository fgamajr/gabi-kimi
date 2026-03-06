from __future__ import annotations

from typing import Any

import psycopg2


class BenchmarkHydrator:
    """Hydrate backend result rows into a canonical shape for grading."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def hydrate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        doc_ids = [str(row.get("doc_id") or "").strip() for row in rows if row.get("doc_id")]
        if not doc_ids:
            return rows
        details = self._fetch_details(doc_ids)
        hydrated: list[dict[str, Any]] = []
        for row in rows:
            doc_id = str(row.get("doc_id") or "").strip()
            meta = details.get(doc_id) or {}
            merged = dict(row)
            for key, value in meta.items():
                if _needs_fill(merged.get(key)):
                    merged[key] = value
            hydrated.append(merged)
        return hydrated

    def _fetch_details(self, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
        conn = psycopg2.connect(self._dsn)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    d.id::text AS doc_id,
                    d.identifica,
                    d.ementa,
                    d.art_type,
                    d.issuing_organ,
                    d.body_plain,
                    e.publication_date AS pub_date,
                    e.section AS edition_section
                FROM dou.document d
                JOIN dou.edition e ON e.id = d.edition_id
                WHERE d.id = ANY(%s::uuid[])
                """,
                (doc_ids,),
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            cur.close()
        finally:
            conn.close()
        return {
            str(row[0]): {
                key: value
                for key, value in zip(columns[1:], row[1:], strict=False)
            }
            for row in rows
        }


def normalized_query(case: dict[str, Any], backend: str) -> str:
    if backend == "pg" and case.get("category") == "organ_type_filters":
        return "*"
    return str(case.get("query") or "")


def response_meta(
    response: dict[str, Any],
    *,
    backend: str,
    original_query: str,
    executed_query: str,
) -> dict[str, Any]:
    meta = {
        key: response.get(key)
        for key in (
            "backend",
            "total",
            "page",
            "page_size",
            "rrf_k",
            "lexical_candidates",
            "vector_candidates",
            "reranker",
        )
        if key in response
    }
    meta["executed_query"] = executed_query
    meta["original_query"] = original_query
    meta["normalized_query"] = executed_query != original_query
    meta.setdefault("backend", backend)
    return meta


def _needs_fill(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False
