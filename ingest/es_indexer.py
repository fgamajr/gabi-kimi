"""Elasticsearch indexer for DOU documents (backfill, incremental sync, stats).

Usage:
  python3 -m ingest.es_indexer backfill
  python3 -m ingest.es_indexer sync
  python3 -m ingest.es_indexer stats
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any

import httpx
import psycopg2


_MAPPING_PATH = Path(__file__).resolve().parent.parent / "search" / "es_index_v1.json"
_DEFAULT_CURSOR_PATH = Path(__file__).resolve().parent.parent / "data" / "es_sync_cursor.json"


def _log(msg: str) -> None:
    print(f"[es-indexer] {msg}", flush=True)


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
        return {"created_at": "1970-01-01T00:00:00+00:00", "doc_id": "00000000-0000-0000-0000-000000000000"}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "created_at": str(data.get("created_at") or "1970-01-01T00:00:00+00:00"),
        "doc_id": str(data.get("doc_id") or "00000000-0000-0000-0000-000000000000"),
    }


def _save_cursor(path: Path, created_at: str, doc_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": created_at,
        "doc_id": doc_id,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)


class ESClient:
    def __init__(self) -> None:
        self.url = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
        self.index = os.getenv("ES_INDEX", "gabi_documents_v1")
        self.alias = (os.getenv("ES_ALIAS") or "").strip() or None
        self.verify_tls = _env_bool("ES_VERIFY_TLS", True)
        self.timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "30"))
        user = (os.getenv("ES_USERNAME") or "").strip()
        pwd = (os.getenv("ES_PASSWORD") or "").strip()
        self.auth = (user, pwd) if user else None
        self.client = httpx.Client(timeout=self.timeout_sec, verify=self.verify_tls, auth=self.auth)

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self.client.request(
            method=method,
            url=f"{self.url}{path}",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Resposta inválida do Elasticsearch")
        return data

    def ensure_index(self, recreate: bool = False) -> None:
        with _MAPPING_PATH.open("r", encoding="utf-8") as f:
            mapping = json.load(f)

        if recreate:
            self.client.request(
                method="DELETE",
                url=f"{self.url}/{self.index}",
            )

        exists_resp = self.client.request(
            method="HEAD",
            url=f"{self.url}/{self.index}",
        )
        if exists_resp.status_code == 404:
            _log(f"creating index {self.index}")
            self.request("PUT", f"/{self.index}", mapping)
        elif exists_resp.status_code >= 400:
            exists_resp.raise_for_status()

        if self.alias:
            self.request(
                "POST",
                "/_aliases",
                {
                    "actions": [
                        {"add": {"index": self.index, "alias": self.alias}},
                    ]
                },
            )

    def bulk(self, docs: list[dict[str, Any]], retries: int = 3) -> tuple[int, int]:
        lines: list[str] = []
        for doc in docs:
            doc_id = doc["doc_id"]
            lines.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}, ensure_ascii=False))
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
            if not isinstance(data, dict):
                raise RuntimeError("Resposta inválida do bulk")
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


def _fetch_batch(conn, cursor_created_at: str, cursor_doc_id: str, batch_size: int) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            d.id::text AS doc_id,
            d.id_materia,
            d.identifica,
            d.ementa,
            d.titulo,
            d.sub_titulo,
            d.body_plain,
            d.art_type,
            d.issuing_organ,
            e.section AS edition_section,
            e.publication_date::text AS pub_date,
            d.document_number,
            d.document_year,
            d.page_number,
            e.is_extra,
            to_char(d.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') AS created_at
        FROM dou.document d
        JOIN dou.edition e ON e.id = d.edition_id
        WHERE (d.created_at, d.id) > (%s::timestamptz, %s::uuid)
        ORDER BY d.created_at, d.id
        LIMIT %s
        """,
        (cursor_created_at, cursor_doc_id, batch_size),
    )
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    return out


def _counts(conn, es: ESClient) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM dou.document")
    pg_count = int(cur.fetchone()[0])
    cur.close()

    es_count = int(es.request("GET", f"/{es.index}/_count").get("count", 0))
    return pg_count, es_count


def _run_sync(*, reset_cursor: bool, recreate_index: bool, batch_size: int, cursor_path: Path) -> None:
    es = ESClient()
    es.ensure_index(recreate=recreate_index)

    if reset_cursor:
        cursor = {"created_at": "1970-01-01T00:00:00+00:00", "doc_id": "00000000-0000-0000-0000-000000000000"}
    else:
        cursor = _load_cursor(cursor_path)
    _log(f"starting from cursor created_at={cursor['created_at']} doc_id={cursor['doc_id']}")

    conn = _conn()
    total_ok = 0
    total_failed = 0
    loops = 0
    try:
        while True:
            loops += 1
            rows = _fetch_batch(conn, cursor["created_at"], cursor["doc_id"], batch_size)
            if not rows:
                break
            ok, failed = es.bulk(rows)
            total_ok += ok
            total_failed += failed

            last = rows[-1]
            cursor["created_at"] = str(last["created_at"])
            cursor["doc_id"] = str(last["doc_id"])
            _save_cursor(cursor_path, cursor["created_at"], cursor["doc_id"])

            _log(
                f"batch={loops} fetched={len(rows)} indexed_ok={ok} failed={failed} "
                f"cursor={cursor['created_at']}::{cursor['doc_id']}"
            )
    finally:
        conn.close()

    conn = _conn()
    try:
        pg_count, es_count = _counts(conn, es)
    finally:
        conn.close()

    _log(f"done indexed_ok={total_ok} failed={total_failed} pg_count={pg_count} es_count={es_count}")


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
    es = ESClient()
    conn = _conn()
    try:
        pg_count, es_count = _counts(conn, es)
    finally:
        conn.close()

    health = es.request("GET", "/_cluster/health")
    idx_stats = es.request("GET", f"/{es.index}/_stats/docs,store")
    cursor = _load_cursor(cursor_path)

    print(json.dumps(
        {
            "backend": "es",
            "index": es.index,
            "cluster_status": health.get("status"),
            "pg_count": pg_count,
            "es_count": es_count,
            "count_delta": pg_count - es_count,
            "cursor": cursor,
            "index_stats": idx_stats.get("indices", {}).get(es.index, {}),
        },
        ensure_ascii=True,
        indent=2,
    ))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Elasticsearch indexer for GABI DOU")
    p.add_argument("--cursor", default=str(_DEFAULT_CURSOR_PATH), help="Cursor state file path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("backfill", help="Full backfill from PostgreSQL")
    sp.add_argument("--batch-size", type=int, default=2000)
    sp.add_argument("--recreate-index", action="store_true")
    sp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("sync", help="Incremental sync from cursor high-water mark")
    sp.add_argument("--batch-size", type=int, default=2000)
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("stats", help="Parity and index statistics")
    sp.set_defaults(func=cmd_stats)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
