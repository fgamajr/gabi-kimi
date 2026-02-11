"""Hybrid PDF parser combining pdfplumber and VLM extraction."""

import logging
from typing import Any, Dict, Optional

from gabi.pipeline.contracts import FetchedContent, ParseResult
from gabi.pipeline.parser import PDFParser
from gabi.pipeline.vlm.extractor import ClaudeVisionExtractor
from gabi.pipeline.vlm.layout_analyzer import LayoutAnalyzer
from gabi.pipeline.vlm.types import ExtractionStrategy

logger = logging.getLogger(__name__)


class HybridPDFParser:
    """PDF parser that intelligently routes between pdfplumber and VLM.
    
    This parser analyzes each PDF's layout and content to determine
    whether to use the fast pdfplumber extraction or the more capable
    VLM extraction for complex/scanned documents.
    
    Attributes:
        layout_analyzer: Analyzer for determining extraction strategy
        vlm_extractor: VLM-based extractor for complex documents
        legacy_parser: Standard pdfplumber parser for simple documents
    """
    
    def __init__(
        self,
        layout_analyzer: Optional[LayoutAnalyzer] = None,
        vlm_extractor: Optional[ClaudeVisionExtractor] = None,
        fallback_to_vlm: bool = True,
    ):
        """Initialize hybrid parser.
        
        Args:
            layout_analyzer: Analyzer for routing decisions
            vlm_extractor: VLM extractor instance
            fallback_to_vlm: Whether to fallback to VLM on legacy errors
        """
        self.layout_analyzer = layout_analyzer or LayoutAnalyzer()
        self.vlm_extractor = vlm_extractor or ClaudeVisionExtractor()
        self.legacy_parser = PDFParser()
        self.fallback_to_vlm = fallback_to_vlm

    async def parse(
        self,
        content: FetchedContent,
        config: Dict[str, Any],
    ) -> ParseResult:
        """Parse PDF using best strategy.
        
        Args:
            content: Fetched PDF content
            config: Parser configuration with keys:
                - use_vlm: Enable VLM routing (default: False)
                - force_strategy: Force specific strategy
                - max_pages: Maximum pages to process
                - source_id: Source identifier
                
        Returns:
            ParseResult with extracted documents
        """
        # Check if VLM is enabled
        use_vlm = config.get("use_vlm", False)
        force_strategy = config.get("force_strategy")
        source_id = config.get("source_id", "unknown")
        
        if not use_vlm:
            # Use legacy parser only
            return await self.legacy_parser.parse(content, config)
        
        # Determine strategy
        if force_strategy:
            strategy = ExtractionStrategy(force_strategy)
            confidence = 1.0
            reasoning = f"Forced strategy: {strategy.value}"
        else:
            analysis = self.layout_analyzer.analyze(content.get_content())
            strategy = analysis.strategy
            confidence = analysis.confidence
            reasoning = analysis.reasoning
        
        logger.info(
            f"PDF {content.url}: strategy={strategy.value}, "
            f"confidence={confidence:.2f}, reason={reasoning}"
        )
        
        # Route to appropriate parser
        if strategy == ExtractionStrategy.SIMPLE:
            try:
                result = await self.legacy_parser.parse(content, config)
                
                # Check if legacy parser got meaningful content
                total_text = sum(len(d.content) for d in result.documents)
                if total_text < 100 and self.fallback_to_vlm:
                    logger.warning(
                        f"Legacy parser returned minimal text ({total_text} chars), "
                        f"falling back to VLM"
                    )
                    return await self.vlm_extractor.extract_document(
                        content=content,
                        source_id=source_id,
                        max_pages=config.get("max_pages"),
                    )
                
                return result
                
            except Exception as e:
                logger.error(f"Legacy parser failed: {e}")
                if self.fallback_to_vlm:
                    logger.info("Falling back to VLM extraction")
                    return await self.vlm_extractor.extract_document(
                        content=content,
                        source_id=source_id,
                        max_pages=config.get("max_pages"),
                    )
                raise
        
        else:
            # Use VLM for complex or scanned documents
            return await self.vlm_extractor.extract_document(
                content=content,
                source_id=source_id,
                max_pages=config.get("max_pages"),
            )
