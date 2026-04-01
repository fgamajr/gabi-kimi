from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.backend.repo_index.config import settings
from src.backend.repo_index.repo_semantics import infer_section_type

PY_SYMBOL_RE = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
JS_TS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+function|function|class|const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"
)
SH_SYMBOL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


@dataclass(frozen=True)
class ChunkCandidate:
    text: str
    char_start: int
    char_end: int


def split_text(
    text: str, target_chars: int = settings.chunk_target_chars
) -> list[ChunkCandidate]:
    paragraphs = [
        segment.strip() for segment in re.split(r"\n\s*\n", text) if segment.strip()
    ]
    candidates: list[ChunkCandidate] = []
    cursor = 0
    buffer = ""
    start = 0
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if buffer and len(candidate) > target_chars:
            end = start + len(buffer)
            candidates.append(
                ChunkCandidate(text=buffer, char_start=start, char_end=end)
            )
            cursor = end
            buffer = paragraph
            start = cursor + 2
            continue
        if not buffer:
            start = cursor
        buffer = candidate
    if buffer:
        candidates.append(
            ChunkCandidate(text=buffer, char_start=start, char_end=start + len(buffer))
        )
    return candidates or [ChunkCandidate(text=text, char_start=0, char_end=len(text))]


def _coalesce(
    candidates: list[ChunkCandidate], max_chunks: int
) -> list[ChunkCandidate]:
    merged = candidates[:]
    while len(merged) > max_chunks and len(merged) > 1:
        join_index = min(
            range(len(merged) - 1),
            key=lambda idx: len(merged[idx].text) + len(merged[idx + 1].text),
        )
        left, right = merged[join_index], merged[join_index + 1]
        combined = ChunkCandidate(
            text=f"{left.text}\n\n{right.text}".strip(),
            char_start=left.char_start,
            char_end=right.char_end,
        )
        merged = merged[:join_index] + [combined] + merged[join_index + 2 :]
    return merged


def _symbol_matches(language: str, line: str) -> str | None:
    if language == "python":
        match = PY_SYMBOL_RE.match(line)
        return match.group(1) if match else None
    if language in {"typescript", "javascript"}:
        match = JS_TS_SYMBOL_RE.match(line)
        return match.group(1) if match else None
    if language == "shell":
        match = SH_SYMBOL_RE.match(line)
        return match.group(1) if match else None
    return None


def _split_large_chunk(
    path: str,
    symbol: str | None,
    chunk_type: str,
    start_line: int,
    lines: list[str],
) -> list[dict]:
    chunks: list[dict] = []
    current: list[str] = []
    current_start = start_line
    current_len = 0
    for idx, line in enumerate(lines, start=start_line):
        line_len = len(line) + 1
        if current and current_len + line_len > settings.chunk_target_chars:
            content = "\n".join(current).strip()
            if content:
                chunks.append(
                    {
                        "path": path,
                        "symbol": symbol,
                        "chunk_type": chunk_type,
                        "start_line": current_start,
                        "end_line": idx - 1,
                        "content": content,
                        "char_start": 0,
                        "char_end": len(content),
                    }
                )
            overlap = (
                current[-settings.window_overlap :]
                if len(current) > settings.window_overlap
                else current[:]
            )
            current = overlap + [line]
            current_start = max(start_line, idx - len(overlap))
            current_len = sum(len(item) + 1 for item in current)
            continue
        current.append(line)
        current_len += line_len
    content = "\n".join(current).strip()
    if content:
        chunks.append(
            {
                "path": path,
                "symbol": symbol,
                "chunk_type": chunk_type,
                "start_line": current_start,
                "end_line": start_line + len(lines) - 1,
                "content": content,
                "char_start": 0,
                "char_end": len(content),
            }
        )
    return chunks


def _window_chunks(path: str, text: str, chunk_type: str) -> list[dict]:
    lines = text.splitlines()
    chunks: list[dict] = []
    step = max(1, settings.window_lines - settings.window_overlap)
    for start in range(0, len(lines), step):
        window = lines[start : start + settings.window_lines]
        content = "\n".join(window).strip()
        if not content:
            continue
        start_line = start + 1
        chunks.extend(_split_large_chunk(path, None, chunk_type, start_line, window))
        if start + settings.window_lines >= len(lines):
            break
    return chunks


def _markdown_chunks(path: str, text: str) -> list[dict]:
    lines = text.splitlines()
    headings: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        match = MD_HEADING_RE.match(line)
        if match:
            headings.append((idx, match.group(1).strip()))
    if not headings:
        return _window_chunks(path, text, "markdown_window")
    chunks: list[dict] = []
    if headings[0][0] > 1:
        prelude = lines[: headings[0][0] - 1]
        prelude_text = "\n".join(prelude).strip()
        if prelude_text:
            chunks.extend(
                _split_large_chunk(path, None, "markdown_prelude", 1, prelude)
            )
    for index, (line_no, title) in enumerate(headings):
        next_line = (
            headings[index + 1][0] if index + 1 < len(headings) else len(lines) + 1
        )
        block = lines[line_no - 1 : next_line - 1]
        chunks.extend(
            _split_large_chunk(path, title, "markdown_section", line_no, block)
        )
    return chunks


