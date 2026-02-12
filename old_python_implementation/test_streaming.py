#!/usr/bin/env python3
"""Test script to verify streaming ingestion for tcu_normas"""

import asyncio
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_tcu_normas_streaming():
    """Test tcu_normas ingestion with streaming enabled"""
    import uuid
    from gabi.tasks.sync import _run_sync_pipeline_entry

    print("\n" + "="*80)
    print("TESTING TCU_NORMAS STREAMING INGESTION")
    print("="*80 + "\n")

    # Generate a proper UUID for the run_id
    run_id = str(uuid.uuid4())
    print(f"Run ID: {run_id}\n")

    # Run the sync pipeline for tcu_normas with a limit
    result = await _run_sync_pipeline_entry(
        source_id="tcu_normas",
        run_id=run_id,
        max_documents_per_source_override=100,  # Limit to 100 docs for testing
        disable_embeddings=False,
    )

    print("\n" + "="*80)
    print("STREAMING TEST RESULTS:")
    print("="*80)
    print(f"Documents indexed: {result.get('documents_indexed', 0)}")
    print(f"Documents parsed: {result.get('documents_parsed', 0)}")
    print(f"Chunks created: {result.get('chunks_created', 0)}")
    print(f"Embeddings generated: {result.get('embeddings_generated', 0)}")
    print(f"URLs processed: {result.get('urls_processed', 0)}")
    print(f"Errors: {len(result.get('errors', []))}")
    if result.get('errors'):
        for error in result.get('errors', [])[:5]:  # Show first 5 errors
            print(f"  - {error}")
    print("="*80 + "\n")

    return result

if __name__ == "__main__":
    result = asyncio.run(test_tcu_normas_streaming())

    # Check if successful
    if result.get('documents_indexed', 0) > 0:
        print("✅ SUCCESS: Streaming ingestion worked!")
    else:
        print("❌ FAILED: No documents were indexed")
        exit(1)
