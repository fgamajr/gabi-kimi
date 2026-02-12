#!/usr/bin/env python3
"""Minimal test to debug httpx streaming issue"""

import asyncio
import httpx

async def test_httpx_streaming():
    """Test basic httpx streaming"""
    url = "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv"

    # Try with different timeout configurations
    configs = [
        {
            "name": "No read timeout",
            "timeout": httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
        },
        {
            "name": "Long read timeout (300s)",
            "timeout": httpx.Timeout(300.0)
        },
        {
            "name": "No timeout at all",
            "timeout": None
        },
    ]

    for config in configs:
        print(f"\n{'='*80}")
        print(f"Testing: {config['name']}")
        print(f"{'='*80}")

        try:
            async with httpx.AsyncClient(timeout=config['timeout']) as client:
                print(f"Opening stream to {url}...")
                async with client.stream("GET", url) as response:
                    print(f"Status: {response.status_code}")
                    print(f"Content-Length: {response.headers.get('content-length', 'N/A')}")

                    chunks_read = 0
                    bytes_read = 0

                    print("Starting to read chunks...")
                    async for chunk in response.aiter_text():
                        chunks_read += 1
                        bytes_read += len(chunk.encode('utf-8'))

                        # Log progress every 50MB
                        if bytes_read % (50 * 1024 * 1024) < 1024:
                            mb = bytes_read / (1024 * 1024)
                            print(f"Progress: {mb:.1f}MB ({chunks_read} chunks)")

                    total_mb = bytes_read / (1024 * 1024)
                    print(f"\n✅ SUCCESS: Read {total_mb:.1f}MB in {chunks_read} chunks")
                    return True

        except httpx.ReadError as e:
            print(f"❌ ReadError: {e}")
            continue
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            continue

    print("\n❌ ALL CONFIGS FAILED")
    return False

if __name__ == "__main__":
    success = asyncio.run(test_httpx_streaming())
    exit(0 if success else 1)
