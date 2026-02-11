# VLM Integration Strategy for GABI

**Vision-Language Models for Document Understanding**  
**Date:** 2026-02-11  
**Status:** Draft for Review  
**Scope:** Replace/Enhance pdfplumber + pytesseract OCR with VLM-based extraction

---

## Executive Summary

This document proposes a hybrid VLM (Vision-Language Model) integration strategy for GABI that addresses the limitations of the current PDF processing pipeline (`pdfplumber` + `pytesseract`). The solution balances cost, accuracy, and implementation complexity while handling TCU's ~470k legal documents.

### Key Recommendations

1. **Hybrid Approach**: Use VLM (Claude Vision) only for complex/scanned documents, keep `pdfplumber` for clean PDFs
2. **Phased Implementation**: 3 phases over 6 months
3. **Estimated Cost**: ~R$ 47k-141k for full corpus (one-time) + ~R$ 300-900/month (incremental)
4. **Storage**: New `page_images` and `vlm_extractions` tables; optional ColPali embeddings for image search

---

## 1. Current State Analysis

### Existing Pipeline (Problematic)

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌─────────────┐
│   PDF URL   │───▶│ pdfplumber   │───▶│ pytesseract │───▶│  Raw Text   │
└─────────────┘    └──────────────┘    └─────────────┘    └─────────────┘
                          │                   │
                          ▼                   ▼
                   ┌──────────────┐    ┌─────────────┐
                   │ Clean Layout │    │    OCR      │
                   │    Works     │    │  Fallback   │
                   └──────────────┘    └─────────────┘
