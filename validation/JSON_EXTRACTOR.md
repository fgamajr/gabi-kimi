# JSON Extractor for Leiturajornal Pages

Optimized JSON extraction from leiturajornal HTML pages with multiple parsing strategies, comprehensive benchmarking, and production-ready batch processing.

## Overview

Leiturajornal pages contain article listings in a `<script id="params" type="application/json">` tag. The JSON structure includes:

```json
{
  "section": "DO3",
  "dateUrl": "03-01-2023",
  "jsonArray": [
    {
      "pubName": "DO3",
      "title": "Article Title",
      "pubDate": "03/01/2023",
      "content": "Article content...",
      "hierarchyStr": "Ministry/Department/...",
      "hierarchyList": ["Ministry", "Department", ...]
    }
  ]
}
```

## Installation

```bash
# Basic installation (regex method only)
pip install -r requirements.txt

# Full installation with all methods
pip install beautifulsoup4 lxml ijson
```

## Quick Start

### Simple Extraction

```python
from validation.json_extractor import extract_articles

# Single file extraction
articles = extract_articles("path/to/do3.html")
print(f"Extracted {len(articles)} articles")

# Access article data
for article in articles[:5]:
    print(f"- {article['title']}")
```

### Using the Extractor Class

```python
from validation.json_extractor import JsonExtractor, ExtractionMethod

# Use specific method
extractor = JsonExtractor(method=ExtractionMethod.LXML)
result = extractor.extract_file("path/to/do3.html")

if result.success:
    print(f"Articles: {len(result.json_array)}")
    print(f"Metadata: {result.metadata}")
else:
    print(f"Error: {result.error}")
```

### Batch Processing

```python
from validation.json_extractor_production import BatchProcessor, ProcessingConfig

# Configure processing
config = ProcessingConfig(
    max_workers=4,
    output_format="jsonl",
    progress_interval=50
)

# Process directory
processor = BatchProcessor(config)
result = processor.process_directory(Path("data/html"))

print(f"Processed: {result.success_count}/{result.total_files}")
print(f"Articles: {result.total_articles}")
print(f"Rate: {result.articles_per_second:.1f} articles/sec")
```

### Extract to JSONL

```python
from validation.json_extractor_production import extract_to_jsonl
from pathlib import Path

result = extract_to_jsonl(
    input_dir=Path("data/html"),
    output_file=Path("output/articles.jsonl"),
    max_workers=4
)
```

## Extraction Methods

| Method | Speed | Memory | Use Case |
|--------|-------|--------|----------|
| `REGEX` | Fast | Medium | Default for files < 5MB |
| `BEAUTIFULSOUP` | Slow | High | Robust HTML parsing |
| `LXML` | Fastest | Medium | Best for large files |
| `MEMORY_MAP` | Fast | Low | Files 5-50MB |
| `STREAMING` | Slow | Lowest | Files > 50MB |

### Method Selection

The library automatically selects the best method based on file size:

```python
from validation.json_extractor import create_optimized_extractor

# Auto-select based on file size
file_size = Path("large_file.html").stat().st_size
extractor = create_optimized_extractor(file_size)
```

## Benchmark Results

### Performance (2MB file, 1915 articles)

| Method | Time (ms) | Throughput (MB/s) | Memory (MB) |
|--------|-----------|-------------------|-------------|
| MEMORY_MAP | 18.40 | 108.2 | 12.60 |
| LXML | 19.61 | 101.5 | 12.73 |
| REGEX | 44.57 | 44.6 | 11.16 |
| BEAUTIFULSOUP | 62.31 | 31.9 | 14.03 |

### Recommendations

- **Small files (< 1MB)**: Use `REGEX` or `LXML`
- **Medium files (1-10MB)**: Use `LXML` or `MEMORY_MAP`
- **Large files (> 10MB)**: Use `MEMORY_MAP` or `STREAMING`
- **Very large files (> 50MB)**: Use `STREAMING` with `ijson`

## Memory Usage

### For Large Files (3MB+)

Memory overhead is approximately **5-7x** the file size during extraction:

- **2MB file**: ~12MB peak memory
- **10MB file**: ~50-70MB peak memory
- **50MB file**: ~250-350MB peak memory

### Memory Optimization Tips

