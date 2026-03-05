"""Embedding + Elasticsearch chunk index pipeline for RAG Phase 2.

Usage:
  python3 -m ingest.embedding_pipeline create-index
  python3 -m ingest.embedding_pipeline backfill --batch-size 500
  python3 -m ingest.embedding_pipeline sync
  python3 -m ingest.embedding_pipeline stats
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import httpx
import psycopg2
from dotenv import load_dotenv


_MAPPING_PATH = Path(__file__).resolve().parent.parent / "search" / "es_chunks_v1.json"
_DEFAULT_CURSOR_PATH = Path(__file__).resolve().parent.parent / "data" / "es_chunks_sync_cursor.json"

load_dotenv()


def _log(msg: str) -> None:
    print(f"[embed-pipeline] {msg}", flush=True)


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


def _load_cursor(path: Path) -> dict[str, str]:
    if not path.exists():
        return {
            "created_at": "1970-01-01T00:00:00+00:00",
            "chunk_id": "00000000-0000-0000-0000-000000000000",
        }
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "created_at": str(data.get("created_at") or "1970-01-01T00:00:00+00:00"),
        "chunk_id": str(data.get("chunk_id") or "00000000-0000-0000-0000-000000000000"),
    }


def _save_cursor(path: Path, created_at: str, chunk_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": created_at,
        "chunk_id": chunk_id,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)


def _l2_normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm <= 0:
        return v
    return [x / norm for x in v]


@dataclass(slots=True)
class EmbedConfig:
    provider: str
    model: str
    dim: int
    base_url: str
    api_key: str
    timeout_sec: int
    verify_tls: bool
    use_contextual_prefix: bool
    max_retries: int
    retry_base_sec: float


def _load_embed_config() -> EmbedConfig:
    api_key = (
        os.getenv("EMBED_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    return EmbedConfig(
        provider=(os.getenv("EMBED_PROVIDER", "hash").strip().lower()),
        model=os.getenv("EMBED_MODEL", "text-embedding-3-small").strip(),
        dim=int(os.getenv("EMBED_DIM", "384")),
        base_url=os.getenv("EMBED_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        api_key=api_key,
        timeout_sec=int(os.getenv("EMBED_TIMEOUT_SEC", "30")),
        verify_tls=_env_bool("EMBED_VERIFY_TLS", True),
        use_contextual_prefix=_env_bool("USE_CONTEXTUAL_EMBEDDINGS", True),
        max_retries=max(1, int(os.getenv("EMBED_MAX_RETRIES", "6"))),
        retry_base_sec=max(0.25, float(os.getenv("EMBED_RETRY_BASE_SEC", "1.5"))),
    )


class EmbeddingProvider:
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic dev fallback embedding provider.

    Not semantic-quality; used to keep the pipeline operational in local envs.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * self.dim
            data = (t or "").encode("utf-8")
            # Fill vector using repeated SHA-256 blocks.
            block = data
            i = 0
            while i < self.dim:
                digest = hashlib.sha256(block).digest()
                for b in digest:
                    if i >= self.dim:
                        break
                    # Map byte -> [-1, 1]
                    vec[i] = (float(b) / 127.5) - 1.0
                    i += 1
                block = digest + block[:32]
            out.append(_l2_normalize(vec))
        return out


class OpenAICompatEmbeddingProvider(EmbeddingProvider):
    def __init__(self, cfg: EmbedConfig) -> None:
        if not cfg.api_key:
            raise RuntimeError(
                "EMBED_API_KEY or OPENAI_API_KEY is required for openai-compatible provider"
            )
        self.cfg = cfg
        self.client = httpx.Client(
            timeout=cfg.timeout_sec,
            verify=cfg.verify_tls,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
        )

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        rows = self._embed_rows(texts)
        vectors: list[list[float]] = []
        for row in rows:
            emb = row.get("embedding")
            if not isinstance(emb, list):
                raise RuntimeError("embedding missing in response")
            vectors.append(_l2_normalize([float(x) for x in emb]))
        return vectors

    def _embed_rows(self, texts: list[str]) -> list[dict[str, Any]]:
        payload = {
            "model": self.cfg.model,
            "input": texts,
        }
        # OpenAI-compatible providers may support dimensions.
        if self.cfg.dim > 0:
            payload["dimensions"] = self.cfg.dim
        try:
            data = self._post_embeddings(payload)
        except httpx.HTTPStatusError as ex:
            if ex.response.status_code == 400 and len(texts) > 1:
                mid = max(1, len(texts) // 2)
                _log(
                    "embedding payload too large; splitting batch "
                    f"size={len(texts)} into {mid}+{len(texts) - mid}"
                )
                return self._embed_rows(texts[:mid]) + self._embed_rows(texts[mid:])
            raise
        rows = data.get("data", [])
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise RuntimeError("invalid embeddings response size")
        return rows

    def _post_embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: str | None = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self.client.post(f"{self.cfg.base_url}/embeddings", json=payload)
                if resp.status_code in {408, 409, 429, 500, 502, 503, 504, 507}:
                    last_error = f"http {resp.status_code}"
                    retry_after = resp.headers.get("retry-after")
                    delay = float(retry_after) if retry_after else self.cfg.retry_base_sec * attempt
                    _log(f"embedding request retry attempt={attempt} reason={last_error} sleep={delay:.1f}s")
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise RuntimeError("invalid embeddings response payload")
                return data
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as ex:
                last_error = type(ex).__name__
                if attempt >= self.cfg.max_retries:
                    break
                delay = self.cfg.retry_base_sec * attempt
                _log(f"embedding request retry attempt={attempt} reason={last_error} sleep={delay:.1f}s")
                time.sleep(delay)
        raise RuntimeError(f"embedding request failed after retries: {last_error}")


def _create_embedder(cfg: EmbedConfig) -> EmbeddingProvider:
    if cfg.provider in {"hash", "fake", "dev"}:
        _log("using hash embedding provider (dev fallback)")
        return HashEmbeddingProvider(cfg.dim)
    if cfg.provider in {"openai", "openai_compat", "openai-compatible"}:
        _log(f"using openai-compatible embedding provider model={cfg.model}")
        return OpenAICompatEmbeddingProvider(cfg)
    raise RuntimeError(f"unsupported EMBED_PROVIDER: {cfg.provider}")


class ESChunksClient:
    def __init__(self, embed_dim: int) -> None:
        self.url = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
        self.index = os.getenv("ES_CHUNKS_INDEX", "gabi_chunks_v1")
        self.verify_tls = _env_bool("ES_VERIFY_TLS", True)
        self.timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "30"))
        user = (os.getenv("ES_USERNAME") or "").strip()
        pwd = (os.getenv("ES_PASSWORD") or "").strip()
        self.auth = (user, pwd) if user else None
        self.client = httpx.Client(timeout=self.timeout_sec, verify=self.verify_tls, auth=self.auth)
        self.embed_dim = embed_dim

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self.client.request(method=method, url=f"{self.url}{path}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Resposta inválida do Elasticsearch")
        return data

    def ensure_index(self, recreate: bool = False) -> None:
        with _MAPPING_PATH.open("r", encoding="utf-8") as f:
            mapping = json.load(f)
        mapping["mappings"]["properties"]["embedding"]["dims"] = int(self.embed_dim)

        if recreate:
            self.client.request(method="DELETE", url=f"{self.url}/{self.index}")

        exists_resp = self.client.request(method="HEAD", url=f"{self.url}/{self.index}")
        if exists_resp.status_code == 404:
            _log(f"creating chunks index {self.index} (dims={self.embed_dim})")
            self.request("PUT", f"/{self.index}", mapping)
        elif exists_resp.status_code >= 400:
            exists_resp.raise_for_status()

    def set_bulk_mode(self, enabled: bool) -> None:
        refresh_interval = "-1" if enabled else "1s"
        replicas = 0
        payload = {
            "index": {
                "refresh_interval": refresh_interval,
                "number_of_replicas": replicas,
            }
        }
        self.request("PUT", f"/{self.index}/_settings", payload)

    def bulk(self, docs: list[dict[str, Any]], retries: int = 3) -> tuple[int, int]:
        lines: list[str] = []
        for doc in docs:
            chunk_id = doc["chunk_id"]
            lines.append(json.dumps({"index": {"_index": self.index, "_id": chunk_id}}, ensure_ascii=False))
            lines.append(json.dumps(doc, ensure_ascii=False))
        body = "\n".join(lines) + "\n"

        last_error: str | None = None
        for attempt in range(1, retries + 1):
            resp = self.client.post(
                f"{self.url}/_bulk",
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
            )
            if resp.status_code in (429, 502, 503, 504):
                last_error = f"http {resp.status_code}"
                time.sleep(1.5 * attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            ok = 0
            failed = 0
            first_error: str | None = None
            for item in items:
                row = item.get("index", {})
                status = int(row.get("status", 500))
                if 200 <= status < 300:
                    ok += 1
                else:
                    failed += 1
                    if first_error is None:
                        err = row.get("error")
                        first_error = json.dumps(err, ensure_ascii=True) if err else f"status={status}"
            if failed:
                raise RuntimeError(
                    f"bulk indexing failed: failed={failed} ok={ok} first_error={first_error}"
                )
            return ok, failed
        raise RuntimeError(f"bulk failed after retries: {last_error}")


def _conn():
    conn = psycopg2.connect(_build_dsn())
    conn.autocommit = True
    return conn


def _fetch_chunk_batch(conn, cursor_created_at: str, cursor_chunk_id: str, batch_size: int) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            c.id::text AS chunk_id,
            c.document_id::text AS doc_id,
            c.chunk_index,
            c.chunk_text,
            c.chunk_text_norm,
            c.chunk_char_start,
            c.chunk_char_end,
            c.token_estimate,
            c.heading_context,
            c.metadata_json,
            d.id_materia,
            d.art_type,
            d.issuing_organ,
            e.section,
            e.publication_date::text AS publication_date,
            to_char(c.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS created_at
        FROM dou.document_chunk c
        JOIN dou.document d ON d.id = c.document_id
        JOIN dou.edition e ON e.id = d.edition_id
        WHERE (c.created_at, c.id) > (%s::timestamptz, %s::uuid)
        ORDER BY c.created_at, c.id
        LIMIT %s
        """,
        (cursor_created_at, cursor_chunk_id, batch_size),
    )
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    return out


