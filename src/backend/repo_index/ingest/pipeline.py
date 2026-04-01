from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.backend.repo_index.config import settings
from src.backend.repo_index.ingest.chunking import build_chunks
from src.backend.repo_index.repo_semantics import canonical_rank, classify_source
from src.backend.repo_index.storage.db import get_connection


@dataclass(frozen=True)
class CandidateDocument:
    path: Path
    doc_id: str
    content_hash: str
    source_type: str
    authority_weight: float
    language: str
    kind: str
    title: str
    text: str
    size_bytes: int
    mtime_ns: int


class RepositoryIndexer:
    def __init__(self) -> None:
        self._ensure_artifact_dirs()

    def _ensure_artifact_dirs(self) -> None:
        settings.index_dir.mkdir(parents=True, exist_ok=True)
        settings.ledger_root.mkdir(parents=True, exist_ok=True)
        settings.manifests_root.mkdir(parents=True, exist_ok=True)

    def discover_paths(self) -> list[Path]:
        paths: list[Path] = []
        for path in sorted(settings.repo_root.rglob("*")):
            if not path.is_file():
                continue
            if classify_source(path) is None:
                continue
            paths.append(path)
        return sorted(paths)

    def _candidate(self, path: Path) -> CandidateDocument | None:
        descriptor = classify_source(path)
        if descriptor is None:
            return None
        try:
            size_bytes = path.stat().st_size
        except OSError:
            return None
        if size_bytes > settings.max_file_bytes:
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in raw:
            return None
        text = raw.decode("utf-8", errors="ignore")
        if not text.strip():
            return None
        from src.backend.repo_index.repo_semantics import _language_for_path

        language, kind = _language_for_path(path)
        doc_id = hashlib.sha256(raw).hexdigest()
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return CandidateDocument(
            path=path,
            doc_id=doc_id,
            content_hash=content_hash,
            source_type=descriptor.source_type,
            authority_weight=descriptor.authority_weight,
            language=language,
            kind=kind,
            title=path.name,
            text=text,
            size_bytes=size_bytes,
            mtime_ns=path.stat().st_mtime_ns,
        )

    def _deduplicate(
        self, candidates: list[CandidateDocument]
    ) -> tuple[list[CandidateDocument], dict[str, str]]:
        groups: dict[str, list[CandidateDocument]] = defaultdict(list)
        for candidate in candidates:
            groups[candidate.content_hash].append(candidate)
        canonical: list[CandidateDocument] = []
        duplicates: dict[str, str] = {}
        for group in groups.values():
            chosen = min(group, key=lambda item: canonical_rank(item.path))
            canonical.append(chosen)
            for item in group:
                if item.doc_id != chosen.doc_id:
                    duplicates[item.doc_id] = chosen.doc_id
        return canonical, duplicates

    def _document_payload(
        self,
        candidate: CandidateDocument,
        *,
        is_duplicate: bool,
        duplicate_of: str | None,
    ) -> dict:
        rel = candidate.path.relative_to(settings.repo_root).as_posix()
        return {
            "doc_id": candidate.doc_id,
            "source_path": rel,
            "source_type": candidate.source_type,
            "authority_weight": candidate.authority_weight,
            "language": candidate.language,
            "kind": candidate.kind,
            "content_hash": candidate.content_hash,
            "pipeline_fingerprint": settings.pipeline_fingerprint,
            "title": candidate.title,
            "text": candidate.text,
            "size_bytes": candidate.size_bytes,
            "mtime_ns": candidate.mtime_ns,
            "is_duplicate": is_duplicate,
            "duplicate_of": duplicate_of,
        }

    def reset_state(self) -> None:
        conn = get_connection()
        conn.executescript(
            """
            DELETE FROM chunks_fts;
            DELETE FROM chunks;
            DELETE FROM files;
            DELETE FROM embeddings;
            DELETE FROM meta;
            """
        )
        conn.commit()
        conn.close()

    def build(
        self, full: bool = False, paths: list[Path] | None = None
    ) -> dict[str, int]:
        self._ensure_artifact_dirs()
        if full:
            self.reset_state()
        target_paths = paths or self.discover_paths()
        candidates = [
            item
            for item in (self._candidate(path) for path in target_paths)
            if item is not None
        ]
        canonical, duplicates = self._deduplicate(candidates)

        document_rows = []
        chunk_rows = []
        pruning_rows = []
        for candidate in canonical:
            document_row = self._document_payload(
                candidate, is_duplicate=False, duplicate_of=None
            )
            document_rows.append(document_row)
            chunks, pruning_ledger = build_chunks(
                doc_id=candidate.doc_id,
                text=candidate.text,
                path=candidate.path.relative_to(settings.repo_root).as_posix(),
                language=candidate.language,
                source_type=candidate.source_type,
                authority_weight=candidate.authority_weight,
            )
            if pruning_ledger:
                pruning_ledger["source_path"] = str(
                    candidate.path.relative_to(settings.repo_root).as_posix()
                )
                pruning_rows.append(pruning_ledger)
            chunk_rows.extend(chunks)

        duplicate_rows = []
        for candidate in candidates:
            duplicate_of = duplicates.get(candidate.doc_id)
            if duplicate_of is None:
                continue
            duplicate_rows.append(
                self._document_payload(
                    candidate, is_duplicate=True, duplicate_of=duplicate_of
                )
            )

        conn = get_connection()
        if not full:
            for path in target_paths:
                rel = path.relative_to(settings.repo_root).as_posix()
                existing = conn.execute(
                    "SELECT id FROM files WHERE source_path = ?", (rel,)
                ).fetchone()
                if existing:
                    file_id = existing["id"]
                    conn.execute(
                        "DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE file_id = ?)",
                        (file_id,),
                    )
                    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
                    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))

        for row in document_rows + duplicate_rows:
            conn.execute(
                """
                INSERT INTO files (
                    doc_id, source_path, source_type, authority_weight, language, kind,
                    content_hash, pipeline_fingerprint, title, text, size_bytes, mtime_ns,
                    is_duplicate, duplicate_of, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["doc_id"],
                    row["source_path"],
                    row["source_type"],
                    row["authority_weight"],
                    row["language"],
                    row["kind"],
                    row["content_hash"],
                    row["pipeline_fingerprint"],
                    row["title"],
                    row["text"],
                    row["size_bytes"],
                    row["mtime_ns"],
                    row["is_duplicate"],
                    row["duplicate_of"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

        for chunk in chunk_rows:
            cur = conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, doc_id, path, symbol, chunk_type, chunk_seq, char_start, char_end,
                    start_line, end_line, text, source_type, authority_weight, section_type,
                    chunk_manifest_hash, chunk_feature_hash, entity_density, importance_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk["id"],
                    chunk["document_id"],
                    chunk["path"],
                    chunk["symbol"],
                    chunk["chunk_type"],
                    chunk["chunk_seq"],
                    chunk["char_start"],
                    chunk["char_end"],
                    chunk["start_line"],
                    chunk["end_line"],
                    chunk["text"],
                    chunk["source_type"],
                    chunk["authority_weight"],
                    chunk["section_type"],
                    chunk["chunk_manifest_hash"],
                    chunk["chunk_feature_hash"],
                    chunk["entity_density"],
                    chunk["importance_score"],
                ),
            )
            chunk_rowid = cur.lastrowid
            conn.execute(
                """
                INSERT INTO chunks_fts(rowid, path, symbol, content)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chunk_rowid,
                    chunk["path"],
                    chunk["symbol"] or "",
                    f"{chunk['path']}\n{chunk['symbol'] or ''}\n{chunk['text']}".strip(),
                ),
            )

        conn.commit()
        conn.close()

        summary = {
            "documents": len(document_rows),
            "duplicates": len(duplicate_rows),
            "chunks": len(chunk_rows),
            "pruned_documents": len(pruning_rows),
        }
        self._write_build_artifacts(
            full=full,
            paths_scanned=target_paths,
            canonical_rows=document_rows,
            duplicate_rows=duplicate_rows,
            chunk_rows=chunk_rows,
            pruning_rows=pruning_rows,
            summary=summary,
        )
        return summary

    def _write_build_artifacts(
        self,
        *,
        full: bool,
        paths_scanned: list[Path],
        canonical_rows: list[dict],
        duplicate_rows: list[dict],
        chunk_rows: list[dict],
        pruning_rows: list[dict],
        summary: dict[str, int],
    ) -> None:
        created_at = datetime.now(timezone.utc)
        build_id = hashlib.sha256(
            json.dumps(
                {
                    "full": full,
                    "paths": [
                        str(path.relative_to(settings.repo_root).as_posix())
                        for path in paths_scanned
                    ],
                    "summary": summary,
                    "fingerprint": settings.pipeline_fingerprint,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        chunks_by_doc: dict[str, list[dict]] = defaultdict(list)
        for chunk in chunk_rows:
            chunks_by_doc[chunk["document_id"]].append(chunk)
        documents = []
        for row in sorted(canonical_rows, key=lambda item: item["source_path"]):
            doc_chunks = sorted(
                chunks_by_doc[row["doc_id"]], key=lambda item: item["chunk_seq"]
            )
            documents.append(
                {
                    "source_path": row["source_path"],
                    "doc_id": row["doc_id"],
                    "content_hash": row["content_hash"],
                    "source_type": row["source_type"],
                    "authority_weight": row["authority_weight"],
                    "language": row["language"],
                    "chunk_count": len(doc_chunks),
                    "chunk_manifest_hashes": [
                        chunk["chunk_manifest_hash"] for chunk in doc_chunks
                    ],
                    "chunk_feature_hashes": [
                        chunk["chunk_feature_hash"] for chunk in doc_chunks
                    ],
                }
            )
        manifest = {
            "build_id": build_id,
            "created_at": created_at.isoformat(),
            "full": full,
            "pipeline_fingerprint": settings.pipeline_fingerprint,
            "summary": {**summary, "paths_scanned": len(paths_scanned)},
            "documents": documents,
            "duplicates": [
                {
                    "source_path": row["source_path"],
                    "doc_id": row["doc_id"],
                    "duplicate_of": row["duplicate_of"],
                    "content_hash": row["content_hash"],
                }
                for row in sorted(duplicate_rows, key=lambda item: item["source_path"])
            ],
            "pruning": [
                {
                    "doc_id": row["document_id"],
                    "source_path": row["source_path"],
                    "original_candidate_count": row["original_candidate_count"],
                    "kept_count": row["kept_count"],
                    "pruned_chunk_count": row["original_candidate_count"]
                    - row["kept_count"],
                    "dropped_sequences": row["dropped_sequences"],
                    "reason": row["reason"],
                }
                for row in pruning_rows
            ],
        }
        manifest_name = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}_{build_id}.json"
        manifest_path = settings.manifests_root / manifest_name
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (settings.manifests_root / "latest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        pruning_path = settings.ledger_root / "pruning.jsonl"
        with pruning_path.open("a", encoding="utf-8") as handle:
            for row in manifest["pruning"]:
                handle.write(
                    json.dumps(
                        {
                            "build_id": build_id,
                            "created_at": created_at.isoformat(),
                            **row,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
