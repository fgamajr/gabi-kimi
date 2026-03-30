"""Deterministic DOU chunker for the reindex-v3 sidecar index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import re
from typing import Any


CHUNKER_VERSION = "dou_chunker_v1"
PRUNING_AUDIT_VERSION = "chunk_prune_v1"
MAX_CHUNKS_PER_DOC = 8
HARD_LIMIT = 12
MIN_ELIGIBLE_TEXT_LEN = 1500
TARGET_CHUNK_CHARS = 2200
OVERLAP_CHARS = 200
_SPACE_RE = re.compile(r"\s+")
_ARTICLE_BOUNDARY_RE = re.compile(
    r"(?im)(?=^(?:art\.?\s*\d+[º°]?(?:-[a-z])?|anexo\b|refer[eê]ncias?\b|assina(?:do|tura)\b))"
)
_LEGAL_REF_RE = re.compile(
    r"\b(?:lei(?:\s+complementar)?|decreto(?:-lei)?|portaria|resolu[cç][aã]o|"
    r"instru[cç][aã]o\s+normativa|medida\s+provis[oó]ria|s[uú]mula|ac[oó]rd[aã]o)"
    r"\s*(?:n[°º.]?\s*)?\d",
    re.IGNORECASE,
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return _SPACE_RE.sub(" ", str(value)).strip()


def _sha256_hex(parts: list[str]) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(slots=True)
class ChunkCandidate:
    chunk_seq: int
    chunk_type: str
    text: str
    char_start: int
    char_end: int
    priority: float
    chunk_quality_score: float
    chunk_importance_score: float
    chunk_entity_density: float
    chunk_legal_density: float
    chunk_reference_count: int


class DouChunker:
    """Generate deterministic chunk docs from a DOU Mongo parent document."""

    def __init__(
        self,
        *,
        chunker_version: str = CHUNKER_VERSION,
        max_chunks: int = MAX_CHUNKS_PER_DOC,
        hard_limit: int = HARD_LIMIT,
    ) -> None:
        self.chunker_version = chunker_version
        self.max_chunks = max_chunks
        self.hard_limit = hard_limit

    def is_eligible(self, doc: dict[str, Any]) -> bool:
        text = _normalize_text(doc.get("texto"))
        html = _normalize_text(doc.get("content_html"))
        return bool(
            len(text) > MIN_ELIGIBLE_TEXT_LEN
            or bool(doc.get("is_multipart"))
            or bool(doc.get("was_blob_split"))
            or bool(doc.get("was_page_fragment_merged"))
            or any(
                marker in html.lower()
                for marker in ("<p", "<table", "<h1", "<h2", "<h3")
            )
        )

    def build_chunk_docs(
        self, doc: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.is_eligible(doc):
            return [], self._ledger(doc, [], [], "ineligible")

        raw_candidates = self._build_candidates(doc)
        if not raw_candidates:
            return [], self._ledger(doc, [], [], "no_candidates")

        pretruncated = raw_candidates[: self.hard_limit]
        retained = sorted(
            pretruncated,
            key=lambda item: (-item.priority, item.char_start, item.chunk_seq),
        )[: self.max_chunks]
        retained = sorted(retained, key=lambda item: item.chunk_seq)

        manifest_ids = [self._chunk_id(doc, candidate) for candidate in retained]
        ledger = self._ledger(doc, pretruncated, manifest_ids, None)

        chunk_docs: list[dict[str, Any]] = []
        for candidate in retained:
            chunk_id = self._chunk_id(doc, candidate)
            chunk_manifest_hash = _sha256_hex(
                [
                    str(doc.get("_id") or ""),
                    self.chunker_version,
                    candidate.chunk_type,
                    str(candidate.char_start),
                    str(candidate.char_end),
                    candidate.text,
                ]
            )
            chunk_feature_hash = _sha256_hex(
                [
                    chunk_manifest_hash,
                    str(candidate.chunk_quality_score),
                    str(candidate.chunk_importance_score),
                    str(candidate.chunk_entity_density),
                    str(candidate.chunk_legal_density),
                    str(candidate.chunk_reference_count),
                    _normalize_text(doc.get("pipeline_fingerprint")) or "parent_v2",
                ]
            )
            chunk_docs.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": chunk_id,
                    "parent_doc_id": str(doc.get("_id") or ""),
                    "logical_doc_id": _normalize_text(doc.get("logical_doc_id"))
                    or str(doc.get("_id") or ""),
                    "chunk_seq": candidate.chunk_seq,
                    "chunk_type": candidate.chunk_type,
                    "char_start": candidate.char_start,
                    "char_end": candidate.char_end,
                    "text": candidate.text,
                    "rerank_text": self._rerank_text(doc, candidate),
                    "identifica": _normalize_text(doc.get("identifica")) or None,
                    "ementa": _normalize_text(doc.get("ementa")) or None,
                    "art_type": _normalize_text(doc.get("art_type")) or None,
                    "issuing_organ": _normalize_text(
                        doc.get("issuing_organ") or doc.get("orgao")
                    )
                    or None,
                    "pub_date": self._pub_date(doc.get("pub_date")),
                    "section": _normalize_text(
                        doc.get("section_normalized") or doc.get("section")
                    ).lower()
                    or None,
                    "edition_number": str(doc.get("edition"))
                    if doc.get("edition") is not None
                    else None,
                    "source_url": _normalize_text(doc.get("source_url")) or None,
                    "source_type": "dou_chunk",
                    "authority_score": _safe_float(doc.get("authority_score")),
                    "reconstruction_trust_score": _safe_float(
                        doc.get("reconstruction_trust_score")
                    ),
                    "chunk_quality_score": candidate.chunk_quality_score,
                    "chunk_importance_score": candidate.chunk_importance_score,
                    "chunk_entity_density": candidate.chunk_entity_density,
                    "chunk_legal_density": candidate.chunk_legal_density,
                    "chunk_reference_count": candidate.chunk_reference_count,
                    "chunk_manifest_hash": chunk_manifest_hash,
                    "chunk_feature_hash": chunk_feature_hash,
                    "chunker_version": self.chunker_version,
                    "pipeline_fingerprint": _normalize_text(
                        doc.get("pipeline_fingerprint")
                    )
                    or None,
                    "embedding_status": "skipped",
                    "embedding_version": _normalize_text(doc.get("embedding_version"))
                    or None,
                    "vector_id": None,
                }
            )

        return chunk_docs, ledger

    def _build_candidates(self, doc: dict[str, Any]) -> list[ChunkCandidate]:
        candidates: list[ChunkCandidate] = []
        seq = 0
        identifica = _normalize_text(doc.get("identifica"))
        ementa = _normalize_text(doc.get("ementa"))
        body_text = _normalize_text(doc.get("texto"))
        authority_score = _safe_float(doc.get("authority_score"))
        reconstruction_trust_score = _safe_float(doc.get("reconstruction_trust_score"))
        entity_density = _safe_float(doc.get("entity_density"))

        if identifica:
            candidates.append(
                self._candidate(
                    chunk_seq=seq,
                    chunk_type="title",
                    text=identifica,
                    body_text=body_text,
                    base_priority=10.0 + authority_score,
                    entity_density=entity_density,
                    reconstruction_trust_score=reconstruction_trust_score,
                )
            )
            seq += 1
        if ementa and ementa != identifica:
            candidates.append(
                self._candidate(
                    chunk_seq=seq,
                    chunk_type="ementa",
                    text=ementa,
                    body_text=body_text,
                    base_priority=9.0 + authority_score,
                    entity_density=entity_density,
                    reconstruction_trust_score=reconstruction_trust_score,
                )
            )
            seq += 1

        for block_type, block_text, char_start, char_end in self._iter_body_blocks(
            body_text
        ):
            candidates.append(
                self._candidate(
                    chunk_seq=seq,
                    chunk_type=block_type,
                    text=block_text,
                    body_text=body_text,
                    base_priority=self._base_priority(block_type),
                    entity_density=entity_density,
                    reconstruction_trust_score=reconstruction_trust_score,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
            seq += 1

        return candidates

    def _candidate(
        self,
        *,
        chunk_seq: int,
        chunk_type: str,
        text: str,
        body_text: str,
        base_priority: float,
        entity_density: float,
        reconstruction_trust_score: float,
        char_start: int | None = None,
        char_end: int | None = None,
    ) -> ChunkCandidate:
        if char_start is None:
            char_start = body_text.find(text) if body_text else 0
            if char_start < 0:
                char_start = 0
        if char_end is None:
            char_end = char_start + len(text)

        reference_count = len(_LEGAL_REF_RE.findall(text))
        legal_density = min(1.0, reference_count / max(len(text) / 400.0, 1.0))
        importance = min(1.0, len(text) / 1800.0)
        quality = min(
            1.0, 0.55 + reconstruction_trust_score * 0.35 + legal_density * 0.1
        )
        priority = round(
            base_priority
            + importance
            + legal_density * 2.0
            + entity_density
            + reconstruction_trust_score * 0.5,
            6,
        )

        return ChunkCandidate(
            chunk_seq=chunk_seq,
            chunk_type=chunk_type,
            text=text,
            char_start=max(0, char_start),
            char_end=max(char_start, char_end),
            priority=priority,
            chunk_quality_score=round(quality, 4),
            chunk_importance_score=round(importance, 4),
            chunk_entity_density=round(entity_density, 4),
            chunk_legal_density=round(legal_density, 4),
            chunk_reference_count=reference_count,
        )

    def _iter_body_blocks(self, body_text: str) -> list[tuple[str, str, int, int]]:
        if not body_text:
            return []

        chunks: list[tuple[str, str, int, int]] = []
        cursor = 0
        boundaries = [
            match.start() for match in _ARTICLE_BOUNDARY_RE.finditer(body_text)
        ]
        if not boundaries:
            boundaries = [0]
        if boundaries[0] != 0:
            boundaries.insert(0, 0)
        boundaries.append(len(body_text))

        for start, end in zip(boundaries, boundaries[1:]):
            raw = body_text[start:end].strip()
            if not raw:
                continue
            block_type = self._detect_block_type(raw)
            for text, inner_start, inner_end in self._split_long_block(raw, start):
                chunks.append((block_type, text, inner_start, inner_end))
            cursor = end

        if cursor < len(body_text):
            tail = body_text[cursor:].strip()
            if tail:
                for text, inner_start, inner_end in self._split_long_block(
                    tail, cursor
                ):
                    chunks.append(
                        (self._detect_block_type(tail), text, inner_start, inner_end)
                    )

        return chunks

    def _split_long_block(
        self, text: str, base_start: int
    ) -> list[tuple[str, int, int]]:
        if len(text) <= TARGET_CHUNK_CHARS:
            return [(text, base_start, base_start + len(text))]

        pieces: list[tuple[str, int, int]] = []
        local_start = 0
        while local_start < len(text):
            local_end = min(local_start + TARGET_CHUNK_CHARS, len(text))
            if local_end < len(text):
                split_at = text.rfind("\n\n", local_start, local_end)
                if split_at <= local_start:
                    split_at = text.rfind(". ", local_start, local_end)
                if split_at > local_start:
                    local_end = split_at + 1
            piece = text[local_start:local_end].strip()
            if piece:
                absolute_start = base_start + local_start
                pieces.append((piece, absolute_start, absolute_start + len(piece)))
            if local_end >= len(text):
                break
            local_start = max(local_end - OVERLAP_CHARS, local_start + 1)
        return pieces

    def _detect_block_type(self, text: str) -> str:
        lowered = text[:120].lower()
        if lowered.startswith("art"):
            return "article_block"
        if lowered.startswith("anexo"):
            return "annex_block"
        if "refer" in lowered:
            return "reference_block"
        if lowered.startswith("assina") or "ministro" in lowered[:180]:
            return "signature_block"
        return "article_block"

    def _base_priority(self, block_type: str) -> float:
        if block_type == "annex_block":
            return 6.5
        if block_type == "reference_block":
            return 6.0
        if block_type == "signature_block":
            return 5.0
        return 7.0

    def _chunk_id(self, doc: dict[str, Any], candidate: ChunkCandidate) -> str:
        return _sha256_hex(
            [
                str(doc.get("_id") or ""),
                self.chunker_version,
                str(candidate.chunk_seq),
                candidate.chunk_type,
                str(candidate.char_start),
                str(candidate.char_end),
            ]
        )[:40]

    def _ledger(
        self,
        doc: dict[str, Any],
        candidates: list[ChunkCandidate],
        retained_chunk_ids: list[str],
        reason: str | None,
    ) -> dict[str, Any]:
        pruned = max(0, len(candidates) - len(retained_chunk_ids))
        manifest_hash = _sha256_hex(
            [
                str(doc.get("_id") or ""),
                self.chunker_version,
                str(len(candidates)),
                "|".join(retained_chunk_ids),
            ]
        )
        return {
            "_id": f"{doc.get('_id')}:{self.chunker_version}",
            "doc_id": str(doc.get("_id") or ""),
            "logical_doc_id": _normalize_text(doc.get("logical_doc_id"))
            or str(doc.get("_id") or ""),
            "chunker_version": self.chunker_version,
            "pipeline_fingerprint": _normalize_text(doc.get("pipeline_fingerprint"))
            or None,
            "chunk_manifest_hash": manifest_hash,
            "raw_chunk_candidate_count": len(candidates),
            "retained_chunk_count": len(retained_chunk_ids),
            "pruned_chunk_count": pruned,
            "pruning_reason": reason
            or ("hard_limit" if len(candidates) > self.max_chunks else "none"),
            "pruning_audit_version": PRUNING_AUDIT_VERSION,
            "retained_chunk_ids": retained_chunk_ids,
            "updated_at": datetime.now(UTC),
        }

    def _pub_date(self, value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.astimezone(UTC).strftime("%Y-%m-%d")
        if value:
            return str(value)[:10]
        return None

    def _rerank_text(self, doc: dict[str, Any], candidate: ChunkCandidate) -> str:
        prefix = " ".join(
            item
            for item in (
                _normalize_text(doc.get("identifica")),
                _normalize_text(doc.get("ementa")),
                _normalize_text(doc.get("issuing_organ") or doc.get("orgao")),
                _normalize_text(doc.get("art_type")),
            )
            if item
        )
        return _normalize_text(f"{prefix} {candidate.text}")