def _contextual_text(row: dict[str, Any], use_context: bool) -> str:
    base = str(row.get("chunk_text") or "").strip()
    if not use_context:
        return base
    parts = [
        f"Tipo: {row.get('art_type') or ''}",
        f"Órgão: {row.get('issuing_organ') or ''}",
        f"Seção: {row.get('section') or ''}",
        f"Data: {row.get('publication_date') or ''}",
        f"ID matéria: {row.get('id_materia') or ''}",
        f"Contexto: {row.get('heading_context') or ''}",
        "",
        base,
    ]
    return "\n".join(parts).strip()


def _to_es_doc(row: dict[str, Any], embedding: list[float]) -> dict[str, Any]:
    meta = row.get("metadata_json")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}

    return {
        "chunk_id": row["chunk_id"],
        "doc_id": row["doc_id"],
        "id_materia": row.get("id_materia"),
        "chunk_index": int(row.get("chunk_index", 0) or 0),
        "chunk_char_start": int(row.get("chunk_char_start", 0) or 0),
        "chunk_char_end": int(row.get("chunk_char_end", 0) or 0),
        "token_estimate": int(row.get("token_estimate", 0) or 0),
        "chunk_text": row.get("chunk_text") or "",
        "chunk_text_norm": row.get("chunk_text_norm") or "",
        "heading_context": row.get("heading_context") or "",
        "section": row.get("section"),
        "publication_date": row.get("publication_date"),
        "issuing_organ": row.get("issuing_organ"),
        "art_type": row.get("art_type"),
        "created_at": row.get("created_at"),
        "metadata": meta,
        "embedding": embedding,
    }


