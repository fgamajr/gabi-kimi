"""VLM (Vision-Language Model) integration for PDF processing.

This module provides VLM-based document extraction capabilities
for handling complex layouts, scanned documents, and tables.

Example:
    >>> from gabi.pipeline.vlm import HybridPDFParser, LayoutAnalyzer
    >>> analyzer = LayoutAnalyzer()
    >>> parser = HybridPDFParser(layout_analyzer=analyzer)
    >>> result = await parser.parse(content, config)
"""

from gabi.pipeline.vlm.extractor import ClaudeVisionExtractor, VLMExtractionResult
from gabi.pipeline.vlm.layout_analyzer import LayoutAnalyzer, LayoutAnalysis
from gabi.pipeline.vlm.hybrid_parser import HybridPDFParser
from gabi.pipeline.vlm.types import ExtractionStrategy, ExtractionMode

__all__ = [
    "ClaudeVisionExtractor",
    "VLMExtractionResult",
    "LayoutAnalyzer",
    "LayoutAnalysis",
    "HybridPDFParser",
    "ExtractionStrategy",
    "ExtractionMode",
]
