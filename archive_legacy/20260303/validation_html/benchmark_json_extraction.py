"""Benchmark script for JSON extraction methods.

This script benchmarks different JSON extraction approaches on real data
and generates a performance report.

Usage:
    python validation/benchmark_json_extraction.py
    python validation/benchmark_json_extraction.py --files data/phase0/2023-01-probe/2023-01-03/*.html
    python validation/benchmark_json_extraction.py --method regex --runs 5
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time
import tracemalloc
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.json_extractor import (
    JsonExtractor,
    ExtractionMethod,
    JsonExtractorBenchmark,
    create_optimized_extractor,
    extract_articles,
    HAS_BS4,
    HAS_LXML,
    HAS_IJSON,
)


def find_test_files(base_dir: Path, max_files: int = 10) -> list[Path]:
    """Find HTML files with params script tag."""
    test_files = []
    
    for html_file in base_dir.rglob("*.html"):
        if len(test_files) >= max_files:
            break
        # Quick check if file contains params script
        try:
            content = html_file.read_text(encoding="utf-8", errors="ignore")
            if '<script id="params"' in content or "<script id='params'" in content:
                test_files.append(html_file)
        except Exception:
            continue
    
    return sorted(test_files)


def benchmark_memory_usage(file_path: Path, method: ExtractionMethod) -> dict[str, Any]:
    """Benchmark memory usage for a specific method."""
    tracemalloc.start()
    
    extractor = JsonExtractor(method=method)
    result = extractor.extract_file(file_path)
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    return {
        "success": result.success,
        "current_mb": current / 1024 / 1024,
        "peak_mb": peak / 1024 / 1024,
        "articles": len(result.json_array),
        "error": result.error,
    }


def test_edge_cases() -> None:
    """Test edge cases for extraction methods."""
    print("\n" + "=" * 80)
    print("EDGE CASE TESTING")
    print("=" * 80)
    
    test_dir = Path("/tmp/json_extract_test")
    test_dir.mkdir(exist_ok=True)
    
    # Test case 1: Missing script tag
    print("\n1. Testing missing script tag...")
    missing_script = test_dir / "missing_script.html"
    missing_script.write_text("<html><body>No script tag here</body></html>")
    
    extractor = JsonExtractor(method=ExtractionMethod.REGEX)
    result = extractor.extract_file(missing_script)
    assert not result.success
    assert "No <script id='params'>" in result.error
    print("   ✓ Correctly handles missing script tag")
    
    # Test case 2: Empty jsonArray
    print("\n2. Testing empty jsonArray...")
    empty_array = test_dir / "empty_array.html"
    empty_array.write_text('''
    <html>
    <script id="params" type="application/json">
    {"section": "DO1", "jsonArray": []}
    </script>
    </html>
    ''')
    
    result = extractor.extract_file(empty_array)
    assert result.success
    assert len(result.json_array) == 0
    assert result.metadata["total_articles"] == 0
    print("   ✓ Correctly handles empty jsonArray")
    
    # Test case 3: Malformed JSON
    print("\n3. Testing malformed JSON...")
    malformed = test_dir / "malformed.html"
    malformed.write_text('''
    <html>
    <script id="params" type="application/json">
    {"section": "DO1", "jsonArray": [invalid json here}
    </script>
    </html>
    ''')
    
    result = extractor.extract_file(malformed)
    assert not result.success
    assert "JSON parsing failed" in result.error
    print("   ✓ Correctly handles malformed JSON")
    
    # Test case 4: Valid JSON with articles
    print("\n4. Testing valid JSON with articles...")
    valid = test_dir / "valid.html"
    valid.write_text('''
    <html>
    <script id="params" type="application/json">
    {
        "section": "DO3",
        "dateUrl": "03-01-2023",
        "jsonArray": [
            {
                "pubName": "DO3",
                "title": "Test Article 1",
                "pubDate": "03/01/2023",
                "content": "Test content 1",
                "hierarchyStr": "Ministry/Test"
            },
            {
                "pubName": "DO3",
                "title": "Test Article 2",
                "pubDate": "03/01/2023",
                "content": "Test content 2",
                "hierarchyStr": "Ministry/Test"
            }
        ]
    }
    </script>
    </html>
    ''')
    
    result = extractor.extract_file(valid)
    assert result.success
    assert len(result.json_array) == 2
    assert result.json_array[0]["title"] == "Test Article 1"
    assert result.metadata["section"] == "DO3"
    assert result.metadata["date_url"] == "03-01-2023"
    print("   ✓ Correctly extracts valid JSON with articles")
    
    # Test case 5: Encoding issues
    print("\n5. Testing encoding issues...")
    encoding_test = test_dir / "encoding.html"
    # Create content with mixed encodings
    encoding_test.write_bytes(b'''
    <html>
    <script id="params" type="application/json">
    {"section": "DO1", "jsonArray": [{"title": "Caf\xe9 \xe0 Paris"}]}
    </script>
    </html>
    ''')
    
    result = extractor.extract_file(encoding_test)
    # Should handle encoding errors gracefully
    print(f"   {'✓' if result.success else '✗'} Handles encoding issues (success={result.success})")
    
    # Test case 6: Large file handling
    print("\n6. Testing large file handling...")
    large_file = test_dir / "large.html"
    # Create a file with many articles
    articles = []
    for i in range(1000):
        articles.append({
            "pubName": "DO3",
            "title": f"Article {i}",
            "pubDate": "03/01/2023",
            "content": "x" * 1000,  # 1KB content per article
        })
    
    import json
    large_json = {"section": "DO3", "jsonArray": articles}
    large_content = f'''
    <html>
    <head><title>Large File</title></head>
    <body>
    <script id="params" type="application/json">
    {json.dumps(large_json)}
    </script>
    </body>
    </html>
    '''
    large_file.write_text(large_content)
    
    file_size_mb = large_file.stat().st_size / 1024 / 1024
    
    # Test with different methods
    for method in [ExtractionMethod.REGEX, ExtractionMethod.MEMORY_MAP]:
        mem_result = benchmark_memory_usage(large_file, method)
        print(f"   {method.name}: {mem_result['peak_mb']:.2f} MB peak, "
              f"{mem_result['articles']} articles")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir)
    
    print("\n✓ All edge case tests completed")


def run_performance_benchmark(files: list[Path], runs: int = 3) -> None:
    """Run performance benchmark on real files."""
    print("\n" + "=" * 80)
    print("PERFORMANCE BENCHMARK")
    print("=" * 80)
    
    if not files:
        print("No test files found!")
        return
    
    print(f"\nTest files ({len(files)}):")
    for f in files:
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  - {f.name}: {size_mb:.2f} MB")
    
    # Run benchmark
    benchmark = JsonExtractorBenchmark()
    methods = [ExtractionMethod.REGEX]
    
    if HAS_BS4:
        methods.append(ExtractionMethod.BEAUTIFULSOUP)
    if HAS_LXML:
        methods.append(ExtractionMethod.LXML)
    if HAS_IJSON:
        methods.append(ExtractionMethod.STREAMING)
    methods.append(ExtractionMethod.MEMORY_MAP)
    
    results = benchmark.run_benchmark(files, methods=methods, benchmark_runs=runs)
    benchmark.print_summary()
    
    # Detailed comparison for largest file
    largest = max(files, key=lambda p: p.stat().st_size)
    print(f"\nDetailed comparison for largest file ({largest.name}):")
    print("-" * 80)
    
    largest_results = [r for r in results if r.file_path == largest]
    largest_results.sort(key=lambda r: r.elapsed_ms)
    
    print(f"{'Method':<20} {'Time (ms)':<12} {'Throughput (MB/s)':<20} {'Status'}")
    print("-" * 80)
    for r in largest_results:
        throughput = (r.file_size_bytes / (r.elapsed_ms / 1000)) / 1024 / 1024 if r.elapsed_ms > 0 else 0
        status = "✓" if r.success else f"✗ {r.error[:30]}"
        print(f"{r.method:<20} {r.elapsed_ms:>10.2f}  {throughput:>18.2f}  {status}")


def test_convenience_function(files: list[Path]) -> None:
    """Test the convenience function."""
    print("\n" + "=" * 80)
    print("CONVENIENCE FUNCTION TEST")
    print("=" * 80)
    
    if not files:
        print("No test files available")
        return
    
    test_file = files[0]
    print(f"\nTesting extract_articles() on {test_file.name}...")
    
    try:
        start = time.perf_counter()
        articles = extract_articles(test_file)
        elapsed = (time.perf_counter() - start) * 1000
        print(f"  ✓ Extracted {len(articles)} articles in {elapsed:.2f} ms")
        if articles:
            print(f"  ✓ Sample article keys: {list(articles[0].keys())[:5]}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark JSON extraction methods for leiturajornal pages"
    )
    parser.add_argument(
        "--files",
        nargs="+",
        help="Specific HTML files to test"
    )
    parser.add_argument(
        "--data-dir",
        default="data/phase0",
        help="Base directory to search for test files"
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=5,
        help="Maximum number of test files to use"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of benchmark runs per method"
    )
    parser.add_argument(
        "--skip-edge-cases",
        action="store_true",
        help="Skip edge case testing"
    )
    parser.add_argument(
        "--memory-profile",
        action="store_true",
        help="Run detailed memory profiling"
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("JSON EXTRACTION BENCHMARK")
    print("=" * 80)
    
    # Print available libraries
    print("\nAvailable libraries:")
    print(f"  BeautifulSoup4: {'✓' if HAS_BS4 else '✗'}")
    print(f"  lxml: {'✓' if HAS_LXML else '✗'}")
    print(f"  ijson: {'✓' if HAS_IJSON else '✗'}")
    
    # Find or use test files
    if args.files:
        test_files = [Path(f) for f in args.files]
    else:
        data_dir = Path(args.data_dir)
        if data_dir.exists():
            print(f"\nSearching for test files in {data_dir}...")
            test_files = find_test_files(data_dir, max_files=args.max_files)
        else:
            test_files = []
    
    # Run edge case tests
    if not args.skip_edge_cases:
        test_edge_cases()
    
    # Run performance benchmark
    if test_files:
        run_performance_benchmark(test_files, runs=args.runs)
        test_convenience_function(test_files)
    else:
        print("\nNo test files found. Please provide files or ensure data directory exists.")
    
    # Memory profiling if requested
    if args.memory_profile and test_files:
        print("\n" + "=" * 80)
        print("MEMORY PROFILING")
        print("=" * 80)
        
        largest = max(test_files, key=lambda p: p.stat().st_size)
        print(f"\nProfiling {largest.name} ({largest.stat().st_size / 1024 / 1024:.2f} MB)...")
        
        for method in [ExtractionMethod.REGEX, ExtractionMethod.MEMORY_MAP]:
            print(f"\n{method.name}:")
            mem_result = benchmark_memory_usage(largest, method)
            print(f"  Current memory: {mem_result['current_mb']:.2f} MB")
            print(f"  Peak memory: {mem_result['peak_mb']:.2f} MB")
            print(f"  Articles extracted: {mem_result['articles']}")
    
    print("\n" + "=" * 80)
    print("BENCHMARK COMPLETE")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