def _counts(conn, es: ESChunksClient) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM dou.document_chunk")
    pg_count = int(cur.fetchone()[0])
    cur.close()
    es_count = int(es.request("GET", f"/{es.index}/_count").get("count", 0))
    return pg_count, es_count


def _run_sync(*, reset_cursor: bool, recreate_index: bool, batch_size: int, cursor_path: Path) -> None:
    embed_cfg = _load_embed_config()
    embedder = _create_embedder(embed_cfg)
    es = ESChunksClient(embed_dim=embed_cfg.dim)
    es.ensure_index(recreate=recreate_index)
    es.set_bulk_mode(True)

    if reset_cursor:
        cursor = {
            "created_at": "1970-01-01T00:00:00+00:00",
            "chunk_id": "00000000-0000-0000-0000-000000000000",
        }
    else:
        cursor = _load_cursor(cursor_path)
    _log(f"starting from cursor created_at={cursor['created_at']} chunk_id={cursor['chunk_id']}")

    conn = _conn()
    total_ok = 0
    total_failed = 0
    loops = 0
    try:
        while True:
            loops += 1
            rows = _fetch_chunk_batch(conn, cursor["created_at"], cursor["chunk_id"], batch_size)
            if not rows:
                break

            embed_inputs = [_contextual_text(r, embed_cfg.use_contextual_prefix) for r in rows]
            vectors = embedder.embed_batch(embed_inputs)
            if len(vectors) != len(rows):
                raise RuntimeError("embedding provider returned wrong number of vectors")

            docs = [_to_es_doc(r, v) for r, v in zip(rows, vectors)]
            ok, failed = es.bulk(docs)
            total_ok += ok
            total_failed += failed

            last = rows[-1]
            cursor["created_at"] = str(last["created_at"])
            cursor["chunk_id"] = str(last["chunk_id"])
            _save_cursor(cursor_path, cursor["created_at"], cursor["chunk_id"])

            _log(
                f"batch={loops} fetched={len(rows)} indexed_ok={ok} failed={failed} "
                f"cursor={cursor['created_at']}::{cursor['chunk_id']}"
            )
    finally:
        conn.close()
        try:
            es.set_bulk_mode(False)
        except Exception as ex:
            _log(f"warning: failed to restore index refresh settings: {type(ex).__name__}: {ex}")

    conn = _conn()
    try:
        pg_count, es_count = _counts(conn, es)
    finally:
        conn.close()
    _log(f"done indexed_ok={total_ok} failed={total_failed} pg_count={pg_count} es_count={es_count}")


