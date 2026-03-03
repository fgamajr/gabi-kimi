"""Production-ready JSON extraction for leiturajornal pages.

This module provides optimized batch processing with:
- Parallel processing using multiprocessing
- Progress tracking
- Error recovery
- Memory-efficient processing of large files
- Structured logging

Memory usage guidelines:
- Files < 5MB: Use default REGEX method (fastest)
- Files 5-50MB: Use MEMORY_MAP method (good balance)
- Files > 50MB: Use STREAMING method (lowest memory)

Example:
    >>> from validation.json_extractor_production import BatchProcessor
    >>> processor = BatchProcessor(max_workers=4)
    >>> results = processor.process_directory(Path("data/html"))
    >>> print(f"Processed {results.success_count} files")
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import Any, Callable, Iterator

from validation.json_extractor import (
    JsonExtractor,
    ExtractionMethod,
    ExtractionResult,
    create_optimized_extractor,
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchProcessingResult:
    """Result of batch processing operation.
    
    Attributes:
        total_files: Total number of files processed
        success_count: Number of successful extractions
        error_count: Number of failed extractions
        total_articles: Total articles extracted across all files
        elapsed_seconds: Total processing time
        errors: List of error messages
        output_file: Path to output file if saved
    """
    total_files: int
    success_count: int
    error_count: int
    total_articles: int
    elapsed_seconds: float
    errors: list[str] = field(default_factory=list)
    output_file: Path | None = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.success_count / self.total_files) * 100
    
    @property
    def articles_per_second(self) -> float:
        """Calculate extraction throughput."""
        if self.elapsed_seconds == 0:
            return 0.0
        return self.total_articles / self.elapsed_seconds


@dataclass(slots=True)
class ProcessingConfig:
    """Configuration for batch processing.
    
    Attributes:
        max_workers: Number of parallel workers (None = auto)
        chunk_size: Number of files to process per batch
        method: Extraction method to use (None = auto-detect)
        output_format: Output format (json, jsonl, or none)
        save_errors: Whether to save error details
        validate_output: Whether to validate extracted data
        progress_interval: Log progress every N files
    """
    max_workers: int | None = None
    chunk_size: int = 100
    method: ExtractionMethod | None = None
    output_format: str = "jsonl"  # json, jsonl, or none
    save_errors: bool = True
    validate_output: bool = True
    progress_interval: int = 10


class BatchProcessor:
    """High-performance batch processor for leiturajornal HTML files.
    
    This processor is designed for production use with:
    - Automatic worker count based on CPU cores
    - Progress tracking and logging
    - Error recovery and reporting
    - Configurable output formats
    
    Example:
        >>> config = ProcessingConfig(max_workers=4, output_format="jsonl")
        >>> processor = BatchProcessor(config)
        >>> result = processor.process_directory(Path("data/html"))
        >>> processor.save_results(result, Path("output.jsonl"))
    """
    
    def __init__(self, config: ProcessingConfig | None = None) -> None:
        self.config = config or ProcessingConfig()
        self._logger = logger
    
    def process_directory(
        self,
        directory: Path,
        pattern: str = "*.html",
        recursive: bool = True
    ) -> BatchProcessingResult:
        """Process all HTML files in a directory.
        
        Args:
            directory: Root directory to search
            pattern: File pattern to match
            recursive: Whether to search recursively
            
        Returns:
            BatchProcessingResult with statistics
        """
        # Find all matching files
        if recursive:
            files = list(directory.rglob(pattern))
        else:
            files = list(directory.glob(pattern))
        
        return self.process_files(files)
    
    def process_files(self, files: list[Path]) -> BatchProcessingResult:
        """Process a list of files.
        
        Args:
            files: List of HTML file paths
            
        Returns:
            BatchProcessingResult with statistics
        """
        start_time = time.perf_counter()
        
        total_files = len(files)
        success_count = 0
        error_count = 0
        total_articles = 0
        errors = []
        
        self._logger.info(f"Starting batch processing of {total_files} files")
        
        # Use single-threaded processing for small batches
        if total_files < self.config.chunk_size or self.config.max_workers == 1:
            for i, file_path in enumerate(files):
                result = self._process_single_file(file_path)
                
                if result.success:
                    success_count += 1
                    total_articles += len(result.json_array)
                else:
                    error_count += 1
                    if self.config.save_errors:
                        errors.append(f"{file_path}: {result.error}")
                
                if (i + 1) % self.config.progress_interval == 0:
                    self._logger.info(f"Processed {i + 1}/{total_files} files...")
        else:
            # Use parallel processing for larger batches
            with ProcessPoolExecutor(max_workers=self.config.max_workers) as executor:
                # Submit all tasks
                future_to_file = {
                    executor.submit(self._process_single_file, fp): fp 
                    for fp in files
                }
                
                # Collect results as they complete
                completed = 0
                for future in as_completed(future_to_file):
                    file_path = future_to_file[future]
                    completed += 1
                    
                    try:
                        result = future.result()
                        if result.success:
                            success_count += 1
                            total_articles += len(result.json_array)
                        else:
                            error_count += 1
                            if self.config.save_errors:
                                errors.append(f"{file_path}: {result.error}")
                    except Exception as e:
                        error_count += 1
                        if self.config.save_errors:
                            errors.append(f"{file_path}: Exception - {e}")
                    
                    if completed % self.config.progress_interval == 0:
                        self._logger.info(f"Processed {completed}/{total_files} files...")
        
        elapsed = time.perf_counter() - start_time
        
        self._logger.info(
            f"Batch processing complete: {success_count} succeeded, "
            f"{error_count} failed, {total_articles} articles in {elapsed:.2f}s"
        )
        
        return BatchProcessingResult(
            total_files=total_files,
            success_count=success_count,
            error_count=error_count,
            total_articles=total_articles,
            elapsed_seconds=elapsed,
            errors=errors[:100]  # Limit error list size
        )
    
    def process_files_iter(
        self,
        files: list[Path]
    ) -> Iterator[tuple[Path, ExtractionResult]]:
        """Process files and yield results as they complete.
        
        This is useful for processing results incrementally without
        waiting for all files to complete.
        
        Args:
            files: List of HTML file paths
            
        Yields:
            Tuples of (file_path, extraction_result)
        """
        for file_path in files:
            result = self._process_single_file(file_path)
            yield file_path, result
    
    def _process_single_file(self, file_path: Path) -> ExtractionResult:
        """Process a single file with appropriate method."""
        # Auto-detect method based on file size
        if self.config.method is None:
            file_size = file_path.stat().st_size
            extractor = create_optimized_extractor(file_size)
        else:
            extractor = JsonExtractor(method=self.config.method)
        
        return extractor.extract_file(file_path)
    
    def save_results(
        self,
        result: BatchProcessingResult,
        output_path: Path,
        extraction_results: list[tuple[Path, ExtractionResult]] | None = None
    ) -> None:
        """Save processing results to file.
        
        Args:
            result: BatchProcessingResult to save
            output_path: Path to output file
            extraction_results: Optional detailed extraction results
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if self.config.output_format == "json":
            self._save_json(result, output_path, extraction_results)
        elif self.config.output_format == "jsonl":
            self._save_jsonl(result, output_path, extraction_results)
        else:
            self._logger.info(f"Output format '{self.config.output_format}' - not saving")
    
    def _save_json(
        self,
        result: BatchProcessingResult,
        output_path: Path,
        extraction_results: list[tuple[Path, ExtractionResult]] | None
    ) -> None:
        """Save as JSON format."""
        data = {
            "summary": {
                "total_files": result.total_files,
                "success_count": result.success_count,
                "error_count": result.error_count,
                "total_articles": result.total_articles,
                "elapsed_seconds": result.elapsed_seconds,
                "success_rate": result.success_rate,
                "articles_per_second": result.articles_per_second,
            },
            "errors": result.errors,
        }
        
        if extraction_results:
            data["files"] = [
                {
                    "file": str(fp),
                    "success": r.success,
                    "articles": len(r.json_array) if r.success else 0,
                    "error": r.error if not r.success else None,
                    "metadata": r.metadata if r.success else None,
                }
                for fp, r in extraction_results
            ]
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self._logger.info(f"Saved results to {output_path}")
    
    def _save_jsonl(
        self,
        result: BatchProcessingResult,
        output_path: Path,
        extraction_results: list[tuple[Path, ExtractionResult]] | None
    ) -> None:
        """Save as JSON Lines format (one JSON object per line)."""
        with open(output_path, 'w', encoding='utf-8') as f:
            if extraction_results:
                for fp, r in extraction_results:
                    if r.success:
                        for article in r.json_array:
                            record = {
                                "source_file": str(fp),
                                "extraction_metadata": r.metadata,
                                **article
                            }
                            f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        self._logger.info(f"Saved {result.total_articles} articles to {output_path}")