def _code_chunks(path: str, text: str, language: str) -> list[dict]:
    lines = text.splitlines()
    symbols: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        symbol = _symbol_matches(language, line)
        if symbol:
            symbols.append((idx, symbol))
    if not symbols:
        return _window_chunks(path, text, "code_window")
    chunks: list[dict] = []
    if symbols[0][0] > 1:
        prelude = lines[: symbols[0][0] - 1]
        prelude_text = "\n".join(prelude).strip()
        if prelude_text:
            chunks.extend(_split_large_chunk(path, None, "module_prelude", 1, prelude))
    for index, (line_no, symbol) in enumerate(symbols):
        next_line = (
            symbols[index + 1][0] if index + 1 < len(symbols) else len(lines) + 1
        )
        block = lines[line_no - 1 : next_line - 1]
        chunks.extend(_split_large_chunk(path, symbol, "symbol", line_no, block))
    return chunks


def _entity_density(text: str) -> float:
    tokens = max(len(text.split()), 1)
    matches = len(re.findall(r"\b[A-Z][a-zA-Z0-9_]*\b", text))
    return round(matches / tokens, 6)


def _importance(text: str) -> float:
    tokens = max(len(text.split()), 1)
    code_signals = len(
        re.findall(
            r"\b(def|class|function|const|let|var|import|export|return|await|async)\b",
            text,
        )
    )
    return round(code_signals / tokens, 6)


def build_chunks(
    doc_id: str,
    text: str,
    path: str,
    language: str,
    source_type: str,
    authority_weight: float,
) -> tuple[list[dict], dict | None]:
    if language == "markdown":
        raw_chunks = _markdown_chunks(path, text)
    elif language in {"python", "typescript", "javascript", "shell"}:
        raw_chunks = _code_chunks(path, text, language)
    else:
        raw_chunks = _window_chunks(path, text, f"{language}_window")

    candidates = [
        ChunkCandidate(text=c["content"], char_start=0, char_end=len(c["content"]))
        for c in raw_chunks
    ]
    if len(candidates) > settings.max_chunks_per_file:
        scored = [
            (idx, _importance(candidate.text))
            for idx, candidate in enumerate(candidates)
        ]
        keep = {0, len(candidates) - 1}
        ranked_middle = sorted(scored[1:-1], key=lambda item: (-item[1], item[0]))
        for idx, _score in ranked_middle[: settings.max_chunks_per_file - len(keep)]:
            keep.add(idx)
        kept_indices = sorted(keep)
        pruning_ledger = {
            "document_id": doc_id,
            "original_candidate_count": len(candidates),
            "kept_count": len(kept_indices),
            "dropped_sequences": [
                idx for idx in range(len(candidates)) if idx not in keep
            ],
            "reason": f"candidate_count_exceeded_{settings.max_chunks_per_file}",
        }
        candidates = [candidates[idx] for idx in kept_indices]
        raw_chunks = [raw_chunks[idx] for idx in kept_indices]
    else:
        pruning_ledger = None

    candidates = _coalesce(candidates, settings.max_chunks_per_file)
    raw_chunks = raw_chunks[: len(candidates)]

    chunks = []
    for seq, (candidate, raw) in enumerate(zip(candidates, raw_chunks)):
        entity_density = _entity_density(candidate.text)
        importance = round(
            (_importance(candidate.text) * 0.5)
            + (authority_weight * 0.3)
            + (entity_density * 0.2),
            6,
        )
        section_type = infer_section_type(candidate.text, language, Path(path))
        manifest_payload = {
            "doc_id": doc_id,
            "seq": seq,
            "char_start": candidate.char_start,
            "char_end": candidate.char_end,
            "source_type": source_type,
        }
        feature_payload = {
            "entity_density": entity_density,
            "importance_score": importance,
            "section_type": section_type,
        }
        chunk_manifest_hash = hashlib.sha256(
            json.dumps(manifest_payload, sort_keys=True).encode()
        ).hexdigest()
        chunk_feature_hash = hashlib.sha256(
            json.dumps(feature_payload, sort_keys=True).encode()
        ).hexdigest()
        chunk_id = hashlib.sha256(
            f"{doc_id}:{seq}:{chunk_manifest_hash}".encode()
        ).hexdigest()
        chunks.append(
            {
                "id": chunk_id,
                "document_id": doc_id,
                "path": path,
                "symbol": raw.get("symbol"),
                "chunk_type": raw.get("chunk_type", "window"),
                "chunk_seq": seq,
                "char_start": candidate.char_start,
                "char_end": candidate.char_end,
                "start_line": raw.get("start_line", 1),
                "end_line": raw.get("end_line", 1),
                "text": candidate.text,
                "source_type": source_type,
                "authority_weight": authority_weight,
                "section_type": section_type,
                "chunk_manifest_hash": chunk_manifest_hash,
                "chunk_feature_hash": chunk_feature_hash,
                "entity_density": entity_density,
                "importance_score": importance,
            }
        )
    return chunks, pruning_ledger
