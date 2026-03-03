"""Optimized JSON extractor for leiturajornal pages.

This module provides multiple strategies for extracting JSON data from
leiturajornal HTML pages, with a focus on performance for bulk processing.

Memory considerations for large files (3MB+):
- The JSON content itself can be 1-2MB per file
- Full DOM parsing adds additional overhead
- Streaming parsers use less memory but are slower
- Regex extraction is fastest for simple extraction tasks

Example usage:
    >>> from validation.json_extractor import JsonExtractor
    >>> extractor = JsonExtractor(method="regex")
    >>> result = extractor.extract_file(Path("do3.html"))
    >>> articles = result.json_array
    >>> print(f"Found {len(articles)} articles")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
import io
import json
import mmap
import os
from pathlib import Path
import re
import time
from typing import Any, Callable

# Optional imports - graceful degradation if not available
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from lxml import html as lhtml
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

try:
    import ijson
    HAS_IJSON = True
except ImportError:
    HAS_IJSON = False


class ExtractionMethod(Enum):
    """Available extraction methods."""
    REGEX = auto()  # Fastest for simple extraction
    BEAUTIFULSOUP = auto()  # Good balance of speed and robustness
    LXML = auto()  # Fast but requires C extension
    STREAMING = auto()  # Lowest memory usage for large files
    MEMORY_MAP = auto()  # Uses mmap for very large files


class JsonExtractionError(Exception):
    """Base exception for JSON extraction errors."""
    pass


class MissingScriptTagError(JsonExtractionError):
    """Raised when the params script tag is not found."""
    pass


class MalformedJsonError(JsonExtractionError):
    """Raised when JSON parsing fails."""
    pass


class EncodingError(JsonExtractionError):
    """Raised when encoding issues are encountered."""
    pass


@dataclass(slots=True)
class ExtractionResult:
    """Result of a JSON extraction operation.
    
    Attributes:
        success: Whether extraction was successful
        json_array: List of article objects from jsonArray field
        raw_json: The raw JSON string extracted (for debugging)
        metadata: Additional metadata about the extraction
        error: Error message if extraction failed
        elapsed_ms: Time taken for extraction in milliseconds
        memory_bytes: Approximate memory used during extraction
    """
    success: bool
    json_array: list[dict[str, Any]] = field(default_factory=list)
    raw_json: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    elapsed_ms: float = 0.0
    memory_bytes: int = 0


@dataclass(slots=True)
class BenchmarkResult:
    """Result of a benchmark run."""
    method: str
    file_path: Path
    file_size_bytes: int
    success: bool
    elapsed_ms: float
    articles_count: int
    memory_bytes: int
    error: str = ""


class JsonExtractor:
    """High-performance JSON extractor for leiturajornal pages.
    
    This extractor is optimized for bulk processing of HTML files containing
    article listings in a <script id="params" type="application/json"> tag.
    
    The extractor supports multiple parsing strategies:
    - regex: Fastest method using regex to extract JSON (recommended for bulk)
    - beautifulsoup: Uses BeautifulSoup for robust HTML parsing
    - lxml: Uses lxml for fast C-accelerated parsing
    - streaming: Uses ijson for memory-efficient parsing of very large files
    - memory_map: Uses mmap for files that don't fit in memory
    
    Attributes:
        method: The extraction method to use
        encoding: Text encoding for reading files (default: utf-8)
        max_file_size_mb: Maximum file size to process in memory (default: 10)
        validate_json: Whether to validate JSON structure (default: True)
    """
    
    # Pre-compiled regex for better performance
    _PARAMS_SCRIPT_RE = re.compile(
        r'<script\s+id=["\']params["\']\s+type=["\']application/json["\']\s*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE
    )
    
    def __init__(
        self,
        method: ExtractionMethod = ExtractionMethod.REGEX,
        encoding: str = "utf-8",
        max_file_size_mb: float = 10.0,
        validate_json: bool = True,
    ) -> None:
        self.method = method
        self.encoding = encoding
        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)
        self.validate_json = validate_json
        
    def extract_file(self, file_path: Path | str) -> ExtractionResult:
        """Extract JSON from a single HTML file.
        
        Args:
            file_path: Path to the HTML file
            
        Returns:
            ExtractionResult with extracted data or error information
        """
        path = Path(file_path)
        if not path.exists():
            return ExtractionResult(
                success=False,
                error=f"File not found: {path}"
            )
        
        file_size = path.stat().st_size
        
        # Auto-switch to memory-mapped method for very large files
        if file_size > self.max_file_size_bytes and self.method != ExtractionMethod.MEMORY_MAP:
            return self._extract_mmap(path)
        
        start_time = time.perf_counter()
        
        try:
            if self.method == ExtractionMethod.REGEX:
                result = self._extract_regex(path)
            elif self.method == ExtractionMethod.BEAUTIFULSOUP:
                result = self._extract_beautifulsoup(path)
            elif self.method == ExtractionMethod.LXML:
                result = self._extract_lxml(path)
            elif self.method == ExtractionMethod.STREAMING:
                result = self._extract_streaming(path)
            elif self.method == ExtractionMethod.MEMORY_MAP:
                result = self._extract_mmap(path)
            else:
                result = ExtractionResult(success=False, error=f"Unknown method: {self.method}")
        except MissingScriptTagError as e:
            result = ExtractionResult(success=False, error=str(e))
        except MalformedJsonError as e:
            result = ExtractionResult(success=False, error=str(e))
        except EncodingError as e:
            result = ExtractionResult(success=False, error=str(e))
        except Exception as e:
            result = ExtractionResult(success=False, error=f"Unexpected error: {e}")
        
        result.elapsed_ms = (time.perf_counter() - start_time) * 1000
        result.memory_bytes = file_size  # Approximate
        
        return result
    
    def extract_batch(
        self,
        file_paths: list[Path | str],
        progress_callback: Callable[[int, int], None] | None = None
    ) -> list[ExtractionResult]:
        """Extract JSON from multiple files.
        
        Args:
            file_paths: List of paths to HTML files
            progress_callback: Optional callback(current, total) for progress updates
            
        Returns:
            List of ExtractionResult objects
        """
        results = []
        total = len(file_paths)
        
        for i, path in enumerate(file_paths):
            results.append(self.extract_file(path))
            if progress_callback:
                progress_callback(i + 1, total)
        
        return results
    
    def _extract_regex(self, path: Path) -> ExtractionResult:
        """Extract using regex - fastest method."""
        try:
            html = path.read_text(encoding=self.encoding, errors="ignore")
        except UnicodeDecodeError as e:
            raise EncodingError(f"Failed to decode file: {e}")
        
        match = self._PARAMS_SCRIPT_RE.search(html)
        if not match:
            raise MissingScriptTagError(f"No <script id='params'> tag found in {path}")
        
        json_str = match.group(1).strip()
        return self._parse_json_content(json_str)
    
    def _extract_beautifulsoup(self, path: Path) -> ExtractionResult:
        """Extract using BeautifulSoup - robust but slower."""
        if not HAS_BS4:
            return ExtractionResult(
                success=False,
                error="beautifulsoup4 not installed. Install with: pip install beautifulsoup4"
            )
        
        try:
            html = path.read_bytes()
        except IOError as e:
            return ExtractionResult(success=False, error=f"Failed to read file: {e}")
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            script_tag = soup.find('script', id='params', type='application/json')
            
            if not script_tag:
                raise MissingScriptTagError(f"No <script id='params'> tag found in {path}")
            
            json_str = script_tag.string
            if not json_str:
                raise MalformedJsonError("Script tag is empty")
            
            return self._parse_json_content(json_str.strip())
        except Exception as e:
            if isinstance(e, (MissingScriptTagError, MalformedJsonError)):
                raise
            raise MalformedJsonError(f"BeautifulSoup parsing failed: {e}")
    
    def _extract_lxml(self, path: Path) -> ExtractionResult:
        """Extract using lxml - fast but requires C extension."""
        if not HAS_LXML:
            return ExtractionResult(
                success=False,
                error="lxml not installed. Install with: pip install lxml"
            )
        
        try:
            html = path.read_bytes()
        except IOError as e:
            return ExtractionResult(success=False, error=f"Failed to read file: {e}")
        
        try:
            tree = lhtml.fromstring(html)
            script_tags = tree.xpath('//script[@id="params"][@type="application/json"]')
            
            if not script_tags:
                raise MissingScriptTagError(f"No <script id='params'> tag found in {path}")
            
            json_str = script_tags[0].text
            if not json_str:
                raise MalformedJsonError("Script tag is empty")
            
            return self._parse_json_content(json_str.strip())
        except Exception as e:
            if isinstance(e, (MissingScriptTagError, MalformedJsonError)):
                raise
            raise MalformedJsonError(f"lxml parsing failed: {e}")
    
    def _extract_streaming(self, path: Path) -> ExtractionResult:
        """Extract using streaming parser for very large files."""
        if not HAS_IJSON:
            return ExtractionResult(
                success=False,
                error="ijson not installed. Install with: pip install ijson"
            )
        
        # First extract the JSON string using regex (memory efficient)
        try:
            html = path.read_text(encoding=self.encoding, errors="ignore")
        except UnicodeDecodeError as e:
            raise EncodingError(f"Failed to decode file: {e}")
        
        match = self._PARAMS_SCRIPT_RE.search(html)
        if not match:
            raise MissingScriptTagError(f"No <script id='params'> tag found in {path}")
        
        json_str = match.group(1).strip()
        
        # Use streaming parser for the jsonArray field
        try:
            json_bytes = json_str.encode('utf-8')
            json_stream = io.BytesIO(json_bytes)
            
            articles = []
            # Stream through jsonArray items without loading full JSON
            for item in ijson.items(json_stream, 'jsonArray.item'):
                articles.append(item)
            
            return ExtractionResult(
                success=True,
                json_array=articles,
                raw_json=json_str[:1000] if self.validate_json else "",
                metadata={
                    "total_articles": len(articles),
                    "method": "streaming",
                    "streaming_parser": "ijson"
                }
            )
        except Exception as e:
            raise MalformedJsonError(f"Streaming JSON parsing failed: {e}")
    
    def _extract_mmap(self, path: Path) -> ExtractionResult:
        """Extract using memory-mapped files for very large files."""
        try:
            with open(path, 'rb') as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    # Search for the script tag in memory-mapped file
                    # This is more memory efficient than reading entire file
                    
                    # Look for the start pattern
                    start_pattern = b'<script id="params" type="application/json">'
                    end_pattern = b'</script>'
                    
                    start_idx = mm.find(start_pattern)
                    if start_idx == -1:
                        # Try with single quotes
                        start_pattern = b"<script id='params' type='application/json'>"
                        start_idx = mm.find(start_pattern)
                    
                    if start_idx == -1:
                        raise MissingScriptTagError(f"No <script id='params'> tag found in {path}")
                    
                    # Find the end of the script content
                    content_start = start_idx + len(start_pattern)
                    end_idx = mm.find(end_pattern, content_start)
                    
                    if end_idx == -1:
                        raise MalformedJsonError("Could not find closing </script> tag")
                    
                    # Extract JSON bytes
                    json_bytes = mm[content_start:end_idx]
                    
                    try:
                        json_str = json_bytes.decode(self.encoding, errors="ignore")
                    except UnicodeDecodeError as e:
                        raise EncodingError(f"Failed to decode JSON content: {e}")
                    
                    return self._parse_json_content(json_str.strip())
        except IOError as e:
            return ExtractionResult(success=False, error=f"File I/O error: {e}")
    
    def _parse_json_content(self, json_str: str) -> ExtractionResult:
        """Parse JSON string and extract jsonArray."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise MalformedJsonError(f"JSON parsing failed: {e}")
        
        if not isinstance(data, dict):
            raise MalformedJsonError("JSON root is not an object")
        
        json_array = data.get("jsonArray", [])
        
        if not isinstance(json_array, list):
            raise MalformedJsonError("jsonArray field is not a list")
        
        # Extract metadata
        metadata = {
            "total_articles": len(json_array),
            "method": self.method.name.lower(),
            "has_pub_name": any("pubName" in item for item in json_array[:1]),
            "has_hierarchy": any("hierarchyStr" in item for item in json_array[:1]),
        }
        
        # Add section info if available
        if "section" in data:
            metadata["section"] = data["section"]
        if "dateUrl" in data:
            metadata["date_url"] = data["dateUrl"]
        
        return ExtractionResult(
            success=True,
            json_array=json_array,
            raw_json=json_str[:1000] if self.validate_json else "",
            metadata=metadata
        )


