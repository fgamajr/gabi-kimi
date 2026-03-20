"""Ingest TCU Súmulas, Jurisprudência Selecionada, and Respostas a Consulta.

Downloads CSVs from TCU open data, processes, and indexes into
gabi_tcu_acordaos_v1 (same index as acórdãos, with authority_level).

Usage:
  python -m src.backend.ingest.tcu_jurisprudencia_ingest --all
  python -m src.backend.ingest.tcu_jurisprudencia_ingest --sumulas
  python -m src.backend.ingest.tcu_jurisprudencia_ingest --jurisprudencia
  python -m src.backend.ingest.tcu_jurisprudencia_ingest --respostas
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import httpx
import pymongo

from src.backend.ingest.tcu_jurisprudencia_processor import (
    BOLETIM_JURIS_URL,
    BOLETIM_LC_URL,
    BOLETIM_PESSOAL_URL,
    JURISPRUDENCIA_URL,
    RESPOSTA_URL,
    SUMULA_URL,
    boletim_juris_to_es_doc,
    boletim_lc_to_es_doc,
    boletim_pessoal_to_es_doc,
    enunciado_hash,
    iter_csv_rows,
    jurisprudencia_to_es_doc,
    resposta_consulta_to_es_doc,
    sumula_to_es_doc,
)

_TCU_INDEX = "gabi_tcu_acordaos_v1"
_MONGO_COLLECTION = "tcu_acordaos"


def _log(msg: str) -> None:
    print(f"[tcu-juris] {msg}", flush=True)


def _es_url() -> str:
    return os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")


def _mongo_client():
    uri = os.getenv("MONGO_STRING", "mongodb://mongo:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    client = pymongo.MongoClient(uri)
    return client, client[db_name]


def _update_mapping() -> None:
    """Add new fields to existing TCU index mapping."""
    es = _es_url()
    index = os.getenv("TCU_ES_INDEX", _TCU_INDEX)
    new_fields = {
        "properties": {
            "enunciado": {"type": "text", "analyzer": "pt_br_full"},
            "excerto": {"type": "text", "analyzer": "pt_br_folded"},
            "authority_level": {"type": "byte"},
            "area": {"type": "keyword"},
            "tema_tcu_oficial": {"type": "keyword"},
            "subtema_tcu": {"type": "keyword"},
            "referencia_legal": {"type": "text", "analyzer": "pt_br_folded"},
            "indexacao": {"type": "text", "analyzer": "pt_br_full"},
            "vigente": {"type": "boolean"},
            "paradigmatico": {"type": "boolean"},
            "parent_acordao_key": {"type": "keyword"},
        }
    }
    with httpx.Client(timeout=30) as client:
        resp = client.put(
            f"{es}/{index}/_mapping",
            json=new_fields,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            _log(f"mapping updated for {index}")
        else:
            _log(f"mapping update: {resp.status_code} {resp.text[:200]}")


def download_csv(url: str, cache_dir: str) -> str:
    """Download CSV to cache dir. Returns local path."""
    filename = url.split("/")[-1]
    filepath = os.path.join(cache_dir, filename)
    _log(f"downloading {url}")
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
    _log(f"downloaded {filepath} ({len(resp.content):,} bytes)")
    return filepath


def _es_bulk(docs: list[dict], es_client: httpx.Client) -> tuple[int, int]:
    """Bulk index documents into ES."""
    index = os.getenv("TCU_ES_INDEX", _TCU_INDEX)
    lines: list[str] = []
    for doc in docs:
        doc_id = doc.get("doc_id")
        lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
        lines.append(json.dumps(doc, ensure_ascii=False))
    body = "\n".join(lines) + "\n"
    resp = es_client.post(
        f"{_es_url()}/_bulk",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=60,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    ok = sum(1 for i in items if 200 <= i.get("index", {}).get("status", 500) < 300)
    return ok, len(items) - ok


def ingest_csv(
    url: str,
    converter,
    *,
    mongo_collection,
    es_client: httpx.Client,
    cache_dir: str,
    batch_size: int = 500,
) -> dict[str, int]:
    """Download and ingest a single CSV."""
    stats = {"total": 0, "indexed": 0, "failed": 0, "skipped": 0}

    filepath = download_csv(url, cache_dir)
    csv_filename = os.path.basename(filepath)
    batch: list[dict] = []

    for row in iter_csv_rows(filepath):
        stats["total"] += 1
        try:
            doc = converter(row, csv_filename)
        except Exception as exc:
            stats["skipped"] += 1
            _log(f"skip: {row.get('KEY', '?')}: {exc}")
            continue

        # Mongo upsert
        try:
            mongo_collection.update_one(
                {"_id": doc["doc_id"]},
                {"$set": {**doc, "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as exc:
            _log(f"mongo error: {doc['doc_id']}: {exc}")

        batch.append(doc)
        if len(batch) >= batch_size:
            ok, failed = _es_bulk(batch, es_client)
            stats["indexed"] += ok
            stats["failed"] += failed
            batch = []

    if batch:
        ok, failed = _es_bulk(batch, es_client)
        stats["indexed"] += ok
        stats["failed"] += failed

    _log(f"{csv_filename}: total={stats['total']} indexed={stats['indexed']} failed={stats['failed']} skipped={stats['skipped']}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TCU Súmulas + Jurisprudência + Respostas + Boletins")
    parser.add_argument("--all", action="store_true", help="Ingest all CSVs")
    parser.add_argument("--sumulas", action="store_true")
    parser.add_argument("--jurisprudencia", action="store_true")
    parser.add_argument("--respostas", action="store_true")
    parser.add_argument("--boletins", action="store_true", help="Ingest 3 boletins (jurisprudência, pessoal, LC)")
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()

    if not any([args.all, args.sumulas, args.jurisprudencia, args.respostas, args.boletins]):
        _log("ERROR: specify --all or --sumulas/--jurisprudencia/--respostas/--boletins")
        sys.exit(1)

    cache_dir = args.cache_dir or tempfile.mkdtemp(prefix="tcu_juris_")
    os.makedirs(cache_dir, exist_ok=True)

    # Update ES mapping first
    _update_mapping()

    mongo_client, db = _mongo_client()
    collection = db[_MONGO_COLLECTION]
    es_client = httpx.Client(timeout=60)

    t0 = time.time()
    totals = {"total": 0, "indexed": 0, "failed": 0, "skipped": 0}

    try:
        tasks = []
        if args.all or args.sumulas:
            tasks.append(("Súmulas", SUMULA_URL, sumula_to_es_doc))
        if args.all or args.jurisprudencia:
            tasks.append(("Jurisprudência", JURISPRUDENCIA_URL, jurisprudencia_to_es_doc))
        if args.all or args.respostas:
            tasks.append(("Respostas", RESPOSTA_URL, resposta_consulta_to_es_doc))
        if args.all or args.boletins:
            tasks.append(("Boletim Jurisprudência", BOLETIM_JURIS_URL, boletim_juris_to_es_doc))
            tasks.append(("Boletim Pessoal", BOLETIM_PESSOAL_URL, boletim_pessoal_to_es_doc))
            tasks.append(("Boletim LC", BOLETIM_LC_URL, boletim_lc_to_es_doc))

        for label, url, converter in tasks:
            _log(f"--- {label} ---")
            stats = ingest_csv(
                url, converter,
                mongo_collection=collection,
                es_client=es_client,
                cache_dir=cache_dir,
            )
            for k in totals:
                totals[k] += stats.get(k, 0)
    finally:
        es_client.close()
        mongo_client.close()

    elapsed = time.time() - t0
    _log(f"ALL DONE in {elapsed:.0f}s — total={totals['total']} indexed={totals['indexed']} failed={totals['failed']} skipped={totals['skipped']}")


if __name__ == "__main__":
    main()
