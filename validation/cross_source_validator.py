#!/usr/bin/env python3
"""
Cross-Source Validation Framework for DOU Data

Validates data across multiple sources (INLabs, leiturajornal, etc.)
to ensure completeness, accuracy, and detect discrepancies.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ============================================================================
# Data Models
# ============================================================================

class SourceType(str, Enum):
    """Available DOU data sources."""
    INLABS = "inlabs"           # INLabs API (official source)
    LEITURAJORNAL = "leiturajornal"  # Portal leitura jornal
    WEB_DOU = "web_dou"         # Direct web scraping
    PDF_EXTRACT = "pdf_extract" # PDF extraction


class DiscrepancyType(str, Enum):
    """Types of discrepancies between sources."""
    MISSING_IN_SOURCE = "missing_in_source"      # Document exists in A but not B
    COUNT_MISMATCH = "count_mismatch"            # Different document counts
    CONTENT_HASH_MISMATCH = "content_hash_mismatch"  # Same ID, different content
    METADATA_MISMATCH = "metadata_mismatch"      # Same ID, different metadata
    TEMPORAL_GAP = "temporal_gap"                # Different date coverage
    FIELD_MISSING = "field_missing"              # Required field missing in source


class ReconciliationStrategy(str, Enum):
    """Strategies for resolving source conflicts."""
    SOURCE_HIERARCHY = "source_hierarchy"        # Use priority ranking
    MOST_COMPLETE = "most_complete"              # Use source with most fields
    MOST_RECENT = "most_recent"                  # Use most recently updated
    CONSENSUS = "consensus"                      # Require agreement across sources
    MANUAL_REVIEW = "manual_review"              # Flag for human review


@dataclass(slots=True)
class DocumentFingerprint:
    """Unique fingerprint for cross-source document identification."""
    # Core identifying fields
    doc_type: str                           # e.g., "portaria", "decreto"
    doc_number: Optional[str] = None        # Document number
    doc_year: Optional[int] = None          # Document year
    
    # Publication context
    publication_date: Optional[str] = None  # ISO date format
    edition_number: Optional[str] = None    # Edition number
    section: Optional[str] = None           # Section (1, 2, 3, etc.)
    page_number: Optional[str] = None       # Page number in edition
    
    # Content signature
    title_normalized: str = ""              # Normalized title for matching
    content_hash: Optional[str] = None      # Hash of normalized content
    
    # Authority
    issuing_organ: Optional[str] = None     # Issuing organization
    issuing_authority: Optional[str] = None # Specific authority
    
    # Natural key hash for quick lookup
    natural_key_hash: str = field(default="")
    
    def __post_init__(self):
        if not self.natural_key_hash:
            self.natural_key_hash = self._compute_natural_key()
    
    def _compute_natural_key(self) -> str:
        """Compute stable natural key hash."""
        # Primary strategy: doc_type + number + year
        if self.doc_number and self.doc_year:
            key = f"{self.doc_type}|{self.doc_number}|{self.doc_year}"
            return hashlib.sha256(key.lower().encode()).hexdigest()[:32]
        
        # Secondary: title + date + organ
        key = f"{self.title_normalized}|{self.publication_date}|{self.issuing_organ}"
        return hashlib.sha256(key.lower().encode()).hexdigest()[:32]
    
    def to_matching_key(self) -> str:
        """Key for cross-source matching."""
        return f"{self.doc_type}:{self.doc_number}:{self.doc_year}:{self.publication_date}"


@dataclass(slots=True)
class SourceDocument:
    """Document from a specific source."""
    source: SourceType
    fingerprint: DocumentFingerprint
    
    # Raw data
    raw_data: dict[str, Any] = field(default_factory=dict)
    
    # Source-specific IDs
    source_url: Optional[str] = None
    external_id: Optional[str] = None
    
    # Extraction metadata
    extracted_at: Optional[datetime] = None
    extraction_version: str = ""
    
    # Quality flags
    fields_present: set[str] = field(default_factory=set)
    fields_missing: set[str] = field(default_factory=set)


@dataclass(slots=True)
class Discrepancy:
    """Detected discrepancy between sources."""
    type: DiscrepancyType
    natural_key_hash: str
    sources_involved: list[SourceType]
    
    # Details
    field_differences: dict[str, dict[str, Any]] = field(default_factory=dict)
    description: str = ""
    severity: str = "warning"  # info, warning, error, critical
    
    # Resolution
    suggested_source: Optional[SourceType] = None
    confidence: float = 0.0  # 0.0-1.0


@dataclass(slots=True)
class CrossMatchResult:
    """Result of matching documents across sources."""
    # Matching statistics
    total_by_source: dict[SourceType, int] = field(default_factory=dict)
    matched_documents: int = 0
    unmatched_by_source: dict[SourceType, int] = field(default_factory=dict)
    
    # Match groups
    perfect_matches: list[list[SourceDocument]] = field(default_factory=list)  # Same fingerprint
    probable_matches: list[list[SourceDocument]] = field(default_factory=list)  # Fuzzy match
    unique_to_source: dict[SourceType, list[SourceDocument]] = field(default_factory=dict)


@dataclass(slots=True)
class QualityMetrics:
    """Quality metrics for a source or cross-source comparison."""
    # Completeness
    total_documents: int = 0
    documents_with_type: int = 0
    documents_with_number: int = 0
    documents_with_year: int = 0
    documents_with_body: int = 0
    documents_with_authority: int = 0
    
    # Coverage
    date_range_start: Optional[date] = None
    date_range_end: Optional[date] = None
    total_dates_covered: int = 0
    
    # Timeliness
    avg_extraction_delay_hours: Optional[float] = None
    
    # Accuracy indicators
    duplicate_count: int = 0
    content_hash_conflicts: int = 0
    
    def completeness_score(self) -> float:
        """Calculate overall completeness score (0.0-1.0)."""
        if self.total_documents == 0:
            return 0.0
        
        required_fields = [
            self.documents_with_type,
            self.documents_with_number,
            self.documents_with_year,
            self.documents_with_body,
        ]
        weights = [0.3, 0.25, 0.15, 0.3]  # Total = 1.0
        
        return sum(
            (count / self.total_documents) * weight
            for count, weight in zip(required_fields, weights)
        )
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "total_documents": self.total_documents,
            "completeness_score": round(self.completeness_score(), 4),
            "field_coverage": {
                "type": self._pct(self.documents_with_type),
                "number": self._pct(self.documents_with_number),
                "year": self._pct(self.documents_with_year),
                "body": self._pct(self.documents_with_body),
                "authority": self._pct(self.documents_with_authority),
            },
            "date_range": {
                "start": self.date_range_start.isoformat() if self.date_range_start else None,
                "end": self.date_range_end.isoformat() if self.date_range_end else None,
                "total_dates": self.total_dates_covered,
            },
            "accuracy_indicators": {
                "duplicates": self.duplicate_count,
                "hash_conflicts": self.content_hash_conflicts,
            },
        }
    
    def _pct(self, count: int) -> str:
        if self.total_documents == 0:
            return "0%"
        return f"{count / self.total_documents * 100:.1f}%"


@dataclass(slots=True)
class ValidationReport:
    """Complete cross-source validation report."""
    validation_date: datetime = field(default_factory=datetime.utcnow)
    sources: list[SourceType] = field(default_factory=list)
    
    # Individual source metrics
    per_source_metrics: dict[SourceType, QualityMetrics] = field(default_factory=dict)
    
    # Cross-source results
    cross_match: CrossMatchResult = field(default_factory=CrossMatchResult)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    
    # Reconciliation
    reconciliation_strategy: ReconciliationStrategy = ReconciliationStrategy.SOURCE_HIERARCHY
    source_hierarchy: list[SourceType] = field(default_factory=list)
    
    # Summary
    overall_completeness: float = 0.0
    overall_accuracy: float = 0.0
    consensus_rate: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_date": self.validation_date.isoformat(),
            "sources": [s.value for s in self.sources],
            "per_source_metrics": {
                k.value: v.to_dict() 
                for k, v in self.per_source_metrics.items()
            },
            "cross_match": {
                "total_by_source": {k.value: v for k, v in self.cross_match.total_by_source.items()},
                "matched_documents": self.cross_match.matched_documents,
                "unmatched_by_source": {k.value: v for k, v in self.cross_match.unmatched_by_source.items()},
                "perfect_matches": len(self.cross_match.perfect_matches),
                "probable_matches": len(self.cross_match.probable_matches),
            },
            "discrepancies": [
                {
                    "type": d.type.value,
                    "sources": [s.value for s in d.sources_involved],
                    "severity": d.severity,
                    "description": d.description,
                }
                for d in self.discrepancies
            ],
            "summary": {
                "overall_completeness": round(self.overall_completeness, 4),
                "overall_accuracy": round(self.overall_accuracy, 4),
                "consensus_rate": round(self.consensus_rate, 4),
                "total_discrepancies": len(self.discrepancies),
                "critical_issues": sum(1 for d in self.discrepancies if d.severity == "critical"),
                "warnings": sum(1 for d in self.discrepancies if d.severity == "warning"),
            },
        }


# ============================================================================
# Fingerprinting Engine
# ============================================================================

class FingerprintEngine:
    """Creates document fingerprints for cross-source matching."""
    
    # Document type normalizations
    DOC_TYPE_MAP = {
        "portaria": ["portaria", "portarias"],
        "decreto": ["decreto", "decretos"],
        "lei": ["lei", "leis", "lei complementar", "emenda constitucional"],
        "resolucao": ["resolução", "resolucao", "resoluções"],
        "instrucao_normativa": ["instrução normativa", "instrucao normativa"],
        "ato": ["ato", "ato declaratório", "ato declaratório executivo"],
        "edital": ["edital", "editais"],
        "aviso": ["aviso", "avisos"],
        "despacho": ["despacho", "despachos"],
        "deliberacao": ["deliberação", "deliberacao"],
        "parecer": ["parecer", "pareceres"],
        "retificacao": ["retificação", "retificacao"],
        "errata": ["errata", "erratas"],
    }
    
    # Characters to normalize
    NORMALIZE_CHARS = str.maketrans(
        "áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇñÑ",
        "aaaaeeiooouucAAAAEEIOOOUUCnN"
    )
    
    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Normalize text for comparison."""
        if not text:
            return ""
        # Lowercase and remove accents
        text = text.lower().translate(cls.NORMALIZE_CHARS)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Remove common stop words for matching
        text = re.sub(r'\b(do|da|de|dos|das|no|na|nos|nas|e)\b', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()
    
    @classmethod
    def normalize_doc_type(cls, doc_type: str) -> str:
        """Normalize document type to canonical form."""
        if not doc_type:
            return "unknown"
        
        dt_lower = cls.normalize_text(doc_type)
        for canonical, variants in cls.DOC_TYPE_MAP.items():
            if any(v in dt_lower for v in variants):
                return canonical
        return dt_lower[:50]  # Fallback: truncated normalized
    
    @classmethod
    def extract_doc_number(cls, text: str) -> Optional[str]:
        """Extract document number from text."""
        if not text:
            return None
        
        # Common patterns: Nº 123, No 123, n. 123, 123/2024
        patterns = [
            r'[Nn][ºo\.]?\s*(\d+[./-]?\d*)',
            r'\b(\d{1,5}/\d{4})\b',
            r'\b(\d{1,5})\s*/\s*(\d{4})\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).replace('/', '-')
        return None
    
    @classmethod
    def extract_year(cls, text: str) -> Optional[int]:
        """Extract year from text."""
        if not text:
            return None
        
        # Look for 4-digit year between 1900-2099
        match = re.search(r'\b(19|20)\d{2}\b', text)
        if match:
            year = int(match.group(0))
            return year if 1900 <= year <= 2100 else None
        return None
    
    @classmethod
    def compute_content_hash(cls, body_text: str) -> str:
        """Compute normalized content hash."""
        if not body_text:
            return ""
        
        # Normalize content
        normalized = cls.normalize_text(body_text)
        # Remove signature blocks (source-specific)
        normalized = re.sub(r'assinado por:.*$', '', normalized, flags=re.IGNORECASE)
        # Remove page headers
        normalized = re.sub(r'diario oficial da uniao.*$', '', normalized, flags=re.IGNORECASE)
        
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]
    
    @classmethod
    def from_extraction_result(cls, source: SourceType, data: dict[str, Any]) -> DocumentFingerprint:
        """Create fingerprint from extraction result."""
        doc = data.get("document", {})
        pub = data.get("publication_issue", {})
        
        # Document type
        doc_type = cls.normalize_doc_type(doc.get("document_type", ""))
        
        # Document number and year
        doc_number = doc.get("document_number")
        doc_year = doc.get("document_year")
        
        # If not in structured fields, try to extract from title
        title = doc.get("title", "")
        if not doc_number:
            doc_number = cls.extract_doc_number(title)
        if not doc_year:
            doc_year = cls.extract_year(title)
        
        # Publication context
        pub_date = pub.get("publication_date", "")
        edition = pub.get("edition_number", "")
        section = pub.get("edition_section", "")
        page = pub.get("page_number", "")
        
        # Authority
        organ = doc.get("issuing_organ", "")
        authority = doc.get("issuing_authority", "")
        
        # Content hash
        body = doc.get("body_text", "")
        content_hash = cls.compute_content_hash(body)
        
        # Normalized title
        title_norm = cls.normalize_text(title)
        
        return DocumentFingerprint(
            doc_type=doc_type,
            doc_number=doc_number,
            doc_year=doc_year,
            publication_date=pub_date,
            edition_number=edition,
            section=section,
            page_number=page,
            title_normalized=title_norm,
            content_hash=content_hash,
            issuing_organ=organ,
            issuing_authority=authority,
        )


# ============================================================================
# Cross-Source Matcher
# ============================================================================

class CrossSourceMatcher:
    """Matches documents across multiple sources."""
    
    # Similarity threshold for fuzzy matching
    TITLE_SIMILARITY_THRESHOLD = 0.85
    CONTENT_SIMILARITY_THRESHOLD = 0.90
    
    def __init__(self, source_hierarchy: Optional[list[SourceType]] = None):
        self.source_hierarchy = source_hierarchy or [
            SourceType.INLABS,
            SourceType.LEITURAJORNAL,
            SourceType.WEB_DOU,
        ]
    
    def match_documents(
        self, 
        documents_by_source: dict[SourceType, list[SourceDocument]]
    ) -> CrossMatchResult:
        """Match documents across sources."""
        result = CrossMatchResult()
        
        # Count totals
        for source, docs in documents_by_source.items():
            result.total_by_source[source] = len(docs)
        
        # Index by natural key hash
        by_natural_key: dict[str, dict[SourceType, SourceDocument]] = defaultdict(dict)
        for source, docs in documents_by_source.items():
            for doc in docs:
                by_natural_key[doc.fingerprint.natural_key_hash][source] = doc
        
        # Find perfect matches (same natural key across multiple sources)
        for nk_hash, source_docs in by_natural_key.items():
            if len(source_docs) > 1:
                # Verify content hash similarity
                content_hashes = [
                    doc.fingerprint.content_hash 
                    for doc in source_docs.values()
                    if doc.fingerprint.content_hash
                ]
                
                if len(set(content_hashes)) == 1 or self._content_similar(source_docs):
                    result.perfect_matches.append(list(source_docs.values()))
                    result.matched_documents += 1
                else:
                    # Same natural key but different content - needs review
                    result.probable_matches.append(list(source_docs.values()))
            else:
                # Only in one source
                source = list(source_docs.keys())[0]
                doc = list(source_docs.values())[0]
                if source not in result.unique_to_source:
                    result.unique_to_source[source] = []
                result.unique_to_source[source].append(doc)
                result.unmatched_by_source[source] = result.unmatched_by_source.get(source, 0) + 1
        
        # Attempt fuzzy matching for unique documents
        self._fuzzy_match_uniques(result, documents_by_source)
        
        return result
    
    def _content_similar(self, source_docs: dict[SourceType, SourceDocument]) -> bool:
        """Check if documents have similar content despite different hashes."""
        contents = []
        for doc in source_docs.values():
            body = doc.raw_data.get("document", {}).get("body_text", "")
            if body:
                contents.append(body)
        
        if len(contents) < 2:
            return False
        
        # Compare all pairs
        for i in range(len(contents)):
            for j in range(i + 1, len(contents)):
                sim = SequenceMatcher(None, contents[i], contents[j]).ratio()
                if sim < self.CONTENT_SIMILARITY_THRESHOLD:
                    return False
        return True
    
    def _fuzzy_match_uniques(
        self, 
        result: CrossMatchResult, 
        documents_by_source: list[SourceDocument]
    ) -> None:
        """Attempt to fuzzy match documents that didn't match by natural key."""
        # Get all unique documents
        all_uniques = []
        for source, docs in result.unique_to_source.items():
            for doc in docs:
                all_uniques.append((source, doc))
        
        # Try to match by title similarity + date
        matched_indices = set()
        for i, (source_a, doc_a) in enumerate(all_uniques):
            if i in matched_indices:
                continue
            
            potential_matches = [doc_a]
            for j, (source_b, doc_b) in enumerate(all_uniques[i+1:], start=i+1):
                if j in matched_indices:
                    continue
                
                # Check same date and similar title
                if doc_a.fingerprint.publication_date != doc_b.fingerprint.publication_date:
                    continue
                
                title_a = doc_a.fingerprint.title_normalized
                title_b = doc_b.fingerprint.title_normalized
                
                if title_a and title_b:
                    sim = SequenceMatcher(None, title_a, title_b).ratio()
                    if sim >= self.TITLE_SIMILARITY_THRESHOLD:
                        potential_matches.append(doc_b)
                        matched_indices.add(j)
            
            if len(potential_matches) > 1:
                result.probable_matches.append(potential_matches)
                matched_indices.add(i)


# ============================================================================
# Discrepancy Detector
# ============================================================================

class DiscrepancyDetector:
    """Detects discrepancies between sources."""
    
    def detect(
        self,
        match_result: CrossMatchResult,
        documents_by_source: dict[SourceType, list[SourceDocument]]
    ) -> list[Discrepancy]:
        """Detect all discrepancies."""
        discrepancies = []
        
        # Check count mismatches
        discrepancies.extend(self._check_count_mismatches(documents_by_source))
        
        # Check temporal coverage
        discrepancies.extend(self._check_temporal_coverage(documents_by_source))
        
        # Check matched documents for content/metadata differences
        for match_group in match_result.perfect_matches + match_result.probable_matches:
            discrepancies.extend(self._check_field_consistency(match_group))
        
        # Check unique documents
        for source, docs in match_result.unique_to_source.items():
            for doc in docs:
                disc = Discrepancy(
                    type=DiscrepancyType.MISSING_IN_SOURCE,
                    natural_key_hash=doc.fingerprint.natural_key_hash,
                    sources_involved=[source],
                    description=f"Document unique to {source.value}: {doc.fingerprint.title_normalized[:80]}",
                    severity="warning",
                )
                discrepancies.append(disc)
        
        return discrepancies
    
    def _check_count_mismatches(
        self, 
        documents_by_source: dict[SourceType, list[SourceDocument]]
    ) -> list[Discrepancy]:
        """Check for significant count differences between sources."""
        discrepancies = []
        counts = {s: len(d) for s, d in documents_by_source.items()}
        
        if len(counts) < 2:
            return discrepancies
        
        max_count = max(counts.values())
        min_count = min(counts.values())
        
        if max_count > 0 and (max_count - min_count) / max_count > 0.1:  # 10% threshold
            sources_str = ", ".join(f"{s.value}: {c}" for s, c in counts.items())
            disc = Discrepancy(
                type=DiscrepancyType.COUNT_MISMATCH,
                natural_key_hash="",
                sources_involved=list(counts.keys()),
                description=f"Document count mismatch: {sources_str}",
                severity="error" if (max_count - min_count) / max_count > 0.2 else "warning",
            )
            discrepancies.append(disc)
        
        return discrepancies
    
    def _check_temporal_coverage(
        self, 
        documents_by_source: dict[SourceType, list[SourceDocument]]
    ) -> list[Discrepancy]:
        """Check for date range coverage gaps."""
        discrepancies = []
        
        dates_by_source: dict[SourceType, set[str]] = defaultdict(set)
        for source, docs in documents_by_source.items():
            for doc in docs:
                if doc.fingerprint.publication_date:
                    dates_by_source[source].add(doc.fingerprint.publication_date)
        
        # Find dates unique to sources
        all_dates = set()
        for dates in dates_by_source.values():
            all_dates.update(dates)
        
        for date in sorted(all_dates):
            sources_with = [s for s, dates in dates_by_source.items() if date in dates]
            sources_without = [s for s in documents_by_source.keys() if s not in sources_with]
            
            if sources_with and sources_without:
                disc = Discrepancy(
                    type=DiscrepancyType.TEMPORAL_GAP,
                    natural_key_hash="",
                    sources_involved=sources_with + sources_without,
                    description=f"Date {date}: present in {', '.join(s.value for s in sources_with)}, "
                               f"missing in {', '.join(s.value for s in sources_without)}",
                    severity="info" if len(sources_without) == 1 else "warning",
                )
                discrepancies.append(disc)
        
        return discrepancies
    
    def _check_field_consistency(self, match_group: list[SourceDocument]) -> list[Discrepancy]:
        """Check for field value consistency across matched documents."""
        discrepancies = []
        
        # Fields to compare
        comparable_fields = [
            "document_type", "document_number", "document_year",
            "title", "issuing_organ", "issuing_authority"
        ]
        
        for field in comparable_fields:
            values: dict[str, list[SourceType]] = defaultdict(list)
            for doc in match_group:
                raw_doc = doc.raw_data.get("document", {})
                value = str(raw_doc.get(field, "")).lower().strip()
                if value:
                    values[value].append(doc.source)
            
            if len(values) > 1:
                # Different values for same field
                desc = f"Field '{field}' differs: " + ", ".join(
                    f"'{v}' in {', '.join(s.value for s in sources)}"
                    for v, sources in values.items()
                )
                disc = Discrepancy(
                    type=DiscrepancyType.METADATA_MISMATCH,
                    natural_key_hash=match_group[0].fingerprint.natural_key_hash,
                    sources_involved=[doc.source for doc in match_group],
                    field_differences={field: dict(values)},
                    description=desc,
                    severity="warning",
                )
                discrepancies.append(disc)
        
        # Check content hash
        content_hashes = set(
            doc.fingerprint.content_hash 
            for doc in match_group 
            if doc.fingerprint.content_hash
        )
        if len(content_hashes) > 1:
            disc = Discrepancy(
                type=DiscrepancyType.CONTENT_HASH_MISMATCH,
                natural_key_hash=match_group[0].fingerprint.natural_key_hash,
                sources_involved=[doc.source for doc in match_group],
                description=f"Content hash mismatch across sources for same document",
                severity="error",
            )
            discrepancies.append(disc)
        
        return discrepancies


# ============================================================================
# Reconciliation Engine
# ============================================================================

class ReconciliationEngine:
    """Reconciles discrepancies and determines authoritative values."""
    
    def __init__(
        self, 
        strategy: ReconciliationStrategy = ReconciliationStrategy.SOURCE_HIERARCHY,
        source_hierarchy: Optional[list[SourceType]] = None
    ):
        self.strategy = strategy
        self.source_hierarchy = source_hierarchy or [
            SourceType.INLABS,
            SourceType.LEITURAJORNAL,
            SourceType.WEB_DOU,
        ]
    
    def reconcile(
        self, 
        match_group: list[SourceDocument]
    ) -> tuple[SourceDocument, dict[str, Any]]:
        """
        Reconcile a group of matched documents.
        Returns (authoritative_document, reconciliation_metadata).
        """
        if self.strategy == ReconciliationStrategy.SOURCE_HIERARCHY:
            return self._reconcile_by_hierarchy(match_group)
        elif self.strategy == ReconciliationStrategy.MOST_COMPLETE:
            return self._reconcile_by_completeness(match_group)
        elif self.strategy == ReconciliationStrategy.MOST_RECENT:
            return self._reconcile_by_recency(match_group)
        elif self.strategy == ReconciliationStrategy.CONSENSUS:
            return self._reconcile_by_consensus(match_group)
        else:
            # Manual review - flag all
            return match_group[0], {
                "reconciliation_strategy": "manual_review",
                "all_sources": [d.source.value for d in match_group],
                "needs_review": True,
            }
    
    def _reconcile_by_hierarchy(
        self, 
        match_group: list[SourceDocument]
    ) -> tuple[SourceDocument, dict[str, Any]]:
        """Reconcile using source hierarchy."""
        for preferred_source in self.source_hierarchy:
            for doc in match_group:
                if doc.source == preferred_source:
                    return doc, {
                        "reconciliation_strategy": "source_hierarchy",
                        "selected_source": preferred_source.value,
                        "hierarchy_position": self.source_hierarchy.index(preferred_source),
                        "all_sources": [d.source.value for d in match_group],
                    }
        
        # Fallback to first
        return match_group[0], {
            "reconciliation_strategy": "fallback_first",
            "selected_source": match_group[0].source.value,
        }
    
    def _reconcile_by_completeness(
        self, 
        match_group: list[SourceDocument]
    ) -> tuple[SourceDocument, dict[str, Any]]:
        """Reconcile by choosing most complete document."""
        best_doc = max(match_group, key=lambda d: len(d.fields_present))
        
        return best_doc, {
            "reconciliation_strategy": "most_complete",
            "fields_present": len(best_doc.fields_present),
            "all_sources": [(d.source.value, len(d.fields_present)) for d in match_group],
        }
    
    def _reconcile_by_recency(
        self, 
        match_group: list[SourceDocument]
    ) -> tuple[SourceDocument, dict[str, Any]]:
        """Reconcile by choosing most recently extracted."""
        best_doc = max(
            match_group, 
            key=lambda d: d.extracted_at or datetime.min
        )
        
        return best_doc, {
            "reconciliation_strategy": "most_recent",
            "extraction_time": best_doc.extracted_at.isoformat() if best_doc.extracted_at else None,
        }
    
    def _reconcile_by_consensus(
        self, 
        match_group: list[SourceDocument]
    ) -> tuple[SourceDocument, dict[str, Any]]:
        """Reconcile by finding consensus across sources."""
        # Build consensus for each field
        consensus_doc = match_group[0]
        field_votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        for doc in match_group:
            raw = doc.raw_data.get("document", {})
            for field, value in raw.items():
                if value:
                    field_votes[field][str(value)] += 1
        
        # Check if we have consensus (>50% agreement)
        consensus_fields = {}
        for field, votes in field_votes.items():
            max_votes = max(votes.values())
            total_votes = sum(votes.values())
            if max_votes / total_votes > 0.5:
                consensus_value = max(votes.keys(), key=lambda k: votes[k])
                consensus_fields[field] = consensus_value
        
        return consensus_doc, {
            "reconciliation_strategy": "consensus",
            "consensus_fields": list(consensus_fields.keys()),
            "disputed_fields": [
                f for f in field_votes 
                if max(field_votes[f].values()) / sum(field_votes[f].values()) <= 0.5
            ],
        }


# ============================================================================
# Quality Metrics Calculator
# ============================================================================

class QualityMetricsCalculator:
    """Calculates quality metrics for sources."""
    
    def calculate(
        self, 
        documents: list[SourceDocument]
    ) -> QualityMetrics:
        """Calculate quality metrics for a set of documents."""
        metrics = QualityMetrics()
        metrics.total_documents = len(documents)
        
        # Field presence counts
        for doc in documents:
            raw = doc.raw_data.get("document", {})
            if raw.get("document_type"):
                metrics.documents_with_type += 1
            if raw.get("document_number"):
                metrics.documents_with_number += 1
            if raw.get("document_year"):
                metrics.documents_with_year += 1
            if raw.get("body_text"):
                metrics.documents_with_body += 1
            if raw.get("issuing_organ") or raw.get("issuing_authority"):
                metrics.documents_with_authority += 1
        
        # Date range
        dates = set()
        for doc in documents:
            if doc.fingerprint.publication_date:
                dates.add(doc.fingerprint.publication_date)
                try:
                    d = datetime.strptime(doc.fingerprint.publication_date, "%Y-%m-%d").date()
                    if metrics.date_range_start is None or d < metrics.date_range_start:
                        metrics.date_range_start = d
                    if metrics.date_range_end is None or d > metrics.date_range_end:
                        metrics.date_range_end = d
                except ValueError:
                    pass
        
        metrics.total_dates_covered = len(dates)
        
        # Check for duplicates
        seen_hashes: set[str] = set()
        for doc in documents:
            h = doc.fingerprint.natural_key_hash
            if h in seen_hashes:
                metrics.duplicate_count += 1
            seen_hashes.add(h)
        
        return metrics
    
    def calculate_cross_source(
        self,
        match_result: CrossMatchResult,
        documents_by_source: dict[SourceType, list[SourceDocument]]
    ) -> dict[str, Any]:
        """Calculate cross-source quality metrics."""
        total_docs = sum(len(d) for d in documents_by_source.values())
        
        # Consensus rate
        matched_count = len(match_result.perfect_matches)
        consensus_rate = matched_count / total_docs if total_docs > 0 else 0
        
        # Coverage by source
        source_coverage = {
            source.value: len(docs) / total_docs if total_docs > 0 else 0
            for source, docs in documents_by_source.items()
        }
        
        return {
            "consensus_rate": round(consensus_rate, 4),
            "perfect_matches": len(match_result.perfect_matches),
            "probable_matches": len(match_result.probable_matches),
            "unique_documents": sum(len(d) for d in match_result.unique_to_source.values()),
            "source_coverage": {k: f"{v:.1%}" for k, v in source_coverage.items()},
        }


# ============================================================================
# Main Validation Runner
# ============================================================================

class CrossSourceValidator:
    """Main entry point for cross-source validation."""
    
    def __init__(
        self,
        reconciliation_strategy: ReconciliationStrategy = ReconciliationStrategy.SOURCE_HIERARCHY,
        source_hierarchy: Optional[list[SourceType]] = None
    ):
        self.fingerprinter = FingerprintEngine()
        self.matcher = CrossSourceMatcher(source_hierarchy)
        self.detector = DiscrepancyDetector()
        self.reconciler = ReconciliationEngine(reconciliation_strategy, source_hierarchy)
        self.metrics_calc = QualityMetricsCalculator()
    
    def validate(
        self,
        documents_by_source: dict[SourceType, list[SourceDocument]]
    ) -> ValidationReport:
        """Run full cross-source validation."""
        report = ValidationReport()
        report.sources = list(documents_by_source.keys())
        
        # Calculate per-source metrics
        for source, docs in documents_by_source.items():
            report.per_source_metrics[source] = self.metrics_calc.calculate(docs)
        
        # Match documents across sources
        report.cross_match = self.matcher.match_documents(documents_by_source)
        
        # Detect discrepancies
        report.discrepancies = self.detector.detect(report.cross_match, documents_by_source)
        
        # Calculate cross-source metrics
        cross_metrics = self.metrics_calc.calculate_cross_source(
            report.cross_match, documents_by_source
        )
        
        # Calculate overall scores
        completeness_scores = [
            m.completeness_score() for m in report.per_source_metrics.values()
        ]
        report.overall_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0
        report.overall_accuracy = cross_metrics.get("consensus_rate", 0)
        report.consensus_rate = cross_metrics.get("consensus_rate", 0)
        
        return report


# ============================================================================
# Loaders from existing data formats
# ============================================================================

def load_from_extraction_results(
    source: SourceType,
    parsed_dir: Path,
    extraction_version: str = "1.0"
) -> list[SourceDocument]:
    """Load SourceDocuments from extraction result JSON files."""
    documents = []
    
    for json_file in sorted(parsed_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            docs = data.get("documents", [])
            
            for doc_data in docs:
                fingerprint = FingerprintEngine.from_extraction_result(source, doc_data)
                
                # Determine present/missing fields
                raw_doc = doc_data.get("document", {})
                fields_present = set()
                fields_missing = set()
                required = ["document_type", "title", "body_text"]
                optional = ["document_number", "document_year", "issuing_organ", "issuing_authority"]
                
                for field in required + optional:
                    if raw_doc.get(field):
                        fields_present.add(field)
                    elif field in required:
                        fields_missing.add(field)
                
                doc = SourceDocument(
                    source=source,
                    fingerprint=fingerprint,
                    raw_data=doc_data,
                    source_url=data.get("page_url"),
                    extracted_at=datetime.fromtimestamp(json_file.stat().st_mtime),
                    extraction_version=extraction_version,
                    fields_present=fields_present,
                    fields_missing=fields_missing,
                )
                documents.append(doc)
        except Exception as e:
            print(f"Warning: Failed to load {json_file}: {e}")
    
    return documents


# ============================================================================
# CLI and utilities
# ============================================================================

def write_validation_report(report: ValidationReport, out_dir: Path) -> None:
    """Write validation report to disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Main report
    (out_dir / "cross_source_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    # Discrepancies detail
    discrepancies_json = [
        {
            "type": d.type.value,
            "natural_key_hash": d.natural_key_hash,
            "sources": [s.value for s in d.sources_involved],
            "severity": d.severity,
            "description": d.description,
            "field_differences": d.field_differences,
        }
        for d in report.discrepancies
    ]
    (out_dir / "discrepancies.json").write_text(
        json.dumps(discrepancies_json, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    # Per-source metrics
    for source, metrics in report.per_source_metrics.items():
        (out_dir / f"metrics_{source.value}.json").write_text(
            json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    # Markdown summary
    lines = [
        "# Cross-Source Validation Report",
        "",
        f"**Validation Date:** {report.validation_date.isoformat()}",
        f"**Sources Analyzed:** {', '.join(s.value for s in report.sources)}",
        "",
        "## Executive Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Overall Completeness | {report.overall_completeness:.1%} |",
        f"| Consensus Rate | {report.consensus_rate:.1%} |",
        f"| Total Discrepancies | {len(report.discrepancies)} |",
        f"| Critical Issues | {sum(1 for d in report.discrepancies if d.severity == 'critical')} |",
        "",
        "## Per-Source Metrics",
        "",
        "| Source | Documents | Completeness |",
        "|---|---|---|",
    ]
    
    for source, metrics in report.per_source_metrics.items():
        lines.append(
            f"| {source.value} | {metrics.total_documents} | {metrics.completeness_score():.1%} |"
        )
    
    lines.extend([
        "",
        "## Cross-Source Matching",
        "",
        f"- **Perfect Matches:** {len(report.cross_match.perfect_matches)}",
        f"- **Probable Matches:** {len(report.cross_match.probable_matches)}",
        f"- **Unique per Source:**",
    ])
    
    for source, docs in report.cross_match.unique_to_source.items():
        lines.append(f"  - {source.value}: {len(docs)}")
    
    lines.extend([
        "",
        "## Discrepancies",
        "",
    ])
    
    # Group by severity
    by_severity: dict[str, list[Discrepancy]] = defaultdict(list)
    for d in report.discrepancies:
        by_severity[d.severity].append(d)
    
    for severity in ["critical", "error", "warning", "info"]:
        if severity in by_severity:
            lines.extend([f"### {severity.upper()}", ""])
            for d in by_severity[severity]:
                lines.append(f"- **{d.type.value}:** {d.description}")
            lines.append("")
    
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    # Example usage
    print("Cross-Source Validation Framework for DOU Data")
    print("=" * 50)
    print("\nAvailable sources:", [s.value for s in SourceType])
    print("\nUse this module by importing CrossSourceValidator:")
    print("  from validation.cross_source_validator import CrossSourceValidator")
    print("  validator = CrossSourceValidator()")
    print("  report = validator.validate(documents_by_source)")
