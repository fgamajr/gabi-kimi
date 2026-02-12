#!/usr/bin/env python3
"""Test aiohttp streaming vs httpx for large file downloads.

This script compares streaming implementations between httpx and aiohttp
to determine which handles large file streaming better, specifically for
the 587MB TCU normas CSV file.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp
import httpx
from aiohttp import ClientTimeout, TCPConnector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test configuration
TEST_URL = "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv"
EXPECTED_SIZE_MB = 587  # Approximate expected size
CHUNK_SIZE = 8192  # 8KB chunks
PROGRESS_INTERVAL_MB = 50  # Log progress every 50MB


@dataclass
class StreamingResult:
    """Result of a streaming test."""
    client: str  # 'httpx' or 'aiohttp'
    success: bool
    bytes_downloaded: int
    chunks_received: int
    duration_seconds: float
    throughput_mbps: float
    error: Optional[str] = None
    sha256_hash: Optional[str] = None


async def stream_with_httpx() -> StreamingResult:
    """Stream large file using httpx.
    
    Uses the current implementation approach from fetcher.py:
    - Dedicated client with streaming-specific timeout
    - No read timeout to allow large file streaming
    - aiter_bytes() for binary streaming
    """
    start_time = time.monotonic()
    client_name = "httpx"
    
    logger.info(f"[{client_name}] Starting download from {TEST_URL}")
    
    # Timeout configuration similar to fetcher.py
    streaming_timeout = httpx.Timeout(
        connect=30.0,    # 30s to establish connection
        read=None,       # No timeout while reading chunks (streaming)
        write=30.0,      # 30s to write (not used for GET)
        pool=30.0        # 30s to get connection from pool
    )
    
    headers = {
        "User-Agent": "GABI-Test/1.0 (Streaming Test)",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
    
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=streaming_timeout,
            follow_redirects=True,
            max_redirects=10,
        ) as client:
            
            logger.info(f"[{client_name}] Opening streaming connection...")
            async with client.stream("GET", TEST_URL) as response:
                response.raise_for_status()
                
                # Get metadata
                content_length = response.headers.get("content-length")
                if content_length:
                    logger.info(f"[{client_name}] Content-Length: {int(content_length) / (1024*1024):.1f} MB")
                else:
                    logger.warning(f"[{client_name}] No Content-Length header")
                
                # Stream content
                bytes_downloaded = 0
                chunks_received = 0
                hasher = hashlib.sha256()
                last_progress_mb = 0
                
                logger.info(f"[{client_name}] Starting to read chunks...")
                
                async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                    bytes_downloaded += len(chunk)
                    chunks_received += 1
                    hasher.update(chunk)
                    
                    # Progress logging
                    current_mb = bytes_downloaded // (1024 * 1024)
                    if current_mb >= last_progress_mb + PROGRESS_INTERVAL_MB:
                        logger.info(
                            f"[{client_name}] Progress: {current_mb}MB "
                            f"({chunks_received} chunks)"
                        )
                        last_progress_mb = current_mb
                
                duration = time.monotonic() - start_time
                throughput = (bytes_downloaded / (1024 * 1024)) / duration if duration > 0 else 0
                
                logger.info(
                    f"[{client_name}] Complete: {bytes_downloaded / (1024*1024):.1f}MB "
                    f"in {duration:.2f}s ({throughput:.2f} MB/s)"
                )
                
                return StreamingResult(
                    client=client_name,
                    success=True,
                    bytes_downloaded=bytes_downloaded,
                    chunks_received=chunks_received,
                    duration_seconds=duration,
                    throughput_mbps=throughput,
                    sha256_hash=hasher.hexdigest(),
                )
                
    except httpx.ReadError as e:
        duration = time.monotonic() - start_time
        logger.error(f"[{client_name}] httpx.ReadError after {duration:.2f}s: {e}")
        return StreamingResult(
            client=client_name,
            success=False,
            bytes_downloaded=0,
            chunks_received=0,
            duration_seconds=duration,
            throughput_mbps=0,
            error=f"httpx.ReadError: {e}",
        )
    except Exception as e:
        duration = time.monotonic() - start_time
        logger.error(f"[{client_name}] Error after {duration:.2f}s: {type(e).__name__}: {e}")
        return StreamingResult(
            client=client_name,
            success=False,
            bytes_downloaded=0,
            chunks_received=0,
            duration_seconds=duration,
            throughput_mbps=0,
            error=f"{type(e).__name__}: {e}",
        )


async def stream_with_aiohttp() -> StreamingResult:
    """Stream large file using aiohttp.
    
    Uses aiohttp with:
    - ClientSession with streaming-specific timeout
    - TCPConnector with keepalive and larger limit
    - response.content.iter_chunked() for streaming
    - No read timeout between chunks
    """
    start_time = time.monotonic()
    client_name = "aiohttp"
    
    logger.info(f"[{client_name}] Starting download from {TEST_URL}")
    
    # Timeout configuration for aiohttp
    # total=None means no total timeout
    # sock_read=None means no timeout between reads
    timeout = ClientTimeout(
        total=None,      # No total timeout
        connect=30.0,    # 30s to establish connection
        sock_read=None,  # No timeout between chunks (critical for streaming)
    )
    
    headers = {
        "User-Agent": "GABI-Test/1.0 (Streaming Test)",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
    
    # TCP connector with optimized settings for large file streaming
    connector = TCPConnector(
        limit=10,                    # Connection pool limit
        limit_per_host=5,            # Connections per host
        enable_cleanup_closed=True,  # Clean up closed connections
        force_close=False,           # Keep connections alive
    )
    
    try:
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector,
        ) as session:
            
            logger.info(f"[{client_name}] Opening streaming connection...")
            async with session.get(TEST_URL) as response:
                response.raise_for_status()
                
                # Get metadata
                content_length = response.headers.get("Content-Length")
                if content_length:
                    logger.info(f"[{client_name}] Content-Length: {int(content_length) / (1024*1024):.1f} MB")
                else:
                    logger.warning(f"[{client_name}] No Content-Length header")
                
                # Stream content using iter_chunked
                bytes_downloaded = 0
                chunks_received = 0
                hasher = hashlib.sha256()
                last_progress_mb = 0
                
                logger.info(f"[{client_name}] Starting to read chunks...")
                
                async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                    bytes_downloaded += len(chunk)
                    chunks_received += 1
                    hasher.update(chunk)
                    
                    # Progress logging
                    current_mb = bytes_downloaded // (1024 * 1024)
                    if current_mb >= last_progress_mb + PROGRESS_INTERVAL_MB:
                        logger.info(
                            f"[{client_name}] Progress: {current_mb}MB "
                            f"({chunks_received} chunks)"
                        )
                        last_progress_mb = current_mb
                
                duration = time.monotonic() - start_time
                throughput = (bytes_downloaded / (1024 * 1024)) / duration if duration > 0 else 0
                
                logger.info(
                    f"[{client_name}] Complete: {bytes_downloaded / (1024*1024):.1f}MB "
                    f"in {duration:.2f}s ({throughput:.2f} MB/s)"
                )
                
                return StreamingResult(
                    client=client_name,
                    success=True,
                    bytes_downloaded=bytes_downloaded,
                    chunks_received=chunks_received,
                    duration_seconds=duration,
                    throughput_mbps=throughput,
                    sha256_hash=hasher.hexdigest(),
                )
                
    except asyncio.TimeoutError as e:
        duration = time.monotonic() - start_time
        logger.error(f"[{client_name}] Timeout after {duration:.2f}s: {e}")
        return StreamingResult(
            client=client_name,
            success=False,
            bytes_downloaded=0,
            chunks_received=0,
            duration_seconds=duration,
            throughput_mbps=0,
            error=f"TimeoutError: {e}",
        )
    except Exception as e:
        duration = time.monotonic() - start_time
        logger.error(f"[{client_name}] Error after {duration:.2f}s: {type(e).__name__}: {e}")
        return StreamingResult(
            client=client_name,
            success=False,
            bytes_downloaded=0,
            chunks_received=0,
            duration_seconds=duration,
            throughput_mbps=0,
            error=f"{type(e).__name__}: {e}",
        )


async def stream_with_aiohttp_text() -> StreamingResult:
    """Stream large file using aiohttp with text decoding.
    
    Similar to fetcher.py's fetch_streaming which uses text chunks.
    Uses response.content.iter_any() and manual decoding.
    """
    start_time = time.monotonic()
    client_name = "aiohttp-text"
    
    logger.info(f"[{client_name}] Starting download (text mode) from {TEST_URL}")
    
    timeout = ClientTimeout(
        total=None,
        connect=30.0,
        sock_read=None,
    )
    
    headers = {
        "User-Agent": "GABI-Test/1.0 (Streaming Test)",
        "Accept": "text/csv,*/*",
        "Connection": "keep-alive",
    }
    
    connector = TCPConnector(
        limit=10,
        limit_per_host=5,
        enable_cleanup_closed=True,
        force_close=False,
    )
    
    try:
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector,
        ) as session:
            
            logger.info(f"[{client_name}] Opening streaming connection...")
            async with session.get(TEST_URL) as response:
                response.raise_for_status()
                
                content_length = response.headers.get("Content-Length")
                if content_length:
                    logger.info(f"[{client_name}] Content-Length: {int(content_length) / (1024*1024):.1f} MB")
                
                bytes_downloaded = 0
                chunks_received = 0
                hasher = hashlib.sha256()
                last_progress_mb = 0
                decoder = None
                encoding = response.charset or "utf-8"
                
                logger.info(f"[{client_name}] Starting to read text chunks (encoding: {encoding})...")
                
                # Use iter_any() for potentially larger chunks
                async for chunk in response.content.iter_any():
                    bytes_downloaded += len(chunk)
                    chunks_received += 1
                    hasher.update(chunk)
                    
                    # Convert to text for testing (similar to fetcher.py approach)
                    text_chunk = chunk.decode(encoding, errors="replace")
                    _ = text_chunk  # Use the text (would be processed in real scenario)
                    
                    current_mb = bytes_downloaded // (1024 * 1024)
                    if current_mb >= last_progress_mb + PROGRESS_INTERVAL_MB:
                        logger.info(
                            f"[{client_name}] Progress: {current_mb}MB "
                            f"({chunks_received} chunks)"
                        )
                        last_progress_mb = current_mb
                
                duration = time.monotonic() - start_time
                throughput = (bytes_downloaded / (1024 * 1024)) / duration if duration > 0 else 0
                
                logger.info(
                    f"[{client_name}] Complete: {bytes_downloaded / (1024*1024):.1f}MB "
                    f"in {duration:.2f}s ({throughput:.2f} MB/s)"
                )
                
                return StreamingResult(
                    client=client_name,
                    success=True,
                    bytes_downloaded=bytes_downloaded,
                    chunks_received=chunks_received,
                    duration_seconds=duration,
                    throughput_mbps=throughput,
                    sha256_hash=hasher.hexdigest(),
                )
                
    except Exception as e:
        duration = time.monotonic() - start_time
        logger.error(f"[{client_name}] Error after {duration:.2f}s: {type(e).__name__}: {e}")
        return StreamingResult(
            client=client_name,
            success=False,
            bytes_downloaded=0,
            chunks_received=0,
            duration_seconds=duration,
            throughput_mbps=0,
            error=f"{type(e).__name__}: {e}",
        )


def print_results(results: list[StreamingResult]) -> None:
    """Print formatted test results."""
    print("\n" + "=" * 80)
    print("STREAMING TEST RESULTS")
    print("=" * 80)
    
    for result in results:
        print(f"\n{'─' * 60}")
        print(f"Client: {result.client.upper()}")
        print(f"{'─' * 60}")
        print(f"  Success:           {result.success}")
        
        if result.success:
            print(f"  Bytes downloaded:  {result.bytes_downloaded:,} ({result.bytes_downloaded / (1024*1024):.2f} MB)")
            print(f"  Chunks received:   {result.chunks_received:,}")
            print(f"  Duration:          {result.duration_seconds:.2f} seconds")
            print(f"  Throughput:        {result.throughput_mbps:.2f} MB/s")
            print(f"  SHA-256:           {result.sha256_hash[:16]}...")
        else:
            print(f"  ERROR:             {result.error}")
            if result.bytes_downloaded > 0:
                print(f"  Partial download:  {result.bytes_downloaded / (1024*1024):.2f} MB")
    
    print("\n" + "=" * 80)
    print("COMPARISON SUMMARY")
    print("=" * 80)
    
    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    
    if successes:
        print(f"\n✓ Successful downloads: {len(successes)}")
        for r in successes:
            print(f"  - {r.client}: {r.bytes_downloaded / (1024*1024):.2f} MB in {r.duration_seconds:.2f}s")
    
    if failures:
        print(f"\n✗ Failed downloads: {len(failures)}")
        for r in failures:
            print(f"  - {r.client}: {r.error}")
    
    print("\n" + "=" * 80)


async def run_tests() -> list[StreamingResult]:
    """Run all streaming tests."""
    results = []
    
    # Test httpx first
    logger.info("\n" + "=" * 60)
    logger.info("TEST 1: httpx streaming")
    logger.info("=" * 60)
    httpx_result = await stream_with_httpx()
    results.append(httpx_result)
    
    # Wait a bit between tests
    await asyncio.sleep(2)
    
    # Test aiohttp (binary)
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: aiohttp streaming (binary)")
    logger.info("=" * 60)
    aiohttp_result = await stream_with_aiohttp()
    results.append(aiohttp_result)
    
    # Wait a bit between tests
    await asyncio.sleep(2)
    
    # Test aiohttp (text)
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: aiohttp streaming (text mode)")
    logger.info("=" * 60)
    aiohttp_text_result = await stream_with_aiohttp_text()
    results.append(aiohttp_text_result)
    
    return results


async def main():
    """Main entry point."""
    print("\n" + "=" * 80)
    print("LARGE FILE STREAMING TEST")
    print("=" * 80)
    print(f"Target URL: {TEST_URL}")
    print(f"Expected size: ~{EXPECTED_SIZE_MB} MB")
    print(f"Chunk size: {CHUNK_SIZE} bytes")
    print("=" * 80 + "\n")
    
    try:
        results = await run_tests()
        print_results(results)
        
        # Determine recommendation
        httpx_success = any(r.success for r in results if r.client == "httpx")
        aiohttp_success = any(r.success for r in results if r.client.startswith("aiohttp"))
        
        print("\n" + "=" * 80)
        print("RECOMMENDATION")
        print("=" * 80)
        
        if httpx_success and aiohttp_success:
            print("\n✓ Both clients successfully downloaded the file.")
            print("  Recommendation: Either client works. No migration needed.")
        elif not httpx_success and aiohttp_success:
            print("\n✗ httpx failed, but aiohttp succeeded!")
            print("  Recommendation: MIGRATE to aiohttp for streaming large files.")
            print("  The aiohttp implementation handles long-running streams better.")
        elif httpx_success and not aiohttp_success:
            print("\n? Unexpected: httpx succeeded but aiohttp failed.")
            print("  Recommendation: Investigate aiohttp configuration.")
        else:
            print("\n✗ Both clients failed.")
            print("  Recommendation: Check network connectivity and server availability.")
        
        print("=" * 80 + "\n")
        
    except Exception as e:
        logger.exception("Test failed")
        raise


if __name__ == "__main__":
    asyncio.run(main())