```

### Pain Points

| Problem | Impact | Frequency |
|---------|--------|-----------|
| Complex layouts break extraction | Lost tables, signatures, stamps | ~30% of docs |
| Scanned documents need OCR | Slow, poor quality for legal text | ~15% of docs |
| No visual context understanding | Misses headers, footers, watermarks | ~40% of docs |
| Multi-column text merged incorrectly | Unreadable content | ~20% of docs |
| Handwritten annotations ignored | Lost context | ~10% of docs |

### Current Code (src/gabi/pipeline/parser.py)

```python
class PDFParser(BaseParser):
    async def parse(self, content: FetchedContent, config: dict) -> ParseResult:
        with pdfplumber.open(io.BytesIO(raw_content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                # ❌ Fails on: tables, stamps, signatures, complex layouts
        # ❌ OCR fallback is slow and low quality
```

---

## 2. VLM Pipeline Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        VLM-ENHANCED PIPELINE                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐     ┌──────────────────┐     ┌─────────────────────────────┐
│  PDF Fetch  │────▶│  Layout Analyzer │────▶│  Routing Decision           │
│             │     │  (Heuristic)     │     │                             │
└─────────────┘     └──────────────────┘     └─────────────┬───────────────┘
                                                           │
                              ┌────────────────────────────┼────────────────────────────┐
                              │                            │                            │
                              ▼                            ▼                            ▼
                    ┌─────────────────┐         ┌──────────────────┐        ┌──────────────────┐
                    │  Simple/Clean   │         │  Complex Layout  │        │  Scanned/Image   │
                    │  pdfplumber     │         │  Claude Vision   │        │  Claude Vision   │
                    │                 │         │  Structured      │        │  + OCR Hybrid    │
                    └────────┬────────┘         └────────┬─────────┘        └────────┬─────────┘
                             │                           │                           │
                             └───────────────────────────┼───────────────────────────┘
                                                         ▼
                                            ┌────────────────────────┐
                                            │  Unified Text Output   │
                                            │  (Markdown/Structured) │
                                            └───────────┬────────────┘
                                                        │
                              ┌─────────────────────────┼─────────────────────────┐
                              │                         │                         │
                              ▼                         ▼                         ▼
                    ┌─────────────────┐      ┌──────────────────┐      ┌──────────────────┐
                    │  Chunking       │      │  ColPali Opt-in  │      │  Image Storage   │
                    │  (Semantic)     │      │  (Page Embeds)   │      │  (S3/Object)     │
                    └────────┬────────┘      └────────┬─────────┘      └────────┬─────────┘
                             │                        │                         │
                             └────────────────────────┼─────────────────────────┘
                                                      ▼
                                         ┌────────────────────────┐
                                         │  Standard Pipeline     │
                                         │  (Embed → Index)       │
                                         └────────────────────────┘
```

### 2.2 Components

#### A. Layout Analyzer (Heuristic Router)

```python
# src/gabi/pipeline/layout_analyzer.py

class LayoutAnalyzer:
    """Analyzes PDF to determine best extraction strategy."""
    
    def analyze(self, pdf_bytes: bytes) -> LayoutAnalysis:
        """
        Returns extraction strategy based on document characteristics:
        - SIMPLE: Clean text-based PDF → pdfplumber
        - COMPLEX: Multi-column, tables, forms → Claude Vision
        - SCANNED: Image-based → Claude Vision (full OCR)
        """
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Heuristics
        has_text = self._check_text_layer(doc)
        image_ratio = self._calculate_image_ratio(doc)
        complexity_score = self._analyze_layout_complexity(doc)
        
        if not has_text and image_ratio > 0.8:
            return LayoutAnalysis(strategy=ExtractionStrategy.SCANNED, confidence=0.95)
        elif complexity_score > 0.7:
            return LayoutAnalysis(strategy=ExtractionStrategy.COMPLEX, confidence=0.85)
        else:
            return LayoutAnalysis(strategy=ExtractionStrategy.SIMPLE, confidence=0.90)
```

#### B. VLM Extractor (Claude Vision)

```python
# src/gabi/pipeline/vlm_extractor.py

class ClaudeVisionExtractor:
    """Extracts structured text from PDF pages using Claude Vision."""
    
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.cache = LRUCache(maxsize=1000)  # Cache extractions
    
    async def extract_page(
        self, 
        page_image: bytes,
        page_number: int,
        extraction_mode: ExtractionMode = ExtractionMode.FULL
    ) -> VLMExtractionResult:
        """
        Extract structured content from a page image.
        
        Supports multiple extraction modes:
        - FULL: Complete document extraction
        - TABLE_ONLY: Extract only tables
        - TEXT_ONLY: Extract only body text
        - METADATA: Extract headers, footers, page numbers
        """
        
        prompts = {
            ExtractionMode.FULL: """You are a legal document extraction expert. 
Extract ALL text from this legal document page, preserving structure.

Output format (JSON):
{
    "page_number": int,
    "content_type": "text|table|mixed|image",
    "title": "document title if visible",
    "sections": [
        {
            "type": "header|footer|body|table|stamp|signature",
            "text": "extracted text with formatting",
            "bounding_box": {"x": 0, "y": 0, "w": 100, "h": 100}
        }
    ],
    "tables": [
        {
            "caption": "table caption if any",
            "headers": ["col1", "col2"],
            "rows": [["val1", "val2"]]
        }
    ],
    "metadata": {
        "page_number": "as shown on page",
        "document_id": "if visible",
        "date": "if visible"
    }
}""",
            ExtractionMode.TABLE_ONLY: "Extract only tables from this page...",
            # ... other modes
        }
        
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.0,  # Deterministic for reproducibility
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}},
                    {"type": "text", "text": prompts[extraction_mode]}
                ]
            }]
        )
        
        return self._parse_response(response.content[0].text)
```

#### C. Storage Schema

```sql
-- Migration: Add VLM support tables

-- Table to store page images for VLM processing
CREATE TABLE page_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    image_data BYTEA, -- NULL if stored in S3
    s3_key VARCHAR(512), -- Reference to S3/MinIO
    image_format VARCHAR(10) DEFAULT 'png',
    image_width INTEGER,
    image_height INTEGER,
    dpi INTEGER DEFAULT 150,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_id, page_number)
);

-- Table for VLM extractions
CREATE TABLE vlm_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER,
    extraction_model VARCHAR(100),
    extraction_mode VARCHAR(50),
    raw_response JSONB,
    extracted_text TEXT,
    structured_content JSONB, -- Parsed sections, tables, etc.
    confidence_score FLOAT,
    processing_time_ms INTEGER,
    cost_usd DECIMAL(10,6),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Optional: ColPali image embeddings for visual search
CREATE TABLE page_image_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    embedding VECTOR(128), -- ColPali embeddings are smaller
    model VARCHAR(100) DEFAULT 'colpali-v1.2',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_id, page_number)
);

-- Index for finding documents by extraction method
CREATE INDEX idx_vlm_extractions_document ON vlm_extractions(document_id);
CREATE INDEX idx_page_images_document ON page_images(document_id);
```

---

## 3. VLM Selection Analysis

### 3.1 Option Comparison

| Approach | Pros | Cons | Cost (470k docs) | Best For |
|----------|------|------|------------------|----------|
| **Claude Vision** | Best accuracy, structured output, handles complex layouts | Higher cost, API dependency | ~R$ 141k | Complex docs, initial rollout |
| **ColPali** | Fast, embeds page images directly, search by image | Less precise text extraction | ~R$ 47k (self-hosted GPU) | Visual search, image-heavy docs |
| **GPT-4V** | Similar to Claude, widely tested | Slightly worse for Portuguese legal | ~R$ 155k | Alternative option |
| **Gemini Pro Vision** | Multilingual, good for PT | Less structured output | ~R$ 94k | Cost-sensitive |
| **Local VLM (Qwen-VL)** | No API costs, data privacy | Setup complexity, accuracy lower | Hardware cost only | High-volume, privacy concerns |
| **Hybrid (Recommended)** | Best of both worlds | More complex | ~R$ 47k-70k | Production use |

### 3.2 Detailed Cost Analysis

#### Claude Vision (Anthropic)

```python
# Cost calculation for Claude 3.5 Sonnet
# Pricing: $3/M input tokens, $15/M output tokens
# Average legal doc: 5 pages, ~4000 input tokens/page (image), ~2000 output tokens/page

COSTS = {
    "input_per_page": 4000,  # tokens
    "output_per_page": 2000,  # tokens
    "input_price_per_1m": 3.00,  # USD
    "output_price_per_1m": 15.00,  # USD
    "pages_per_doc": 5,
    "total_docs": 470_000,
}

def calculate_cost(docs: int, pages_per_doc: int = 5) -> dict:
    total_pages = docs * pages_per_doc
    
    input_cost = (total_pages * COSTS["input_per_page"] / 1_000_000) * COSTS["input_price_per_1m"]
    output_cost = (total_pages * COSTS["output_per_page"] / 1_000_000) * COSTS["output_price_per_1m"]
    total = input_cost + output_cost
    
    return {
        "total_usd": total,
        "total_brl": total * 5.0,  # Approximate exchange rate
        "per_doc_usd": total / docs,
    }

# Full corpus (470k docs): ~$35k USD (~R$ 175k)
# Hybrid (30% VLM): ~$10.5k USD (~R$ 52k)
# Monthly incremental (1k docs): ~$75 USD (~R$ 375)
```

#### ColPali (Self-Hosted)

```python
# ColPali: Embed page images directly, search by image
# Requires: GPU server (A10G or similar)

COSTS_COLPALI = {
    "gpu_instance": "aws_g5_2xlarge",  # A10G, 24GB VRAM
    "hourly_cost": 1.20,  # USD
    "pages_per_hour": 2000,  # Estimated throughput
    "total_pages": 470_000 * 5,
}

def calculate_colpali_cost() -> dict:
    hours_needed = COSTS_COLPALI["total_pages"] / COSTS_COLPALI["pages_per_hour"]
    processing_cost = hours_needed * COSTS_COLPALI["hourly_cost"]
    
    return {
        "processing_usd": processing_cost,
        "processing_brl": processing_cost * 5.0,
        "storage_gb": COSTS_COLPALI["total_pages"] * 128 * 4 / 1024**3,  # 128-dim embeddings
    }

# Full corpus: ~$1.4k USD processing + ongoing storage
# Plus GPU server for inference: ~$900/month
```

### 3.3 Recommendation: Hybrid Approach

```python
# Decision tree for extraction method

EXTRACTION_STRATEGY = """
IF document.has_text_layer() AND layout.complexity < 0.5:
    → Use pdfplumber (fast, cheap)
    → Cost: ~$0
    
ELIF document.has_tables() OR layout.is_multicolumn():
    → Use Claude Vision (structured extraction)
    → Cost: ~$0.07/page
    
ELIF document.is_image_based():
    → Use Claude Vision with OCR mode
    → Cost: ~$0.10/page
    
ELSE:
    → Use pdfplumber with VLM fallback on error
    → Cost: ~$0 (with ~5% fallback)
"""

# Expected distribution for TCU corpus:
# - 60% simple: pdfplumber (free)
# - 25% complex: Claude Vision (~$0.07/page)
# - 15% scanned: Claude Vision (~$0.10/page)
# 
# Weighted average: ~$0.025/page = ~$58k for full corpus
```

---

## 4. Implementation Plan

### 4.1 Phase 1: Foundation (Weeks 1-4)

**Goal:** Infrastructure and basic VLM integration

```yaml
Phase1:
  week_1:
    - Create page_images table
    - Create vlm_extractions table
    - Implement PDF to image conversion service
    - Setup S3/MinIO for image storage
    
  week_2:
    - Implement LayoutAnalyzer
    - Create VLM client abstraction
    - Implement ClaudeVisionExtractor
    - Add retry/circuit breaker for VLM API
    
  week_3:
    - Create hybrid PDF parser (pdfplumber + VLM)
    - Add extraction mode routing
    - Implement caching for VLM responses
    - Write tests for new components
    
  week_4:
    - Integration with existing pipeline
    - Add metrics and monitoring
    - Document API and configuration
    - Deploy to staging
```

**Deliverables:**
- [ ] `src/gabi/pipeline/vlm/` module
- [ ] Layout analyzer with 90%+ accuracy
- [ ] Claude Vision integration
- [ ] Updated pipeline orchestrator

### 4.2 Phase 2: Optimization (Weeks 5-8)

**Goal:** Cost optimization and batch processing

```yaml
Phase2:
  week_5_6:
    - Implement batch processing for VLM calls
    - Add intelligent caching (same doc patterns)
    - Optimize image preprocessing (resize, compression)
    - Add cost tracking per document
    
  week_7_8:
    - Implement ColPali for visual search (optional)
    - Add image embedding generation
    - Create visual search endpoint
    - Performance tuning
```

**Deliverables:**
- [ ] Batch processing (10-20 pages per API call)
- [ ] Cost tracking dashboard
- [ ] 50% cost reduction through caching
- [ ] Optional ColPali integration

### 4.3 Phase 3: Production (Weeks 9-12)

**Goal:** Full production rollout

```yaml
Phase3:
  week_9_10:
    - Backfill processing for existing documents
    - Migration strategy for legacy data
    - Load testing at full scale
    - Fine-tune routing thresholds
    
  week_11_12:
    - Production deployment
    - Monitoring and alerting
    - Documentation and training
    - Post-launch optimization
```

**Deliverables:**
- [ ] 470k documents processed
- [ ] <1% error rate
- [ ] Full observability
- [ ] Operations runbook

### 4.4 Timeline Summary

```
Month 1: Foundation
├── Week 1-2: Database + Image storage
├── Week 3-4: VLM integration + Testing
└── Milestone: Staging deployment

Month 2: Optimization  
├── Week 5-6: Batching + Caching
├── Week 7-8: ColPali + Visual search
└── Milestone: Cost targets met

Month 3: Production
├── Week 9-10: Backfill + Load testing
├── Week 11-12: Production + Monitoring
└── Milestone: Full rollout complete
```

---

## 5. Integration with Existing Pipeline

### 5.1 Pipeline Changes

```python
# src/gabi/pipeline/orchestrator.py - Modified

class PipelineOrchestrator:
    async def _process_single_url(
        self,
        url: str,
        source_id: str,
        fetch_config: Dict[str, Any],
        parse_config: Dict[str, Any],
        # ... other params
    ) -> None:
        try:
            # Phase 1: Fetch (unchanged)
            fetched = await self.fetcher.fetch(url=url, ...)
            
            # Phase 2: Parse (MODIFIED - VLM-enhanced)
            parser_config = dict(parse_config)
            parser_config["source_id"] = source_id
            
            # NEW: Enable VLM for PDFs if configured
            if fetched.detected_format == FormatType.PDF:
                parser_config["use_vlm"] = source_config.get("use_vlm", False)
                parser_config["vlm_config"] = source_config.get("vlm", {})
            
            parsed = await self.parser.parse(fetched, parser_config)
            
            # Phase 3: Chunking (unchanged, but receives better text)
            chunks = self.chunker.chunk(document.content, ...)
            
            # Phase 4: Embedding (unchanged)
            embedded = await self.embedder.embed_chunks(chunks, ...)
            
            # Phase 5: Indexing (unchanged)
            await self.indexer.index(embedded, ...)
            
        except Exception as e:
            await self._handle_error(...)
```

### 5.2 Configuration Schema

```yaml
# sources.yaml - VLM configuration example

sources:
  tcu_acordaos_complex:
    name: "TCU Acórdãos (Complex Layout)"
    type: pdf
    
    # NEW: VLM configuration
    vlm:
      enabled: true
      provider: "anthropic"  # anthropic | openai | google | local
      model: "claude-3-5-sonnet-20241022"
      
      # Routing configuration
      routing:
        default_strategy: "hybrid"  # hybrid | vlm_only | legacy_only
        
        # Heuristic thresholds
        thresholds:
          image_ratio: 0.7        # Use VLM if >70% images
          complexity_score: 0.6   # Use VLM if complexity > 0.6
          min_text_chars: 100     # Use VLM if <100 chars extracted
      
      # Processing options
      processing:
        dpi: 150                 # Image resolution
        max_pages_per_batch: 5   # Batch size for API calls
        extract_tables: true     # Extract tables as structured data
        extract_stamps: false    # Skip stamps/signatures
        
      # Cost controls
      cost_control:
        max_cost_per_doc_usd: 1.0
        enable_caching: true
        cache_ttl_hours: 168     # 7 days
      
      # Optional: ColPali for visual search
      colpali:
        enabled: false
        embedding_dimensions: 128
        
    fetch:
      url_pattern: "https://portal.tcu.gov.br/..."
      
    parse:
      input_format: "pdf"
      # VLM settings will override these when enabled
```

### 5.3 Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA FLOW DIAGRAM                             │
└─────────────────────────────────────────────────────────────────┘

Traditional Flow (unchanged):
┌────────┐   ┌────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
│  PDF   │──▶│  Text  │──▶│ Chunks  │──▶│ Embeds  │──▶│  Index  │
└────────┘   └────────┘   └─────────┘   └─────────┘   └─────────┘

VLM-Enhanced Flow:
┌────────┐   ┌────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐
│  PDF   │──▶│ Images │──▶│  Claude  │──▶│ Structured│──▶│ Chunks  │
└────────┘   └────────┘   │  Vision  │   │   Text    │   └─────────┘
                          └──────────┘   └───────────┘        │
                                │                             │
                                ▼                             ▼
                          ┌──────────┐                  ┌─────────┐
                          │  Cache   │                  │  Index  │
                          └──────────┘                  └─────────┘
                                │
                                ▼
                          ┌──────────┐
                          │  ColPali │  (Optional)
                          │ Embeddings
                          └──────────┘
```

---

## 6. Code Examples

### 6.1 VLM Extractor Implementation

```python
# src/gabi/pipeline/vlm/extractor.py

import base64
import io
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Optional

import anthropic
import fitz  # PyMuPDF
from PIL import Image

from gabi.config import settings
from gabi.pipeline.contracts import ParsedDocument, ParseResult


class ExtractionStrategy(Enum):
    SIMPLE = "simple"      # pdfplumber
    COMPLEX = "complex"    # VLM for layout
    SCANNED = "scanned"    # VLM for OCR


class ExtractionMode(Enum):
    FULL = "full"
    TABLE_ONLY = "table_only"
    TEXT_ONLY = "text_only"
    METADATA = "metadata"


@dataclass
class VLMExtractionResult:
    page_number: int
    content_type: str
    title: Optional[str]
    text: str
    structured_content: dict
    tables: list[dict]
    metadata: dict
    confidence: float
    cost_usd: float


class ClaudeVisionExtractor:
    """Extract structured text from PDF using Claude Vision."""
    
    # Structured prompt for legal documents
    LEGAL_EXTRACTION_PROMPT = """You are an expert legal document analyst. Extract ALL content from this document page with high precision.

Rules:
1. Preserve original formatting using Markdown
2. Extract tables as Markdown tables
3. Identify and label: headers, footers, stamps, signatures
4. For stamps/signatures, describe what you see (e.g., "Stamp: TCU Official Seal")
5. Maintain paragraph breaks and list formatting

Output format:
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

    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.vlm_model or "claude-3-5-sonnet-20241022"
        self.max_tokens = 4096
        
    async def extract_document(
        self,
        pdf_bytes: bytes,
        extraction_mode: ExtractionMode = ExtractionMode.FULL,
        max_pages: Optional[int] = None
    ) -> ParseResult:
        """Extract full document using VLM."""
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        documents = []
        errors = []
        total_cost = 0.0
        
        pages_to_process = min(len(doc), max_pages or len(doc))
        
        for page_num in range(pages_to_process):
            try:
                # Convert page to image
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better quality
                img_bytes = pix.tobytes("png")
                
                # Extract with VLM
                result = await self._extract_page(img_bytes, page_num + 1)
                total_cost += result.cost_usd
                
                # Create document
                doc_id = f"{doc_id_prefix}_page_{page_num + 1}"
                document = ParsedDocument(
                    document_id=doc_id,
                    source_id=source_id,
                    title=result.title or f"Page {page_num + 1}",
                    content=result.text,
                    content_preview=result.text[:500],
                    content_type="application/pdf",
                    metadata={
                        "page_number": page_num + 1,
                        "extraction_method": "vlm_claude",
                        "vlm_confidence": result.confidence,
                        "tables_extracted": len(result.tables),
                        "structured_content": result.structured_content,
                    },
                )
                documents.append(document)
                
            except Exception as e:
                errors.append({
                    "page": page_num + 1,
                    "error": str(e),
                    "error_type": type(e).__name__,
                })
        
        doc.close()
        
        return ParseResult(
            documents=documents,
            errors=errors,
            raw_content_size=len(pdf_bytes),
            parsed_content_size=sum(len(d.content) for d in documents),
            duration_seconds=0,  # Calculate actual duration
            metadata={"vlm_cost_usd": total_cost},
        )
    
    async def _extract_page(
        self, 
        image_bytes: bytes,
        page_number: int
    ) -> VLMExtractionResult:
        """Extract single page using Claude Vision."""
        
        # Encode image to base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # Call Claude API
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
                        "text": self.LEGAL_EXTRACTION_PROMPT
                    }
                ]
            }]
        )
        
        # Parse response
        content = response.content[0].text
        parsed = self._parse_json_response(content)
        
        # Calculate cost (approximate)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost_usd = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)
        
        return VLMExtractionResult(
            page_number=page_number,
            content_type=parsed.get("page_type", "unknown"),
            title=parsed.get("title"),
            text=parsed.get("content", ""),
            structured_content=parsed,
            tables=parsed.get("tables", []),
            metadata={"raw_response": content},
            confidence=0.95,  # Could be derived from response analysis
            cost_usd=cost_usd,
        )
    
    def _parse_json_response(self, text: str) -> dict:
        """Extract JSON from Claude's response."""
        import json
        import re
        
        # Try to find JSON block
        json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        
        # Try to parse entire response as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fallback: return as text content
            return {"content": text, "page_type": "unknown"}
```

### 6.2 Layout Analyzer

```python
# src/gabi/pipeline/vlm/layout_analyzer.py

import fitz
import numpy as np
from dataclasses import dataclass
from typing import Tuple


@dataclass
class LayoutAnalysis:
    strategy: ExtractionStrategy
    confidence: float
    metrics: dict
    reasoning: str


class LayoutAnalyzer:
    """Analyzes PDF layout to determine best extraction strategy."""
    
    def __init__(
        self,
        image_ratio_threshold: float = 0.7,
        complexity_threshold: float = 0.6,
        min_text_chars: int = 100
    ):
        self.image_ratio_threshold = image_ratio_threshold
        self.complexity_threshold = complexity_threshold
        self.min_text_chars = min_text_chars
    
    def analyze(self, pdf_bytes: bytes, sample_pages: int = 3) -> LayoutAnalysis:
        """Analyze PDF to determine extraction strategy."""
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Sample first few pages
        pages_to_check = min(len(doc), sample_pages)
        
        total_image_ratio = 0
        total_complexity = 0
        total_text = 0
        has_text_layer = False
        
        for i in range(pages_to_check):
            page = doc[i]
            
            # Check for text layer
            text = page.get_text()
            total_text += len(text)
            if text.strip():
                has_text_layer = True
            
            # Calculate image coverage
            image_ratio = self._calculate_image_ratio(page)
            total_image_ratio += image_ratio
            
            # Calculate layout complexity
            complexity = self._analyze_complexity(page)
            total_complexity += complexity
        
        doc.close()
        
        # Average metrics
        avg_image_ratio = total_image_ratio / pages_to_check
        avg_complexity = total_complexity / pages_to_check
        avg_text = total_text / pages_to_check
        
        # Decision logic
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
    
    def _calculate_image_ratio(self, page: fitz.Page) -> float:
        """Calculate ratio of page covered by images."""
        page_area = page.rect.width * page.rect.height
        image_area = sum(
            img["width"] * img["height"] 
            for img in page.get_images(full=True)
        )
        return min(image_area / page_area, 1.0) if page_area > 0 else 0
    
    def _analyze_complexity(self, page: fitz.Page) -> float:
        """Analyze layout complexity (0-1 scale)."""
        complexity = 0.0
        
        # Get text blocks
        blocks = page.get_text("blocks")
        
        # Multi-column detection
        x_positions = [b[0] for b in blocks]  # x0 coordinates
        if len(x_positions) > 1:
            x_std = np.std(x_positions)
            x_range = max(x_positions) - min(x_positions) if x_positions else 1
            if x_std / x_range > 0.1:  # Multiple columns
                complexity += 0.3
        
        # Many blocks indicate complex layout
        if len(blocks) > 20:
            complexity += 0.2
        
        # Table detection (simple heuristic)
        drawings = page.get_drawings()
        if len(drawings) > 10:  # Many lines = possible tables
            complexity += 0.3
        
        # Check for rotated text
        for block in blocks:
            if len(block) > 6 and block[6] != 0:  # rotation angle
                complexity += 0.2
                break
        
        return min(complexity, 1.0)
```

### 6.3 Hybrid PDF Parser

```python
# src/gabi/pipeline/vlm/hybrid_pdf_parser.py

from gabi.pipeline.parser import PDFParser, BaseParser
from gabi.pipeline.vlm.extractor import ClaudeVisionExtractor
from gabi.pipeline.vlm.layout_analyzer import LayoutAnalyzer


class HybridPDFParser(BaseParser):
    """PDF parser that intelligently routes between pdfplumber and VLM."""
    
    def __init__(
        self,
        layout_analyzer: Optional[LayoutAnalyzer] = None,
        vlm_extractor: Optional[ClaudeVisionExtractor] = None,
    ):
        self.layout_analyzer = layout_analyzer or LayoutAnalyzer()
        self.vlm_extractor = vlm_extractor or ClaudeVisionExtractor()
        self.legacy_parser = PDFParser()
    
    async def parse(
        self, 
        content: FetchedContent, 
        config: Dict[str, Any]
    ) -> ParseResult:
        """Parse PDF using best strategy."""
        
        # Check if VLM is enabled
        use_vlm = config.get("use_vlm", False)
        force_strategy = config.get("force_strategy")
        
        if not use_vlm:
            # Use legacy parser
            return await self.legacy_parser.parse(content, config)
        
        raw_content = content.get_content()
        
        # Determine strategy
        if force_strategy:
            strategy = ExtractionStrategy(force_strategy)
        else:
            analysis = self.layout_analyzer.analyze(raw_content)
            strategy = analysis.strategy
            
            # Log decision
            logger.info(
                f"PDF {content.url}: strategy={strategy.value}, "
                f"confidence={analysis.confidence:.2f}, "
                f"reason={analysis.reasoning}"
            )
        
        # Route to appropriate parser
        if strategy == ExtractionStrategy.SIMPLE:
            return await self.legacy_parser.parse(content, config)
        else:
            return await self.vlm_extractor.extract_document(
                pdf_bytes=raw_content,
                source_id=config.get("source_id", "unknown"),
                doc_id_prefix=self._generate_document_id(
                    config.get("source_id", "unknown"),
                    content.url
                ),
                max_pages=config.get("max_pages"),
            )
```

---

## 7. Storage Strategy

### 7.1 Image Storage Options

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **S3/MinIO** | Scalable, cheap, versioned | Network latency | Production |
| **PostgreSQL BYTEA** | Transactional, simple | DB bloat, slow | Small scale only |
| **File System** | Fast, simple | Diskless servers | Development only |
| **Hybrid (S3 + Cache)** | Best of both | More complex | Recommended |

### 7.2 Implementation

```python
# src/gabi/services/image_storage.py

class ImageStorageService:
    """Service for storing and retrieving page images."""
    
    def __init__(
        self,
        s3_client=None,
        bucket_name: str = "gabi-page-images",
        use_postgres_fallback: bool = True
    ):
        self.s3 = s3_client
        self.bucket = bucket_name
        self.use_postgres = use_postgres_fallback
    
    async def store_image(
        self,
        document_id: str,
        page_number: int,
        image_bytes: bytes,
        format: str = "png"
    ) -> str:
        """Store image and return reference key."""
        
        key = f"{document_id}/page_{page_number}.{format}"
        
        if self.s3:
            # Store in S3
            await self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=image_bytes,
                ContentType=f"image/{format}"
            )
            
            # Store reference in PostgreSQL
            await self._store_reference(document_id, page_number, key)
            return key
        
        elif self.use_postgres:
            # Store directly in PostgreSQL
            await self._store_in_postgres(document_id, page_number, image_bytes, format)
            return f"pg:{document_id}:{page_number}"
        
        else:
            raise RuntimeError("No storage backend available")
    
    async def get_image(self, reference: str) -> bytes:
        """Retrieve image by reference."""
        
        if reference.startswith("pg:"):
            # Retrieve from PostgreSQL
            _, doc_id, page = reference.split(":")
            return await self._get_from_postgres(doc_id, int(page))
        else:
            # Retrieve from S3
            response = await self.s3.get_object(
                Bucket=self.bucket,
                Key=reference
            )
            return await response["Body"].read()
```

---

## 8. Monitoring & Cost Tracking

### 8.1 Metrics

```python
# src/gabi/metrics/vlm_metrics.py

from prometheus_client import Counter, Histogram, Gauge

# VLM API calls
vlm_api_calls = Counter(
    "gabi_vlm_api_calls_total",
    "Total VLM API calls",
    ["provider", "model", "status"]
)

# VLM costs
vlm_cost_usd = Counter(
    "gabi_vlm_cost_usd_total",
    "Total VLM cost in USD",
    ["provider", "source_id"]
)

# Extraction latency
vlm_extraction_duration = Histogram(
    "gabi_vlm_extraction_duration_seconds",
    "VLM extraction latency",
    ["strategy"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)

# Cache hit rate
vlm_cache_hits = Counter(
    "gabi_vlm_cache_hits_total",
    "VLM cache hits",
    ["cache_type"]
)

# Layout analysis
layout_analysis_results = Counter(
    "gabi_layout_analysis_total",
    "Layout analysis results",
    ["strategy", "confidence_bucket"]
)
```

### 8.2 Cost Dashboard Query

```sql
-- Daily VLM cost report
SELECT 
    date_trunc('day', created_at) as day,
    extraction_model,
    COUNT(*) as pages_processed,
    SUM(cost_usd) as total_cost_usd,
    AVG(cost_usd) as avg_cost_per_page,
    SUM(processing_time_ms) / 1000 as total_processing_seconds
FROM vlm_extractions
WHERE created_at >= now() - interval '30 days'
GROUP BY 1, 2
ORDER BY 1 DESC;
```

---

## 9. Risk Assessment

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| API rate limits | Processing delays | Medium | Implement backoff, batching |
| API cost overruns | Budget exceeded | Medium | Cost limits, alerts, caching |
| Data privacy | Legal compliance | Low | No PII in prompts, audit logs |
| Model deprecation | Service disruption | Low | Abstract provider interface |
| Accuracy issues | Poor extraction | Low | Fallback to legacy, human review |
| S3 storage costs | High bills | Medium | Lifecycle policies, compression |

---

## 10. Success Criteria

### 10.1 Technical KPIs

| Metric | Current (pdfplumber) | Target (VLM Hybrid) |
|--------|---------------------|---------------------|
| Extraction accuracy (layout) | 60% | 95% |
| Table extraction success | 40% | 90% |
| Scanned document OCR | 50% | 95% |
| Processing cost per doc | $0 | $0.10 avg |
| Processing time per doc | 2s | 5s avg |
| Cache hit rate | N/A | 30% |

### 10.2 Business KPIs

- **Coverage**: 100% of complex/scanned documents processed with VLM
- **Cost**: Under R$ 70k for full corpus backfill
- **Time to production**: 12 weeks
- **User satisfaction**: Legal team reports improved search relevance

---

## 11. Appendix

### 11.1 Environment Variables

```bash
# VLM Configuration
GABI_VLM_ENABLED=true
GABI_VLM_PROVIDER=anthropic
GABI_VLM_MODEL=claude-3-5-sonnet-20241022
GABI_VLM_API_KEY=sk-ant-...

# Cost Controls
GABI_VLM_MAX_COST_PER_DOC_USD=1.0
GABI_VLM_CACHE_ENABLED=true
GABI_VLM_CACHE_TTL_HOURS=168

# Storage
GABI_VLM_S3_BUCKET=gabi-page-images
GABI_VLM_S3_ENDPOINT=https://s3.tcu.gov.br

# Processing
GABI_VLM_BATCH_SIZE=5
GABI_VLM_IMAGE_DPI=150
GABI_VLM_MAX_PAGES=1000
```

### 11.2 Migration Script

```python
# scripts/migrate_to_vlm.py

async def migrate_documents(
    source_id: str,
    dry_run: bool = True,
    batch_size: int = 100
):
    """Migrate existing documents to VLM extraction."""
    
    # Find documents needing reprocessing
    query = """
        SELECT d.id, d.url, d.content
        FROM documents d
        LEFT JOIN vlm_extractions v ON d.id = v.document_id
        WHERE d.source_id = :source_id
          AND v.id IS NULL
          AND d.content_type = 'application/pdf'
    """
    
    async with db_session() as session:
        result = await session.execute(query, {"source_id": source_id})
        documents = result.fetchall()
        
        logger.info(f"Found {len(documents)} documents to migrate")
        
        if dry_run:
            return
        
        # Process in batches
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            await asyncio.gather(*[
                reprocess_document(doc.id, doc.url)
                for doc in batch
            ])
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-11  
**Author:** Agent 5 (VLM Integration Strategy)  
**Reviewers:** [Pending]