1. Use `MEMORY_MAP` for files > 5MB
2. Process files sequentially, not in parallel, for very large files
3. Use `STREAMING` method with `ijson` for minimal memory footprint
4. Set `max_workers=1` when memory is constrained

## Error Handling

### Edge Cases Handled

- **Missing script tag**: `MissingScriptTagError`
- **Malformed JSON**: `MalformedJsonError`
- **Encoding issues**: Automatic fallback with error ignore
- **Empty jsonArray**: Returns empty list (success=True)
- **Large files**: Automatic method switching

### Exception Hierarchy

```
JsonExtractionError
├── MissingScriptTagError
├── MalformedJsonError
└── EncodingError
```

### Error Handling Example

```python
from validation.json_extractor import (
    JsonExtractor,
    JsonExtractionError,
    MissingScriptTagError
)

extractor = JsonExtractor()

for file_path in html_files:
    try:
        result = extractor.extract_file(file_path)
        if result.success:
            process_articles(result.json_array)
        else:
            log_error(file_path, result.error)
    except MissingScriptTagError:
        log_warning(f"No params tag in {file_path}")
    except JsonExtractionError as e:
        log_error(f"Extraction failed: {e}")
```

## Production Deployment

### CLI Usage

```bash
# Extract from directory to JSONL
python validation/json_extractor_production.py data/html output/articles.jsonl 4

# Benchmark different methods
python validation/benchmark_json_extraction.py --files data/html/*.html --runs 5
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY validation/ validation/

CMD ["python", "validation/json_extractor_production.py", "/data/html", "/output/articles.jsonl"]
```

### Monitoring

```python
from validation.json_extractor_production import BatchProcessor, ProcessingConfig
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Process with progress tracking
config = ProcessingConfig(progress_interval=100)
processor = BatchProcessor(config)
result = processor.process_directory(Path("data/html"))

# Log metrics
logger.info(f"Success rate: {result.success_rate:.1f}%")
logger.info(f"Throughput: {result.articles_per_second:.1f} articles/sec")
```

## Testing

### Run Benchmarks

```bash
# Full benchmark with all methods
python validation/benchmark_json_extraction.py

# Memory profiling
python validation/benchmark_json_extraction.py --memory-profile

# Specific files
python validation/benchmark_json_extraction.py --files file1.html file2.html
```

### Run Tests

```bash
# Edge case testing
python -c "from validation.benchmark_json_extraction import test_edge_cases; test_edge_cases()"

# Verify data integrity
python -c "
from pathlib import Path
from validation.json_extractor import JsonExtractor, ExtractionMethod

file_path = Path('data/phase0/2023-01-probe/2023-01-03/do3.html')
for method in ExtractionMethod:
    extractor = JsonExtractor(method=method)
    result = extractor.extract_file(file_path)
    print(f'{method.name}: {len(result.json_array)} articles')
"
```

## API Reference

### JsonExtractor

```python
class JsonExtractor:
    def __init__(
        self,
        method: ExtractionMethod = ExtractionMethod.REGEX,
        encoding: str = "utf-8",
        max_file_size_mb: float = 10.0,
        validate_json: bool = True,
    ) -> None
    
    def extract_file(self, file_path: Path | str) -> ExtractionResult
    def extract_batch(
        self,
        file_paths: list[Path | str],
        progress_callback: Callable[[int, int], None] | None = None
    ) -> list[ExtractionResult]
```

### ExtractionResult

```python
@dataclass
class ExtractionResult:
    success: bool
    json_array: list[dict[str, Any]]  # Article listings
    raw_json: str                     # First 1000 chars (if validate_json=True)
    metadata: dict[str, Any]          # Extraction metadata
    error: str                        # Error message if failed
    elapsed_ms: float                 # Processing time
    memory_bytes: int                 # Approximate memory used
```

### BatchProcessor

```python
class BatchProcessor:
    def __init__(self, config: ProcessingConfig | None = None) -> None
    def process_directory(
        self,
        directory: Path,
        pattern: str = "*.html",
        recursive: bool = True
    ) -> BatchProcessingResult
    def process_files(self, files: list[Path]) -> BatchProcessingResult
    def save_results(
        self,
        result: BatchProcessingResult,
        output_path: Path,
        extraction_results: list[tuple[Path, ExtractionResult]] | None = None
    ) -> None
```

## License

See project LICENSE file.