def cmd_create_index(args: argparse.Namespace) -> None:
    cfg = _load_embed_config()
    es = ESChunksClient(embed_dim=cfg.dim)
    es.ensure_index(recreate=args.recreate_index)
    _log(f"index ready: {es.index} dims={cfg.dim}")


def cmd_backfill(args: argparse.Namespace) -> None:
    _run_sync(
        reset_cursor=True,
        recreate_index=args.recreate_index,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
    )


def cmd_sync(args: argparse.Namespace) -> None:
    _run_sync(
        reset_cursor=False,
        recreate_index=False,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
    )


def cmd_stats(args: argparse.Namespace) -> None:
    cursor_path = Path(args.cursor)
    cfg = _load_embed_config()
    es = ESChunksClient(embed_dim=cfg.dim)
    conn = _conn()
    try:
        pg_count, es_count = _counts(conn, es)
    finally:
        conn.close()

    health = es.request("GET", "/_cluster/health")
    idx_stats = es.request("GET", f"/{es.index}/_stats/docs,store")
    cursor = _load_cursor(cursor_path)
    print(
        json.dumps(
            {
                "backend": "es_chunks",
                "index": es.index,
                "embed_provider": cfg.provider,
                "embed_model": cfg.model,
                "embed_dim": cfg.dim,
                "cluster_status": health.get("status"),
                "pg_chunk_count": pg_count,
                "es_chunk_count": es_count,
                "count_delta": pg_count - es_count,
                "cursor": cursor,
                "index_stats": idx_stats.get("indices", {}).get(es.index, {}),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Embedding pipeline for ES chunk index")
    p.add_argument("--cursor", default=str(_DEFAULT_CURSOR_PATH), help="Cursor state file path")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_ci = sub.add_parser("create-index", help="Create chunk vector index")
    s_ci.add_argument("--recreate-index", action="store_true")
    s_ci.set_defaults(func=cmd_create_index)

    s_b = sub.add_parser("backfill", help="Full backfill from PostgreSQL chunks")
    s_b.add_argument("--batch-size", type=int, default=256)
    s_b.add_argument("--recreate-index", action="store_true")
    s_b.set_defaults(func=cmd_backfill)

    s_s = sub.add_parser("sync", help="Incremental sync from cursor")
    s_s.add_argument("--batch-size", type=int, default=256)
    s_s.set_defaults(func=cmd_sync)

    s_st = sub.add_parser("stats", help="Show chunk index stats")
    s_st.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