def extract_to_jsonl(
    input_dir: Path,
    output_file: Path,
    pattern: str = "*.html",
    max_workers: int | None = None
) -> BatchProcessingResult:
    """Convenience function to extract all articles to JSONL.
    
    Args:
        input_dir: Directory containing HTML files
        output_file: Output JSONL file path
        pattern: File pattern to match
        max_workers: Number of parallel workers
        
    Returns:
        BatchProcessingResult with statistics
        
    Example:
        >>> result = extract_to_jsonl(
        ...     Path("data/html"),
        ...     Path("output/articles.jsonl"),
        ...     max_workers=4
        ... )
        >>> print(f"Extracted {result.total_articles} articles")
    """
    config = ProcessingConfig(
        max_workers=max_workers,
        output_format="jsonl",
        progress_interval=50
    )
    processor = BatchProcessor(config)
    
    # Collect results for saving
    extraction_results = []
    
    if max_workers == 1:
        # Single-threaded with iterator
        files = list(input_dir.rglob(pattern))
        for fp, result in processor.process_files_iter(files):
            extraction_results.append((fp, result))
    else:
        # Multi-threaded batch processing
        result = processor.process_directory(input_dir, pattern)
        # Re-process to get detailed results for saving
        # (This is inefficient but keeps the API simple)
        files = list(input_dir.rglob(pattern))
        for fp in files:
            file_size = fp.stat().st_size
            extractor = create_optimized_extractor(file_size)
            extraction_results.append((fp, extractor.extract_file(fp)))
        
        processor.save_results(result, output_file, extraction_results)
        return result
    
    # Calculate statistics
    success_count = sum(1 for _, r in extraction_results if r.success)
    error_count = len(extraction_results) - success_count
    total_articles = sum(len(r.json_array) for _, r in extraction_results if r.success)
    
    result = BatchProcessingResult(
        total_files=len(extraction_results),
        success_count=success_count,
        error_count=error_count,
        total_articles=total_articles,
        elapsed_seconds=0,  # Not tracked in this mode
    )
    
    processor.save_results(result, output_file, extraction_results)
    return result


# Example usage and CLI
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python json_extractor_production.py <input_dir> <output_file> [max_workers]")
        print()
        print("Example:")
        print("  python json_extractor_production.py data/html output/articles.jsonl 4")
        sys.exit(1)
    
    input_dir = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    max_workers = int(sys.argv[3]) if len(sys.argv) > 3 else None
    
    if not input_dir.exists():
        print(f"Error: Input directory not found: {input_dir}")
        sys.exit(1)
    
    print(f"Extracting articles from {input_dir}...")
    print(f"Output: {output_file}")
    print(f"Workers: {max_workers or 'auto'}")
    print()
    
    result = extract_to_jsonl(input_dir, output_file, max_workers=max_workers)
    
    print()
    print("=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Files processed: {result.total_files}")
    print(f"Successful: {result.success_count} ({result.success_rate:.1f}%)")
    print(f"Failed: {result.error_count}")
    print(f"Total articles: {result.total_articles}")
    print(f"Throughput: {result.articles_per_second:.1f} articles/sec")
    print(f"Output saved to: {output_file}")
