#!/usr/bin/env python3
"""Full tcu_normas ingestion test - no document limit"""

import asyncio
import logging
import sys
import os

os.environ.setdefault('GABI_DATABASE_URL', 'postgresql+asyncpg://gabi:gabi_dev_password@127.0.0.1:5433/gabi')
os.environ.setdefault('GABI_AUTH_ENABLED', 'false')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_full_ingestion():
    """Run full tcu_normas sync without document limit"""
    from gabi.tasks.sync import _run_sync_pipeline_entry
    import uuid

    print("\n" + "="*80)
    print("FULL TCU_NORMAS INGESTION (NO LIMIT)")
    print("="*80 + "\n")

    run_id = str(uuid.uuid4())
    print(f"Run ID: {run_id}\n")

    result = await _run_sync_pipeline_entry(
        source_id="tcu_normas",
        run_id=run_id,
        max_documents_per_source_override=0,  # No limit
        disable_embeddings=False,
    )

    print("\n" + "="*80)
    print("RESULTS:")
    print("="*80)
    print(f"Documents indexed: {result.get('documents_indexed', 0)}")
    print(f"Documents parsed: {result.get('documents_parsed', 0)}")
    print(f"Chunks created: {result.get('chunks_created', 0)}")
    print(f"Embeddings generated: {result.get('embeddings_generated', 0)}")
    print(f"Errors: {len(result.get('errors', []))}")
    print("="*80 + "\n")

    return result

if __name__ == "__main__":
    result = asyncio.run(test_full_ingestion())
    
    docs_indexed = result.get('documents_indexed', 0)
    if docs_indexed > 1000:  # Expecting ~16,000
        print(f"✅ SUCCESS: Indexed {docs_indexed} documents")
        sys.exit(0)
    else:
        print(f"❌ PARTIAL: Only indexed {docs_indexed} documents")
        sys.exit(1)
