"""Types and enums for VLM processing."""

from enum import Enum


class ExtractionStrategy(Enum):
    """Strategy for PDF text extraction."""
    
    SIMPLE = "simple"
    """Use pdfplumber for clean, text-based PDFs."""
    
    COMPLEX = "complex"
    """Use VLM for complex layouts (tables, multi-column)."""
    
    SCANNED = "scanned"
    """Use VLM for image-based/scanned documents."""


class ExtractionMode(Enum):
    """Mode of VLM extraction."""
    
    FULL = "full"
    """Extract all content from page."""
    
    TABLE_ONLY = "table_only"
    """Extract only tables."""
    
    TEXT_ONLY = "text_only"
    """Extract only body text."""
    
    METADATA = "metadata"
    """Extract headers, footers, page numbers only."""