class JsonExtractorBenchmark:
    """Benchmark different extraction methods."""
    
    def __init__(self) -> None:
        self.results: list[BenchmarkResult] = []
    
    def run_benchmark(
        self,
        file_paths: list[Path],
        methods: list[ExtractionMethod] | None = None,
        warmup_runs: int = 1,
        benchmark_runs: int = 3
    ) -> list[BenchmarkResult]:
        """Run benchmark on multiple files with different methods.
        
        Args:
            file_paths: List of HTML files to benchmark
            methods: List of methods to test (default: all available)
            warmup_runs: Number of warmup runs per file/method
            benchmark_runs: Number of benchmark runs per file/method
            
        Returns:
            List of benchmark results
        """
        if methods is None:
            methods = list(ExtractionMethod)
        
        results = []
        
        for file_path in file_paths:
            file_size = file_path.stat().st_size
            print(f"\nBenchmarking {file_path.name} ({file_size / 1024:.1f} KB)...")
            
            for method in methods:
                # Skip unavailable methods
                if method == ExtractionMethod.BEAUTIFULSOUP and not HAS_BS4:
                    print(f"  Skipping {method.name}: beautifulsoup4 not installed")
                    continue
                if method == ExtractionMethod.LXML and not HAS_LXML:
                    print(f"  Skipping {method.name}: lxml not installed")
                    continue
                if method == ExtractionMethod.STREAMING and not HAS_IJSON:
                    print(f"  Skipping {method.name}: ijson not installed")
                    continue
                
                extractor = JsonExtractor(method=method)
                
                # Warmup runs
                for _ in range(warmup_runs):
                    extractor.extract_file(file_path)
                
                # Benchmark runs
                times = []
                success = False
                articles_count = 0
                error = ""
                
                for run in range(benchmark_runs):
                    result = extractor.extract_file(file_path)
                    times.append(result.elapsed_ms)
                    success = result.success
                    articles_count = len(result.json_array)
                    if not result.success:
                        error = result.error
                
                avg_time = sum(times) / len(times) if times else 0
                
                bench_result = BenchmarkResult(
                    method=method.name,
                    file_path=file_path,
                    file_size_bytes=file_size,
                    success=success,
                    elapsed_ms=avg_time,
                    articles_count=articles_count,
                    memory_bytes=file_size,
                    error=error
                )
                results.append(bench_result)
                
                status = "✓" if success else "✗"
                print(f"  {status} {method.name:15} {avg_time:8.2f} ms  ({articles_count} articles)")
        
        self.results = results
        return results
    
    def print_summary(self) -> None:
        """Print benchmark summary."""
        if not self.results:
            print("No benchmark results available.")
            return
        
        print("\n" + "=" * 80)
        print("BENCHMARK SUMMARY")
        print("=" * 80)
        
        # Group by method
        by_method: dict[str, list[BenchmarkResult]] = {}
        for r in self.results:
            by_method.setdefault(r.method, []).append(r)
        
        for method, results in sorted(by_method.items()):
            success_count = sum(1 for r in results if r.success)
            total_count = len(results)
            avg_time = sum(r.elapsed_ms for r in results if r.success) / max(success_count, 1)
            avg_throughput = sum(r.file_size_bytes / (r.elapsed_ms / 1000) for r in results if r.success) / max(success_count, 1)
            
            print(f"\n{method}:")
            print(f"  Success rate: {success_count}/{total_count}")
            print(f"  Avg time: {avg_time:.2f} ms")
            print(f"  Avg throughput: {avg_throughput / 1024 / 1024:.2f} MB/s")


