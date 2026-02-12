#!/usr/bin/env python3
"""Test to verify the fetch_streaming fix works with TCU server"""

import asyncio
import sys
sys.path.insert(0, '/home/fgamajr/dev/gabi-kimi/src')

from gabi.pipeline.fetcher import ContentFetcher, FetcherConfig

async def test_fetch_streaming():
    """Test fetch_streaming with TCU server"""
    url = "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv"
    
    config = FetcherConfig(
        timeout=600,  # 10 minutes
        max_retries=2,
        max_size_bytes=1024 * 1024 * 1024,  # 1GB
        chunk_size=8192,
    )
    
    fetcher = ContentFetcher(config=config)
    
    try:
        print(f"Starting fetch_streaming test for {url}")
        print(f"Using timeout config: {config.timeout}s")
        
        # Test fetch_streaming
        streaming_content = await fetcher.fetch_streaming(
            url=url,
            source_id="test_tcu_normas"
        )
        
        print(f"✅ Streaming setup successful")
        print(f"   Status: {streaming_content.status_code}")
        print(f"   Content-Type: {streaming_content.content_type}")
        print(f"   Estimated size: {streaming_content.estimated_size_bytes} bytes")
        print(f"   Starting to read chunks...")
        
        chunks_read = 0
        bytes_read = 0
        
        async for chunk in streaming_content.text_chunks:
            chunks_read += 1
            bytes_read += len(chunk.encode('utf-8'))
            
            # Log progress every 50MB
            if bytes_read % (50 * 1024 * 1024) < 8192:
                mb = bytes_read / (1024 * 1024)
                print(f"   Progress: {mb:.1f}MB ({chunks_read} chunks)")
        
        total_mb = bytes_read / (1024 * 1024)
        print(f"\n✅ SUCCESS: Streamed {total_mb:.1f}MB in {chunks_read} chunks")
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await fetcher.close()

if __name__ == "__main__":
    success = asyncio.run(test_fetch_streaming())
    exit(0 if success else 1)
