"""VLM extractor implementation using Claude Vision."""

import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from gabi.pipeline.contracts import FetchedContent, ParsedDocument, ParseResult
from gabi.pipeline.vlm.types import ExtractionMode

logger = logging.getLogger(__name__)


@dataclass
class VLMExtractionResult:
    """Result of VLM extraction for a single page."""
    
    page_number: int
    content_type: str
    title: Optional[str]
    text: str
    structured_content: Dict[str, Any]
    tables: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    confidence: float
    cost_usd: float
    processing_time_ms: int = 0


class ClaudeVisionExtractor:
    """Extract structured text from PDF pages using Claude Vision API.
    
    This extractor uses Anthropic's Claude Vision models to analyze
    document images and extract structured text, tables, and metadata.
    
    Attributes:
        api_key: Anthropic API key
        model: Model name (default: claude-3-5-sonnet-20241022)
        max_tokens: Maximum tokens in response
    """
    
    LEGAL_EXTRACTION_PROMPT = """You are an expert legal document analyst. 
Extract ALL content from this legal document page with high precision.

Rules:
1. Preserve original formatting using Markdown
2. Extract tables as Markdown tables
3. Identify and label: headers, footers, stamps, signatures
4. For stamps/signatures, describe what you see (e.g., "Stamp: TCU Official Seal")
5. Maintain paragraph breaks and list formatting

Output format (JSON):
```json
{
    "page_type": "cover|content|signature|attachment",
    "title": "document title if present",
    "content": "main content in Markdown",
    "tables": [{"headers": [...], "rows": [...]}],
    "special_elements": [
        {"type": "stamp|signature|watermark", "description": "..."}
    ]
}
```

Extract the content now:"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
    ):
        """Initialize the extractor.
        
        Args:
            api_key: Anthropic API key (reads from settings if not provided)
            model: Claude model to use
            max_tokens: Maximum tokens in response
        """
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._client = None

    @property
    def client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                
                api_key = self.api_key
                if api_key is None:
                    from gabi.config import settings
                    api_key = getattr(settings, "anthropic_api_key", None)
                
                self._client = anthropic.AsyncAnthropic(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package required for VLM extraction. "
                    "Install with: pip install anthropic"
                )
        return self._client

    async def extract_document(
        self,
        content: FetchedContent,
        source_id: str,
        extraction_mode: ExtractionMode = ExtractionMode.FULL,
        max_pages: Optional[int] = None,
    ) -> ParseResult:
        """Extract full document using VLM.
        
        Args:
            content: Fetched PDF content
            source_id: Source identifier
            extraction_mode: Mode of extraction
            max_pages: Maximum pages to process
            
        Returns:
            ParseResult with extracted documents
        """
        import time
        import fitz
        
        start_time = time.time()
        pdf_bytes = content.get_content()
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        documents: List[ParsedDocument] = []
        errors: List[Dict[str, Any]] = []
        total_cost = 0.0
        
        pages_to_process = min(len(doc), max_pages or len(doc))
        doc_id_prefix = f"doc_{source_id}_{hash(content.url) % 10000}"
        
        for page_num in range(pages_to_process):
            page_start = time.time()
            try:
                # Convert page to image
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("png")
                
                # Extract with VLM
                result = await self._extract_page(img_bytes, page_num + 1, extraction_mode)
                total_cost += result.cost_usd
                result.processing_time_ms = int((time.time() - page_start) * 1000)
                
                # Create document
                doc_id = f"{doc_id_prefix}_page_{page_num + 1}"
                document = ParsedDocument(
                    document_id=doc_id,
                    source_id=source_id,
                    title=result.title or f"Page {page_num + 1}",
                    content=result.text,
                    content_preview=result.text[:500] if result.text else None,
                    content_type="application/pdf",
                    content_hash=self._generate_content_hash(result.text),
                    url=content.url,
                    metadata={
                        "page_number": page_num + 1,
                        "extraction_method": "vlm_claude",
                        "vlm_model": self.model,
                        "vlm_confidence": result.confidence,
                        "tables_extracted": len(result.tables),
                        "structured_content": result.structured_content,
                        "vlm_cost_usd": result.cost_usd,
                        "processing_time_ms": result.processing_time_ms,
                    },
                    parsed_at=datetime.utcnow(),
                )
                documents.append(document)
                
            except Exception as e:
                logger.error(f"Error extracting page {page_num + 1}: {e}")
                errors.append({
                    "page": page_num + 1,
                    "error": str(e),
                    "error_type": type(e).__name__,
                })
        
        doc.close()
        duration = time.time() - start_time
        
        return ParseResult(
            documents=documents,
            errors=errors,
            raw_content_size=len(pdf_bytes),
            parsed_content_size=sum(len(d.content) for d in documents),
            duration_seconds=duration,
        )

    async def _extract_page(
        self,
        image_bytes: bytes,
        page_number: int,
        mode: ExtractionMode = ExtractionMode.FULL,
    ) -> VLMExtractionResult:
        """Extract single page using Claude Vision.
        
        Args:
            image_bytes: PNG image bytes
            page_number: Page number for reference
            mode: Extraction mode
            
        Returns:
            VLMExtractionResult with extracted content
        """
        import anthropic
        
        # Encode image to base64
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        
        # Build prompt based on mode
        prompt = self._get_prompt_for_mode(mode)
        
        # Call Claude API
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.0,  # Deterministic
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64_image,
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ]
                }]
            )
        except anthropic.RateLimitError as e:
            logger.error(f"Rate limit exceeded: {e}")
            raise
        except anthropic.APIError as e:
            logger.error(f"API error: {e}")
            raise
        
        # Parse response
        content_text = response.content[0].text
        parsed = self._parse_response(content_text)
        
        # Calculate cost (Claude 3.5 Sonnet pricing)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        # $3/M input tokens, $15/M output tokens
        cost_usd = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)
        
        return VLMExtractionResult(
            page_number=page_number,
            content_type=parsed.get("page_type", "unknown"),
            title=parsed.get("title"),
            text=parsed.get("content", ""),
            structured_content=parsed,
            tables=parsed.get("tables", []),
            metadata={"raw_response": content_text},
            confidence=0.95,
            cost_usd=cost_usd,
        )

    def _get_prompt_for_mode(self, mode: ExtractionMode) -> str:
        """Get appropriate prompt for extraction mode."""
        prompts = {
            ExtractionMode.FULL: self.LEGAL_EXTRACTION_PROMPT,
            ExtractionMode.TABLE_ONLY: """Extract only tables from this page. 
Return as JSON: {"tables": [{"headers": [], "rows": []}]}""",
            ExtractionMode.TEXT_ONLY: """Extract only the body text from this page, 
preserving formatting. Return as JSON: {"content": "..."}""",
            ExtractionMode.METADATA: """Extract only headers, footers, page numbers, 
and document metadata. Return as JSON: {"metadata": {...}}""",
        }
        return prompts.get(mode, self.LEGAL_EXTRACTION_PROMPT)

    def _parse_response(self, text: str) -> Dict[str, Any]:
        """Extract JSON from Claude's response."""
        # Try to find JSON block
        json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to parse entire response as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Fallback: return as text content
        return {"content": text, "page_type": "unknown"}

    def _generate_content_hash(self, content: str) -> str:
        """Generate SHA-256 hash of content."""
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()
