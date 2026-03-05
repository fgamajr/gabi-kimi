"""Search backend adapter layer (pg/es) with shared response normalization."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from typing import Any, Protocol

import httpx
import psycopg2
from dotenv import load_dotenv

from ingest.embedding_pipeline import _create_embedder, _load_embed_config

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_dsn() -> str:
    if os.getenv("PG_DSN"):
        return os.environ["PG_DSN"]
    return (
        f"host={os.getenv('PGHOST', os.getenv('GABI_POSTGRES_HOST', 'localhost'))} "
        f"port={os.getenv('PGPORT', os.getenv('GABI_POSTGRES_PORT', '5433'))} "
        f"dbname={os.getenv('PGDATABASE', os.getenv('GABI_POSTGRES_DB', 'gabi'))} "
        f"user={os.getenv('PGUSER', os.getenv('GABI_POSTGRES_USER', 'gabi'))} "
        f"password={os.getenv('PGPASSWORD', os.getenv('GABI_POSTGRES_PASSWORD', 'gabi'))}"
    )


@dataclass(frozen=True)
class SearchConfig:
    backend: str
    pg_dsn: str
    es_url: str
    es_index: str
    es_chunks_index: str
    es_username: str | None
    es_password: str | None
    es_verify_tls: bool
    es_timeout_sec: int
    hybrid_lexical_k: int
    hybrid_vector_k: int
    hybrid_num_candidates: int
    hybrid_rrf_k: int
    rerank_provider: str
    rerank_top_n: int


def load_search_config() -> SearchConfig:
    return SearchConfig(
        backend=os.getenv("SEARCH_BACKEND", "pg").strip().lower(),
        pg_dsn=_build_dsn(),
        es_url=os.getenv("ES_URL", "http://localhost:9200").rstrip("/"),
        es_index=os.getenv("ES_INDEX", "gabi_documents_v1"),
        es_chunks_index=os.getenv("ES_CHUNKS_INDEX", "gabi_chunks_v1"),
        es_username=(os.getenv("ES_USERNAME") or "").strip() or None,
        es_password=(os.getenv("ES_PASSWORD") or "").strip() or None,
        es_verify_tls=_env_bool("ES_VERIFY_TLS", True),
        es_timeout_sec=int(os.getenv("ES_TIMEOUT_SEC", "20")),
        hybrid_lexical_k=int(os.getenv("HYBRID_LEXICAL_K", "80")),
        hybrid_vector_k=int(os.getenv("HYBRID_VECTOR_K", "80")),
        hybrid_num_candidates=int(os.getenv("HYBRID_NUM_CANDIDATES", "240")),
        hybrid_rrf_k=int(os.getenv("HYBRID_RRF_K", "60")),
        rerank_provider=(os.getenv("RERANK_PROVIDER", "basic").strip().lower()),
        rerank_top_n=int(os.getenv("RERANK_TOP_N", "25")),
    )


class SearchAdapter(Protocol):
    def search(
        self,
        *,
        query: str,
        page_size: int,
        page: int,
        date_from: str | None = None,
        date_to: str | None = None,
        section: str | None = None,
        art_type: str | None = None,
        issuing_organ: str | None = None,
    ) -> dict[str, Any]:
        ...

    def suggest(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        ...


def _rows(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _serialize(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    return v


def _query_text(query: str) -> str:
    return (
        query.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .strip()
    )


def _doc_filters(
    *,
    date_from: str | None,
    date_to: str | None,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    if date_from or date_to:
        rng: dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        filters.append({"range": {"pub_date": rng}})
    if section:
        filters.append({"term": {"edition_section.keyword": section}})
    if art_type:
        filters.append({"term": {"art_type.keyword": art_type}})
    if issuing_organ:
        filters.append({"term": {"issuing_organ.keyword": issuing_organ}})
    return filters


def _chunk_filters(
    *,
    date_from: str | None,
    date_to: str | None,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    if date_from or date_to:
        rng: dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        filters.append({"range": {"publication_date": rng}})
    if section:
        filters.append({"term": {"section": section}})
    if art_type:
        filters.append({"term": {"art_type": art_type}})
    if issuing_organ:
        filters.append({"term": {"issuing_organ": issuing_organ}})
    return filters


_LEXICAL_FIELDS = [
    "identifica^5",
    "ementa^4",
    "titulo^3",
    "sub_titulo^3",
    "issuing_organ^2",
    "art_type^2",
    "body_plain",
]


def _lexical_query_clause(query: str) -> dict[str, Any]:
    return {
        "bool": {
            "should": [
                {
                    "simple_query_string": {
                        "query": query,
                        "fields": _LEXICAL_FIELDS,
                        "default_operator": "and",
                        "fuzzy_max_expansions": 20,
                        "boost": 4.0,
                    }
                },
                {
                    "simple_query_string": {
                        "query": query,
                        "fields": _LEXICAL_FIELDS,
                        "default_operator": "or",
                        "fuzzy_max_expansions": 20,
                        "boost": 1.5,
                    }
                },
                {
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "identifica^8",
                            "ementa^6",
                            "titulo^5",
                            "sub_titulo^5",
                        ],
                        "type": "phrase",
                        "boost": 6.0,
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }


class PGSearchAdapter:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _conn(self, timeout_ms: int = 30000):
        conn = psycopg2.connect(self._dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout = {timeout_ms}")
        cur.close()
        return conn

    def search(
        self,
        *,
        query: str,
        page_size: int,
        page: int,
        date_from: str | None = None,
        date_to: str | None = None,
        section: str | None = None,
        art_type: str | None = None,
        issuing_organ: str | None = None,
    ) -> dict[str, Any]:
        q = _query_text(query)
        offset_results = page_size * page

        conn = self._conn()
        try:
            cur = conn.cursor()

            if q.strip() != "*" and not issuing_organ and not art_type:
                cur.execute(
                    "SELECT cat, term FROM dou.suggest_cache "
                    "WHERE cat IN ('orgao','tipo') AND term = %s LIMIT 1",
                    (q.strip(),),
                )
                match = cur.fetchone()
                if match:
                    cat, term = match
                    if cat == "orgao":
                        issuing_organ = term
                        q = "*"
                    elif cat == "tipo":
                        art_type = term
                        q = "*"

            if q.strip() == "*":
                where_parts = ["1=1"]
                params_list: list[Any] = []
                if date_from:
                    where_parts.append("e.publication_date >= %s::date")
                    params_list.append(date_from)
                if date_to:
                    where_parts.append("e.publication_date <= %s::date")
                    params_list.append(date_to)
                if section:
                    where_parts.append("e.section = %s")
                    params_list.append(section)
                if art_type:
                    where_parts.append("d.art_type = %s")
                    params_list.append(art_type)
                if issuing_organ:
                    where_parts.append("d.issuing_organ = %s")
                    params_list.append(issuing_organ)

                sql = f"""
                    SELECT d.id AS doc_id, 0.0 AS score, d.identifica, d.ementa,
                           d.art_type, e.publication_date AS pub_date,
                           e.section AS edition_section,
                           left(d.body_plain, 200) AS snippet
                    FROM dou.document d
                    JOIN dou.edition e ON e.id = d.edition_id
                    WHERE {' AND '.join(where_parts)}
                    ORDER BY e.publication_date DESC
                    LIMIT %s
                """
                params_list.append(offset_results)
                cur.execute(sql, params_list)
            else:
                cur.execute(
                    "SELECT doc_id, score, identifica, ementa, art_type, "
                    "pub_date, edition_section, snippet "
                    "FROM dou.bm25_search_filtered(%s, %s, %s, %s, %s, %s, %s)",
                    (q, offset_results, date_from, date_to, section, art_type, issuing_organ),
                )

            all_rows = _rows(cur)
            cur.close()
        finally:
            conn.close()

        start = (page - 1) * page_size
        page_rows = all_rows[start : start + page_size]
        return {
            "query": q,
            "total": len(all_rows),
            "page": page,
            "page_size": page_size,
            "results": [{k: _serialize(v) for k, v in r.items()} for r in page_rows],
        }

    def suggest(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        conn = self._conn(timeout_ms=5000)
        try:
            cur = conn.cursor()
            pattern = f"%{query}%"
            cur.execute(
                """
                SELECT cat, term, cnt
                FROM dou.suggest_cache
                WHERE term ILIKE %s
                ORDER BY cnt DESC
                LIMIT %s
                """,
                (pattern, limit),
            )
            suggestions: list[dict[str, Any]] = []
            seen: set[str] = set()
            for cat, term, cnt in cur.fetchall():
                key = term.strip().lower()
                if key not in seen:
                    suggestions.append({"term": term.strip(), "doc_freq": cnt, "cat": cat})
                    seen.add(key)
            cur.close()
        finally:
            conn.close()
        return {"prefix": query, "suggestions": suggestions}


class ESSearchAdapter:
    def __init__(
        self,
        *,
        url: str,
        index: str,
        username: str | None,
        password: str | None,
        verify_tls: bool,
        timeout_sec: int = 20,
    ) -> None:
        self._url = url.rstrip("/")
        self._index = index
        self._verify_tls = verify_tls
        self._timeout = timeout_sec
        self._auth = (username, password or "") if username else None
        self._client = httpx.Client(timeout=self._timeout, verify=self._verify_tls, auth=self._auth)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.request(
            method=method,
            url=f"{self._url}{path}",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Resposta inválida do Elasticsearch")
        return data

    def search(
        self,
        *,
        query: str,
        page_size: int,
        page: int,
        date_from: str | None = None,
        date_to: str | None = None,
        section: str | None = None,
        art_type: str | None = None,
        issuing_organ: str | None = None,
    ) -> dict[str, Any]:
        filters: list[dict[str, Any]] = []
        if date_from or date_to:
            rng: dict[str, Any] = {}
            if date_from:
                rng["gte"] = date_from
            if date_to:
                rng["lte"] = date_to
            filters.append({"range": {"pub_date": rng}})
        if section:
            filters.append({"term": {"edition_section.keyword": section}})
        if art_type:
            filters.append({"term": {"art_type.keyword": art_type}})
        if issuing_organ:
            filters.append({"term": {"issuing_organ.keyword": issuing_organ}})

        q = query.strip()
        if q == "*":
            must_clause: list[dict[str, Any]] = [{"match_all": {}}]
            highlight = None
        else:
            must_clause = [
                _lexical_query_clause(q)
            ]
            highlight = {
                "pre_tags": [">>>"],
                "post_tags": ["<<<"],
                "fields": {
                    "identifica": {"number_of_fragments": 0},
                    "ementa": {"number_of_fragments": 1, "fragment_size": 200},
                    "body_plain": {"number_of_fragments": 1, "fragment_size": 200},
                },
            }

        payload: dict[str, Any] = {
            "from": (page - 1) * page_size,
            "size": page_size,
            "track_total_hits": True,
            "query": {"bool": {"must": must_clause, "filter": filters}},
            "_source": [
                "doc_id",
                "identifica",
                "ementa",
                "art_type",
                "pub_date",
                "edition_section",
                "body_plain",
                "issuing_organ",
            ],
        }
        if highlight is not None:
            payload["highlight"] = highlight

        data = self._request("POST", f"/{self._index}/_search", payload)
        hits = data.get("hits", {}).get("hits", [])
        total = data.get("hits", {}).get("total", {}).get("value", 0)

        rows: list[dict[str, Any]] = []
        for hit in hits:
            src = hit.get("_source", {})
            hl = hit.get("highlight", {})
            snippet = ""
            for key in ("identifica", "ementa", "body_plain"):
                frags = hl.get(key)
                if frags:
                    snippet = frags[0]
                    break
            if not snippet:
                snippet = (src.get("body_plain") or "")[:200]
            rows.append(
                {
                    "doc_id": src.get("doc_id") or hit.get("_id"),
                    "score": float(hit.get("_score") or 0.0),
                    "identifica": src.get("identifica"),
                    "ementa": src.get("ementa"),
                    "art_type": src.get("art_type"),
                    "pub_date": src.get("pub_date"),
                    "edition_section": src.get("edition_section"),
                    "snippet": snippet,
                }
            )

        return {
            "query": query,
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "results": rows,
        }

    def suggest(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        q = query.strip()
        if not q:
            return {"prefix": query, "suggestions": []}

        payload = {
            "size": max(limit * 3, 20),
            "_source": ["issuing_organ", "art_type", "identifica"],
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase_prefix": {"issuing_organ": {"query": q}}},
                        {"match_phrase_prefix": {"art_type": {"query": q}}},
                        {"match_phrase_prefix": {"identifica": {"query": q}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }
        data = self._request("POST", f"/{self._index}/_search", payload)
        hits = data.get("hits", {}).get("hits", [])

        bucket: dict[tuple[str, str], int] = {}
        needle = q.lower()
        for hit in hits:
            src = hit.get("_source", {})
            candidates = [
                ("orgao", (src.get("issuing_organ") or "").strip()),
                ("tipo", (src.get("art_type") or "").strip()),
                ("titulo", (src.get("identifica") or "").strip()),
            ]
            for cat, term in candidates:
                if not term:
                    continue
                if needle not in term.lower():
                    continue
                key = (cat, term)
                bucket[key] = bucket.get(key, 0) + 1

        ranked = sorted(bucket.items(), key=lambda x: x[1], reverse=True)[:limit]
        suggestions = [{"term": term, "doc_freq": cnt, "cat": cat} for (cat, term), cnt in ranked]
        return {"prefix": query, "suggestions": suggestions}


class HybridSearchAdapter(ESSearchAdapter):
    """Hybrid retriever: lexical document search + vector chunk search + RRF merge."""

    def __init__(
        self,
        *,
        url: str,
        index: str,
        chunks_index: str,
        username: str | None,
        password: str | None,
        verify_tls: bool,
        timeout_sec: int = 20,
        lexical_k: int = 80,
        vector_k: int = 80,
        num_candidates: int = 240,
        rrf_k: int = 60,
        rerank_provider: str = "basic",
        rerank_top_n: int = 25,
    ) -> None:
        super().__init__(
            url=url,
            index=index,
            username=username,
            password=password,
            verify_tls=verify_tls,
            timeout_sec=timeout_sec,
        )
        self._chunks_index = chunks_index
        self._lexical_k = max(10, lexical_k)
        self._vector_k = max(10, vector_k)
        self._num_candidates = max(self._vector_k, num_candidates)
        self._rrf_k = max(1, rrf_k)
        self._rerank_provider = rerank_provider
        self._rerank_top_n = max(0, rerank_top_n)
        embed_cfg = _load_embed_config()
        self._embedder = _create_embedder(embed_cfg)

    def _lexical_candidates(
        self,
        *,
        query: str,
        size: int,
        date_from: str | None,
        date_to: str | None,
        section: str | None,
        art_type: str | None,
        issuing_organ: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = _doc_filters(
            date_from=date_from,
            date_to=date_to,
            section=section,
            art_type=art_type,
            issuing_organ=issuing_organ,
        )
        payload: dict[str, Any] = {
            "from": 0,
            "size": size,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "must": [_lexical_query_clause(query)],
                    "filter": filters,
                }
            },
            "_source": [
                "doc_id",
                "identifica",
                "ementa",
                "art_type",
                "pub_date",
                "edition_section",
                "body_plain",
                "issuing_organ",
            ],
            "highlight": {
                "pre_tags": [">>>"],
                "post_tags": ["<<<"],
                "fields": {
                    "identifica": {"number_of_fragments": 0},
                    "ementa": {"number_of_fragments": 1, "fragment_size": 220},
                    "body_plain": {"number_of_fragments": 1, "fragment_size": 220},
                },
            },
        }
        data = self._request("POST", f"/{self._index}/_search", payload)
        hits = data.get("hits", {}).get("hits", [])
        total = int(data.get("hits", {}).get("total", {}).get("value", 0))

        rows: list[dict[str, Any]] = []
        for rank, hit in enumerate(hits, start=1):
            src = hit.get("_source", {})
            hl = hit.get("highlight", {})
            snippet = ""
            for key in ("identifica", "ementa", "body_plain"):
                frags = hl.get(key)
                if frags:
                    snippet = frags[0]
                    break
            if not snippet:
                snippet = (src.get("body_plain") or "")[:220]
            rows.append(
                {
                    "doc_id": src.get("doc_id") or hit.get("_id"),
                    "bm25_rank": rank,
                    "bm25_score": float(hit.get("_score") or 0.0),
                    "identifica": src.get("identifica"),
                    "ementa": src.get("ementa"),
                    "art_type": src.get("art_type"),
                    "pub_date": src.get("pub_date"),
                    "edition_section": src.get("edition_section"),
                    "issuing_organ": src.get("issuing_organ"),
                    "snippet": snippet,
                }
            )
        return rows, total

    def _vector_candidates(
        self,
        *,
        query: str,
        size: int,
        date_from: str | None,
        date_to: str | None,
        section: str | None,
        art_type: str | None,
        issuing_organ: str | None,
    ) -> list[dict[str, Any]]:
        vector = self._embedder.embed_batch([query])[0]
        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": vector,
            "k": size,
            "num_candidates": max(size, self._num_candidates),
        }
        filters = _chunk_filters(
            date_from=date_from,
            date_to=date_to,
            section=section,
            art_type=art_type,
            issuing_organ=issuing_organ,
        )
        if filters:
            knn["filter"] = filters

        payload: dict[str, Any] = {
            "size": size,
            "knn": knn,
            "_source": [
                "chunk_id",
                "doc_id",
                "chunk_text",
                "heading_context",
                "art_type",
                "section",
                "publication_date",
                "issuing_organ",
            ],
        }
        data = self._request("POST", f"/{self._chunks_index}/_search", payload)
        hits = data.get("hits", {}).get("hits", [])

        rows: list[dict[str, Any]] = []
        seen_docs: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            src = hit.get("_source", {})
            doc_id = str(src.get("doc_id") or "")
            if not doc_id or doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            snippet = str(src.get("chunk_text") or "").strip()
            if len(snippet) > 220:
                snippet = snippet[:220]
            rows.append(
                {
                    "doc_id": doc_id,
                    "vector_rank": len(rows) + 1,
                    "vector_score": float(hit.get("_score") or 0.0),
                    "vector_chunk_id": src.get("chunk_id"),
                    "vector_snippet": snippet,
                    "art_type": src.get("art_type"),
                    "pub_date": src.get("publication_date"),
                    "edition_section": src.get("section"),
                    "issuing_organ": src.get("issuing_organ"),
                }
            )
        return rows

    def _fetch_doc_sources(self, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not doc_ids:
            return {}
        data = self._request("POST", f"/{self._index}/_mget", {"ids": doc_ids})
        docs = data.get("docs", [])
        out: dict[str, dict[str, Any]] = {}
        for doc in docs:
            if not doc.get("found"):
                continue
            src = doc.get("_source", {})
            doc_id = str(src.get("doc_id") or doc.get("_id") or "")
            if doc_id:
                out[doc_id] = src
        return out

    def _basic_rerank(self, query: str, row: dict[str, Any]) -> float:
        q = query.casefold().strip()
        if not q:
            return 0.0
        q_terms = {term for term in q.split() if term}
        text = " ".join(
            str(row.get(k) or "")
            for k in ("identifica", "ementa", "snippet", "art_type", "issuing_organ")
        ).casefold()
        if not text:
            return 0.0
        overlap = len(q_terms & {term for term in text.split() if term})
        overlap_ratio = overlap / max(1, len(q_terms))
        phrase_bonus = 2.0 if q in text else 0.0
        title_bonus = 1.5 if q and q in str(row.get("identifica") or "").casefold() else 0.0
        return phrase_bonus + title_bonus + overlap_ratio

    def _merge(
        self,
        *,
        query: str,
        lexical_rows: list[dict[str, Any]],
        lexical_total: int,
        vector_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        merged: dict[str, dict[str, Any]] = {}
        for row in lexical_rows:
            doc_id = str(row["doc_id"])
            item = merged.setdefault(doc_id, {"doc_id": doc_id})
            item.update(row)
        for row in vector_rows:
            doc_id = str(row["doc_id"])
            item = merged.setdefault(doc_id, {"doc_id": doc_id})
            for key, value in row.items():
                if key == "doc_id":
                    continue
                item[key] = value

        doc_sources = self._fetch_doc_sources([doc_id for doc_id, row in merged.items() if "identifica" not in row])
        for doc_id, row in merged.items():
            src = doc_sources.get(doc_id, {})
            row.setdefault("identifica", src.get("identifica"))
            row.setdefault("ementa", src.get("ementa"))
            row.setdefault("art_type", src.get("art_type"))
            row.setdefault("pub_date", src.get("pub_date"))
            row.setdefault("edition_section", src.get("edition_section"))
            row.setdefault("issuing_organ", src.get("issuing_organ"))
            row.setdefault("snippet", row.get("vector_snippet") or (src.get("body_plain") or "")[:220])
            row["rrf_score"] = 0.0
            if row.get("bm25_rank"):
                row["rrf_score"] += 1.0 / (self._rrf_k + int(row["bm25_rank"]))
            if row.get("vector_rank"):
                row["rrf_score"] += 1.0 / (self._rrf_k + int(row["vector_rank"]))
            row["score"] = row["rrf_score"]
            row["retrieval_mode"] = (
                "hybrid"
                if row.get("bm25_rank") and row.get("vector_rank")
                else "bm25"
                if row.get("bm25_rank")
                else "vector"
            )

        ranked = sorted(
            merged.values(),
            key=lambda row: (
                float(row.get("rrf_score") or 0.0),
                float(row.get("vector_score") or 0.0),
                float(row.get("bm25_score") or 0.0),
            ),
            reverse=True,
        )

        if self._rerank_provider != "none" and self._rerank_top_n > 0:
            top_n = min(len(ranked), self._rerank_top_n)
            reranked: list[dict[str, Any]] = []
            for row in ranked[:top_n]:
                row["rerank_score"] = self._basic_rerank(query, row)
                reranked.append(row)
            reranked.sort(
                key=lambda row: (
                    float(row.get("rerank_score") or 0.0),
                    float(row.get("rrf_score") or 0.0),
                    float(row.get("vector_score") or 0.0),
                    float(row.get("bm25_score") or 0.0),
                ),
                reverse=True,
            )
            ranked = reranked + ranked[top_n:]

        return {
            "total": max(lexical_total, len(ranked)),
            "rows": ranked,
        }

    def search(
        self,
        *,
        query: str,
        page_size: int,
        page: int,
        date_from: str | None = None,
        date_to: str | None = None,
        section: str | None = None,
        art_type: str | None = None,
        issuing_organ: str | None = None,
    ) -> dict[str, Any]:
        q = _query_text(query)
        if q == "*" or not q:
            out = super().search(
                query=query,
                page_size=page_size,
                page=page,
                date_from=date_from,
                date_to=date_to,
                section=section,
                art_type=art_type,
                issuing_organ=issuing_organ,
            )
            out["backend"] = "hybrid"
            out["retrieval_mode"] = "browse"
            return out

        merge_window = max(page * page_size * 4, self._lexical_k, self._vector_k)
        lexical_rows, lexical_total = self._lexical_candidates(
            query=q,
            size=merge_window,
            date_from=date_from,
            date_to=date_to,
            section=section,
            art_type=art_type,
            issuing_organ=issuing_organ,
        )
        vector_rows = self._vector_candidates(
            query=q,
            size=merge_window,
            date_from=date_from,
            date_to=date_to,
            section=section,
            art_type=art_type,
            issuing_organ=issuing_organ,
        )
        merged = self._merge(
            query=q,
            lexical_rows=lexical_rows,
            lexical_total=lexical_total,
            vector_rows=vector_rows,
        )
        start = (page - 1) * page_size
        page_rows = merged["rows"][start : start + page_size]
        return {
            "query": query,
            "total": int(merged["total"]),
            "page": page,
            "page_size": page_size,
            "backend": "hybrid",
            "rrf_k": self._rrf_k,
            "lexical_candidates": len(lexical_rows),
            "vector_candidates": len(vector_rows),
            "reranker": self._rerank_provider,
            "results": page_rows,
        }


def create_search_adapter(config: SearchConfig | None = None) -> SearchAdapter:
    cfg = config or load_search_config()
    if cfg.backend == "hybrid":
        return HybridSearchAdapter(
            url=cfg.es_url,
            index=cfg.es_index,
            chunks_index=cfg.es_chunks_index,
            username=cfg.es_username,
            password=cfg.es_password,
            verify_tls=cfg.es_verify_tls,
            timeout_sec=cfg.es_timeout_sec,
            lexical_k=cfg.hybrid_lexical_k,
            vector_k=cfg.hybrid_vector_k,
            num_candidates=cfg.hybrid_num_candidates,
            rrf_k=cfg.hybrid_rrf_k,
            rerank_provider=cfg.rerank_provider,
            rerank_top_n=cfg.rerank_top_n,
        )
    if cfg.backend == "es":
        return ESSearchAdapter(
            url=cfg.es_url,
            index=cfg.es_index,
            username=cfg.es_username,
            password=cfg.es_password,
            verify_tls=cfg.es_verify_tls,
            timeout_sec=cfg.es_timeout_sec,
        )
    return PGSearchAdapter(cfg.pg_dsn)