def create_optimized_extractor(file_size_bytes: int | None = None) -> JsonExtractor:
    """Factory function to create an optimized extractor based on file size.
    
    Args:
        file_size_bytes: Optional file size to optimize for
        
    Returns:
        JsonExtractor configured for optimal performance
    """
    # Default to regex for best performance
    if file_size_bytes is None or file_size_bytes < 5 * 1024 * 1024:  # < 5MB
        return JsonExtractor(method=ExtractionMethod.REGEX)
    elif file_size_bytes < 50 * 1024 * 1024:  # < 50MB
        return JsonExtractor(method=ExtractionMethod.MEMORY_MAP)
    else:
        return JsonExtractor(method=ExtractionMethod.STREAMING)


# Convenience function for simple use cases
def extract_articles(file_path: Path | str) -> list[dict[str, Any]]:
    """Extract articles from a leiturajornal HTML file.
    
    This is a convenience function for simple use cases.
    For bulk processing, use JsonExtractor directly.
    
    Args:
        file_path: Path to the HTML file
        
    Returns:
        List of article dictionaries
        
    Raises:
        JsonExtractionError: If extraction fails
    """
    extractor = create_optimized_extractor()
    result = extractor.extract_file(file_path)
    
    if not result.success:
        raise JsonExtractionError(result.error)
    
    return result.json_array
