#!/usr/bin/env python3
"""Test tcu_normas ingestion outside Celery context"""

import asyncio
import logging
import sys
import os

# Set up environment
os.environ.setdefault('GABI_DATABASE_URL', 'postgresql+asyncpg://gabi:gabi_dev_password@127.0.0.1:5433/gabi')
os.environ.setdefault('GABI_AUTH_ENABLED', 'false')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_direct():
    """Run sync pipeline directly without Celery"""
    from gabi.db import init_db, close_db
    from gabi.tasks.sync import _run_sync_pipeline_entry
    import uuid

    print("\n" + "="*80)
    print("DIRECT TCU_NORMAS SYNC (NO CELERY)")
    print("="*80 + "\n")

    # Run sync with streaming (init_db is called internally)
    run_id = str(uuid.uuid4())
    print(f"Run ID: {run_id}\n")

    result = await _run_sync_pipeline_entry(
        source_id="tcu_normas",
        run_id=run_id,
        max_documents_per_source_override=100,  # Limit to 100 for testing
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
    if result.get('errors'):
        for error in result.get('errors', [])[:5]:
            print(f"  - {error}")
    print("="*80 + "\n")

    return result

if __name__ == "__main__":
    result = asyncio.run(test_direct())

    if result.get('documents_indexed', 0) > 0:
        print("✅ SUCCESS")
        sys.exit(0)
    else:
        print("❌ FAILED")
        sys.exit(1)
