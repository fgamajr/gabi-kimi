"""Verifier pipeline module — confirms doc counts and embedding presence in Elasticsearch."""

from __future__ import annotations

from typing import Any

import httpx

from src.backend.core.logging import bind_pipeline, get_logger
from src.backend.worker.registry import FileStatus, Registry

logger = get_logger(__name__)

ES_INDEX = "gabi_documents_v1"
TOLERANCE_PERCENT = 5  # Allow 5% deviation for dedup


async def run_verify(
    registry: Registry,
    run_id: str,
    es_url: str,
) -> dict[str, Any]:
    """Verify indexed document counts and embedding presence against registry expectations.

    Args:
        registry: SQLite registry instance
        run_id: Pipeline run identifier for logging
        es_url: Elasticsearch base URL

    Returns:
        Stats dict: {"verified": N, "failed": M}
    """
    embedded_files = await registry.get_files_by_status(FileStatus.EMBEDDED)
    verified = 0
    failed = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for file_rec in embedded_files:
            file_id = file_rec["id"]
            bind_pipeline(file_id=file_id)
            filename = file_rec["filename"]
            expected_count = file_rec.get("doc_count") or 0

            try:
                await registry.update_status(file_id, FileStatus.VERIFYING)

                # Query ES for doc count matching this source_zip
                resp = await client.get(
                    f"{es_url}/{ES_INDEX}/_count",
                    params={"q": f"source_zip:{filename}"},
                )
                resp.raise_for_status()
                result = resp.json()
                es_count = result.get("count", 0)

                embedding_resp = await client.post(
                    f"{es_url}/{ES_INDEX}/_search",
                    json={
                        "size": 1,
                        "_source": False,
                        "query": {
                            "bool": {
                                "filter": [{"exists": {"field": "embedding"}}],
                                "should": [
                                    {"term": {"source_zip.keyword": filename}},
                                    {"term": {"source_zip": filename}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    },
                )
                embedding_resp.raise_for_status()
                embedding_hits = embedding_resp.json().get("hits", {}).get("hits", [])
                if not embedding_hits:
                    raise ValueError(f"No embedded documents found in ES for {filename}")

                # Check tolerance
                if expected_count == 0:
                    # If no expected count, just verify something was indexed
                    if es_count > 0:
                        await registry.update_status(file_id, FileStatus.VERIFIED)
                        await registry.add_log_entry(
                            run_id, file_id, "INFO", f"Verified {filename}: {es_count} docs in ES with embedding"
                        )
                        verified += 1
                    else:
                        await registry.update_status(file_id, FileStatus.VERIFY_FAILED)
                        await registry.update_file_fields(
                            file_id, error_message=f"No documents found in ES for {filename}"
                        )
                        await registry.add_log_entry(
                            run_id, file_id, "ERROR", f"Verification failed for {filename}: 0 docs in ES"
                        )
                        failed += 1
                else:
                    # Check within tolerance
                    tolerance = expected_count * TOLERANCE_PERCENT / 100
                    delta = abs(es_count - expected_count)

                    if delta <= tolerance:
                        await registry.update_status(file_id, FileStatus.VERIFIED)
                        await registry.add_log_entry(
                            run_id,
                            file_id,
                            "INFO",
                            f"Verified {filename}: expected={expected_count} actual={es_count} delta={delta}",
                        )
                        verified += 1
                    else:
                        await registry.update_status(file_id, FileStatus.VERIFY_FAILED)
                        await registry.update_file_fields(
                            file_id,
                            error_message=(
                                f"Doc count mismatch: expected={expected_count} "
                                f"actual={es_count} delta={delta} "
                                f"(tolerance={tolerance:.0f})"
                            ),
                        )
                        await registry.add_log_entry(
                            run_id,
                            file_id,
                            "ERROR",
                            f"Verification failed for {filename}: "
                            f"expected={expected_count} actual={es_count} delta={delta}",
                        )
                        failed += 1

            except Exception as e:
                error_msg = str(e)
                logger.error("Verify error for %s: %s", filename, error_msg)
                await registry.update_status(file_id, FileStatus.VERIFY_FAILED)
                await registry.update_file_fields(file_id, error_message=error_msg)
                await registry.add_log_entry(run_id, file_id, "ERROR", f"Verify error for {filename}: {error_msg}")
                failed += 1

    return {"verified": verified, "failed": failed}
