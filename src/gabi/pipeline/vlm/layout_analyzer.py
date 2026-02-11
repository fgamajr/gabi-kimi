"""Layout analyzer for determining PDF extraction strategy."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

import numpy as np

from gabi.pipeline.vlm.types import ExtractionStrategy

if TYPE_CHECKING:
    import fitz


@dataclass
class LayoutAnalysis:
    """Result of PDF layout analysis."""
    
    strategy: ExtractionStrategy
    confidence: float
    metrics: dict
    reasoning: str


class LayoutAnalyzer:
    """Analyzes PDF layout to determine best extraction strategy.
    
    This analyzer uses heuristics to decide whether a PDF should be
    processed with pdfplumber (simple text-based) or VLM (complex/scanned).
    
    Attributes:
        image_ratio_threshold: Threshold for image coverage (default: 0.7)
        complexity_threshold: Threshold for layout complexity (default: 0.6)
        min_text_chars: Minimum text characters for simple extraction (default: 100)
    """
    
    def __init__(
        self,
        image_ratio_threshold: float = 0.7,
        complexity_threshold: float = 0.6,
        min_text_chars: int = 100,
    ):
        """Initialize analyzer with thresholds.
        
        Args:
            image_ratio_threshold: Use VLM if image coverage > threshold
            complexity_threshold: Use VLM if complexity > threshold
            min_text_chars: Use VLM if avg text < min_text_chars
        """
        self.image_ratio_threshold = image_ratio_threshold
        self.complexity_threshold = complexity_threshold
        self.min_text_chars = min_text_chars

    def analyze(self, pdf_bytes: bytes, sample_pages: int = 3) -> LayoutAnalysis:
        """Analyze PDF to determine extraction strategy.
        
        Args:
            pdf_bytes: Raw PDF bytes
            sample_pages: Number of pages to sample (default: 3)
            
        Returns:
            LayoutAnalysis with recommended strategy
        """
        import fitz
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        try:
            pages_to_check = min(len(doc), sample_pages)
            
            total_image_ratio = 0.0
            total_complexity = 0.0
            total_text = 0
            has_text_layer = False
            
            for i in range(pages_to_check):
                page = doc[i]
                
                # Check for text layer
                text = page.get_text()
                total_text += len(text)
                if text.strip():
                    has_text_layer = True
                
                # Calculate metrics
                image_ratio = self._calculate_image_ratio(page)
                total_image_ratio += image_ratio
                
                complexity = self._analyze_complexity(page)
                total_complexity += complexity
            
            # Average metrics
            avg_image_ratio = total_image_ratio / pages_to_check if pages_to_check > 0 else 0
            avg_complexity = total_complexity / pages_to_check if pages_to_check > 0 else 0
            avg_text = total_text / pages_to_check if pages_to_check > 0 else 0
            
            # Decision logic
            return self._determine_strategy(
                has_text_layer=has_text_layer,
                avg_image_ratio=avg_image_ratio,
                avg_complexity=avg_complexity,
                avg_text=avg_text,
            )
        
        finally:
            doc.close()

    def _determine_strategy(
        self,
        has_text_layer: bool,
        avg_image_ratio: float,
        avg_complexity: float,
        avg_text: float,
    ) -> LayoutAnalysis:
        """Determine extraction strategy based on metrics."""
        
        if not has_text_layer and avg_image_ratio > self.image_ratio_threshold:
            strategy = ExtractionStrategy.SCANNED
            confidence = min(avg_image_ratio, 0.95)
            reasoning = f"Image-based PDF ({avg_image_ratio:.0%} image coverage)"
            
        elif avg_complexity > self.complexity_threshold:
            strategy = ExtractionStrategy.COMPLEX
            confidence = min(avg_complexity, 0.9)
            reasoning = f"Complex layout detected (complexity: {avg_complexity:.2f})"
            
        elif avg_text < self.min_text_chars:
            strategy = ExtractionStrategy.SCANNED
            confidence = 0.85
            reasoning = f"Low text extraction ({avg_text:.0f} chars), likely image-based"
            
        else:
            strategy = ExtractionStrategy.SIMPLE
            confidence = 0.9
            reasoning = f"Clean layout, sufficient text ({avg_text:.0f} chars)"
        
        return LayoutAnalysis(
            strategy=strategy,
            confidence=confidence,
            metrics={
                "image_ratio": avg_image_ratio,
                "complexity": avg_complexity,
                "avg_text_chars": avg_text,
                "has_text_layer": has_text_layer,
            },
            reasoning=reasoning,
        )

    def _calculate_image_ratio(self, page: "fitz.Page") -> float:
        """Calculate ratio of page covered by images.
        
        Args:
            page: PyMuPDF page object
            
        Returns:
            Ratio of page area covered by images (0-1)
        """
        page_area = page.rect.width * page.rect.height
        
        # Get image rectangles
        image_list = page.get_images(full=True)
        image_area = 0.0
        
        for img_index, img in enumerate(image_list, start=1):
            try:
                xref = img[0]
                pix = page.parent.extract_image(xref)
                if pix:
                    # Estimate area from image dimensions
                    rect = page.get_image_rects(xref)
                    if rect:
                        for r in rect:
                            image_area += r.width * r.height
            except Exception:
                continue
        
        return min(image_area / page_area, 1.0) if page_area > 0 else 0.0

    def _analyze_complexity(self, page: "fitz.Page") -> float:
        """Analyze layout complexity (0-1 scale).
        
        Args:
            page: PyMuPDF page object
            
        Returns:
            Complexity score between 0 and 1
        """
        complexity = 0.0
        
        # Get text blocks
        blocks = page.get_text("blocks")
        
        if not blocks:
            return 0.0
        
        # Multi-column detection
        x_positions = [b[0] for b in blocks if len(b) > 0]  # x0 coordinates
        if len(x_positions) > 1:
            x_std = np.std(x_positions)
            x_range = max(x_positions) - min(x_positions) if x_positions else 1
            if x_range > 0 and x_std / x_range > 0.1:
                complexity += 0.3
        
        # Many blocks indicate complex layout
        if len(blocks) > 20:
            complexity += 0.2
        elif len(blocks) > 10:
            complexity += 0.1
        
        # Table detection via drawings (lines)
        drawings = page.get_drawings()
        line_count = len([d for d in drawings if d.get("type") == "l"])
        if line_count > 20:
            complexity += 0.3
        elif line_count > 10:
            complexity += 0.15
        
        # Check for rotated text
        for block in blocks:
            if len(block) > 6 and block[6] != 0:  # rotation angle
                complexity += 0.2
                break
        
        # Check for varying font sizes (headers, etc.)
        try:
            spans = []
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = span.get("size", 0)
                        if size > 0:
                            spans.append(size)
            
            if spans:
                size_std = np.std(spans)
                if size_std > 2:
                    complexity += 0.1
        except Exception:
            pass
        
        return min(complexity, 1.0)

    def quick_check(self, pdf_bytes: bytes) -> ExtractionStrategy:
        """Quick check for simple routing decisions.
        
        Args:
            pdf_bytes: Raw PDF bytes
            
        Returns:
            Recommended extraction strategy
        """
        analysis = self.analyze(pdf_bytes, sample_pages=1)
        return analysis.strategy
