#!/usr/bin/env python3
"""Diagnose TCU doc_id vs Elasticsearch _id for es_document / es_tcu_semantic_search alignment.

Usage:
  ES_URL=http://elasticsearch:9200 python3 ops/diagnose_tcu_doc_id.py JURISPRUDENCIA-SELECIONADA-12345
  ES_URL=http://localhost:9200 TCU_ES_INDEX=gabi_tcu_acordaos_v1 python3 ops/diagnose_tcu_doc_id.py

Without doc_id: runs a match_all size=1 on TCU_ES_INDEX and prints _id vs doc_id for that hit.
With doc_id: GET _doc/{id} then term search on doc_id field; prints both outcomes.

Read-only — does not modify the cluster.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _es_request(
    es_url: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, str]:
    full = f"{es_url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        full,
        data=data,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def main() -> int:
    es_url = os.environ.get("ES_URL", "http://localhost:9200").strip()
    tcu_index = os.environ.get("TCU_ES_INDEX", "gabi_tcu_acordaos_v1").strip()
    doc_id_arg = sys.argv[1].strip() if len(sys.argv) > 1 else None

    print(f"ES_URL={es_url}")
    print(f"TCU_ES_INDEX={tcu_index}")

    if not doc_id_arg:
        code, text = _es_request(
            es_url,
            f"/{tcu_index}/_search",
            method="POST",
            body={"size": 1, "query": {"match_all": {}}},
        )
        print(f"\nSample hit (match_all size=1): HTTP {code}")
        if code != 200:
            print(text[:800])
            return 1
        data = json.loads(text)
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            print("No documents in index.")
            return 0
        h = hits[0]
        src = h.get("_source") or {}
        print(f"  _id={h.get('_id')!r}")
        print(f"  _source.doc_id={src.get('doc_id')!r}")
        return 0

    from urllib.parse import quote

    encoded = quote(doc_id_arg, safe="")
    code, text = _es_request(es_url, f"/{tcu_index}/_doc/{encoded}", method="GET")
    print(f"\nGET /_doc/{doc_id_arg!r} (encoded path): HTTP {code}")
    if code == 200:
        data = json.loads(text)
        print(f"  found={data.get('found')} _id={data.get('_id')!r}")
    else:
        print(f"  body (truncated): {text[:500]}")

    code2, text2 = _es_request(
        es_url,
        f"/{tcu_index}/_search",
        method="POST",
        body={"size": 1, "query": {"term": {"doc_id": doc_id_arg}}},
    )
    print(f"\nPOST _search term doc_id={doc_id_arg!r}: HTTP {code2}")
    if code2 == 200:
        data2 = json.loads(text2)
        hits2 = data2.get("hits", {}).get("hits", [])
        if hits2:
            h2 = hits2[0]
            src2 = h2.get("_source") or {}
            print(f"  hit _id={h2.get('_id')!r} _source.doc_id={src2.get('doc_id')!r}")
        else:
            print("  no hits")
    else:
        print(f"  body (truncated): {text2[:500]}")

    print(
        "\nInterpretation: if GET 404 but term search finds a hit, _id != doc_id — "
        "es_document fallback (term on doc_id) fixes MCP fetch."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
