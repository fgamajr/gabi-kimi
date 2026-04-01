#!/usr/bin/env python3
"""Pré-checagens para rollout RAG: cobertura de campo embedding no ES e reachability do reranker.

Uso:
  python3 ops/rag_rollout_checks.py
  ES_URL=http://elasticsearch:9200 ES_ALIAS=gabi_documents python3 ops/rag_rollout_checks.py

Não altera cluster; apenas lê contagens e tenta HTTP GET no base URL do reranker.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _es_post_json(
    url: str, path: str, body: dict[str, object], timeout: float = 30.0
) -> dict[str, object]:
    full = f"{url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        full,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _embedding_exists_count(es_url: str, index: str) -> tuple[bool, int, str]:
    try:
        out = _es_post_json(
            es_url,
            f"/{index}/_count",
            {"query": {"exists": {"field": "embedding"}}},
        )
        return True, int(out.get("count", 0)), ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        return False, 0, f"HTTP {exc.code}: {body}"
    except OSError as exc:
        return False, 0, str(exc)


def _http_get_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(256)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    es_url = os.environ.get("ES_URL", "http://localhost:9200").strip()
    primary = (
        os.environ.get("ES_ALIAS") or os.environ.get("ES_INDEX") or "gabi_documents"
    ).strip()
    chunks = os.environ.get("ES_CHUNKS_INDEX", "gabi_document_chunks_v1").strip()
    tcu = os.environ.get("TCU_ES_INDEX", "gabi_tcu_acordaos_v1").strip()
    reranker_url = os.environ.get("RERANKER_URL", "http://localhost:8902").strip()

    print(f"ES_URL={es_url}")
    indices = [
        ("primary (DOU / alias ou índice)", primary),
        ("chunks", chunks),
        ("TCU acórdãos", tcu),
    ]
    ok_any = False
    es_errors = 0
    for label, idx in indices:
        ok, count, err = _embedding_exists_count(es_url, idx)
        if ok:
            print(f"[embedding] {label} ({idx}): count={count}")
            if count > 0:
                ok_any = True
        else:
            es_errors += 1
            print(f"[embedding] {label} ({idx}): ERRO {err}")

    if es_errors == len(indices):
        print(
            "\nAviso: não foi possível contactar o Elasticsearch para nenhum índice. "
            "Confirme ES_URL e rede antes do rollout.",
        )
    elif not ok_any:
        print(
            "\nAviso: nenhum índice listado devolveu count>0 para exists:embedding. "
            "Verifique alias/índice e dados antes de VECTOR_SEARCH_ENABLED=true.",
        )

    base = reranker_url.rstrip("/")
    ping_urls = [base, f"{base}/health", f"{base}/v1/rerank"]
    print(f"\nRERANKER_URL base={base}")
    for u in ping_urls:
        ok, err = _http_get_ok(u)
        status = "OK" if ok else f"falhou ({err})"
        print(f"  GET {u} -> {status}")

    print(
        "\nPróximos passos: docs/RAG_14DAY_RUNBOOK.md (Fases 1–4). "
        "GET em /v1/rerank pode retornar 405 — só indica que o host responde."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
