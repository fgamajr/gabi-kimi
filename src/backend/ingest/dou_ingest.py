"""DOU schema ingestor.

Reads extracted ZIPs (XML + images), parses, enriches via NLP extraction,
and inserts into the ``dou.*`` PostgreSQL schema.

Transaction granularity: one commit per ZIP.

Usage (standalone):
    python -m src.backend.ingest.dou_ingest --data-dir ops/data/sample200/zips --dsn "host=localhost port=5433 ..."

Usage (from pipeline):
    from src.backend.ingest.dou_ingest import DOUIngestor
    ingestor = DOUIngestor(dsn)
    result = ingestor.ingest_zip(zip_path)
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.backend.ingest.html_extractor import (
    ImageRef,
    NormRef,
    ProcRef,
    Signature,
    extract_document_number,
    extract_images,
    extract_issuing_organ,
    extract_normative_references,
    extract_procedure_references,
    normalize_art_type,
    strip_html,
)
from src.backend.ingest.html_extractor import _extract_signatures_precise as extract_signatures
from src.backend.ingest.image_checker import (
    check_document_images,
    checked_image_row,
    media_name_from_ref,
    resolve_external_media_url,
    rewrite_document_html_images,
    summarize_checked_images,
)
from src.backend.ingest.multipart_merger import MergedArticle, group_and_merge, merge_page_fragments
from src.backend.ingest.normalizer import (
    _canonicalize_content,
    _compute_natural_key_hash,
    normalize_pub_date,
    normalize_section,
)
from src.backend.ingest.xml_parser import DOUArticle, INLabsXMLParser, is_index_document, split_blob_acts


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ZIPIngestResult:
    """Result of ingesting one ZIP or single XML into dou.* schema."""
    zip_path: Path
    success: bool = True
    xml_count: int = 0
    image_count: int = 0
    articles_found: int = 0  # article count after merge/filter (for worker_jobs)
    documents_inserted: int = 0
    documents_dup: int = 0    # skipped (ON CONFLICT id_materia)
    documents_failed: int = 0 # per-article insert/parse errors (PROC-05)
    media_inserted: int = 0
    signatures_inserted: int = 0
    norm_refs_inserted: int = 0
    proc_refs_inserted: int = 0
    images_available: int = 0
    images_missing: int = 0
    images_unknown: int = 0
    parse_errors: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


@dataclass(slots=True)
class BatchIngestResult:
    """Aggregate result of ingesting a batch of ZIPs."""
    zips_processed: int = 0
    zips_succeeded: int = 0
    zips_failed: int = 0
    total_documents: int = 0
    total_media: int = 0
    total_signatures: int = 0
    total_norm_refs: int = 0
    total_proc_refs: int = 0
    total_images_available: int = 0
    total_images_missing: int = 0
    total_images_unknown: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_str(s: str) -> str:
    """SHA-256 hex digest of a string."""
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"})
_XML_EXTENSIONS = frozenset({".xml"})


def _guess_media_type(ext: str) -> str:
    """Guess MIME type from file extension."""
    mt = mimetypes.guess_type(f"file{ext}")[0]
    return mt or "application/octet-stream"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# DOUIngestor
# ---------------------------------------------------------------------------

class DOUIngestor:
    """Ingest DOU ZIPs into the ``dou.*`` PostgreSQL schema."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def ingest_zip(self, zip_path: Path) -> ZIPIngestResult:
        """Ingest a single ZIP file.

        Extracts all XML and images to a temp directory, parses,
        merges multi-parts, extracts NLP, and inserts into DB.
        One transaction per ZIP.
        """
        import psycopg2  # lazy import

        t0 = time.monotonic()
        result = ZIPIngestResult(zip_path=zip_path)

        # --- Extract ZIP ---
        extract_dir = zip_path.parent / f".tmp_{zip_path.stem}"
        extract_dir.mkdir(parents=True, exist_ok=True)

        xml_files: list[Path] = []
        image_files: list[Path] = []

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    # ZIP Slip (PROC-06): reject path traversal and absolute paths
                    if name.startswith("/") or ".." in name:
                        result.errors.append(f"ZIP Slip rejected: {name}")
                        result.success = False
                        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
                        _cleanup_dir(extract_dir)
                        return result
                    suffix = Path(name).suffix.lower()
                    target = extract_dir / Path(name).name
                    try:
                        with zf.open(info) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        if suffix in _XML_EXTENSIONS:
                            xml_files.append(target)
                        elif suffix in _IMAGE_EXTENSIONS:
                            image_files.append(target)
                    except Exception as ex:
                        result.errors.append(f"extract {name}: {ex}")
        except (zipfile.BadZipFile, Exception) as ex:
            result.errors.append(f"open zip: {ex}")
            result.success = False
            result.elapsed_ms = int((time.monotonic() - t0) * 1000)
            return result

        xml_files.sort()
        image_files.sort()
        result.xml_count = len(xml_files)
        result.image_count = len(image_files)

        # --- Build image lookup: name (no ext) → file path ---
        image_lookup: dict[str, Path] = {}
        for img_path in image_files:
            image_lookup[img_path.stem] = img_path

        # --- Parse XML ---
        parser = INLabsXMLParser()
        parsed: list[tuple[DOUArticle, Path]] = []
        for xf in xml_files:
            try:
                article = parser.parse_file(xf)
                parsed.append((article, xf))
            except Exception as ex:
                result.parse_errors += 1
                result.errors.append(f"parse {xf.name}: {ex}")

        # --- Merge multi-parts ---
        merged_articles = group_and_merge(parsed)

        # --- Merge page fragments (Bug 3) ---
        merged_articles = merge_page_fragments(merged_articles)

        # --- Filter index docs (Bug 1) and expand blob docs (Bug 2) ---
        filtered: list[MergedArticle] = []
        for ma in merged_articles:
            if is_index_document(ma.article):
                _log(f"  skipping index doc {ma.base_id_materia}")
                continue
            # Try splitting blob docs into individual acts
            segments = split_blob_acts(ma.article, base_id_materia=ma.base_id_materia)
            if len(segments) > 1:
                _log(f"  split blob {ma.base_id_materia} → {len(segments)} acts")
                for seg in segments:
                    filtered.append(MergedArticle(
                        article=seg,
                        xml_paths=ma.xml_paths,
                        is_multipart=ma.is_multipart,
                        part_count=ma.part_count,
                        base_id_materia=seg.id_materia,
                    ))
            else:
                filtered.append(ma)
        merged_articles = filtered
        result.articles_found = len(merged_articles)

        # --- ZIP metadata ---
        zip_sha = _sha256_file(zip_path)
        zip_size = zip_path.stat().st_size
        zip_filename = zip_path.name

        # Infer month/section from filename patterns
        # Common: "2020-09_do1_S01092020.zip" or "S01092020.zip"
        zip_month, zip_section = _infer_zip_meta(zip_filename)

        # --- Database insertion ---
        conn = psycopg2.connect(self.dsn)
        try:
            conn.autocommit = False
            cur = conn.cursor()

            # Insert source_zip
            source_zip_id = self._upsert_source_zip(
                cur, zip_filename, zip_month, zip_section, zip_sha,
                zip_size, len(xml_files), len(image_files),
            )

            for ma in merged_articles:
                try:
                    counts = self._insert_document(
                        cur, ma, source_zip_id, image_lookup,
                    )
                    if counts.get("inserted"):
                        result.documents_inserted += 1
                    else:
                        result.documents_dup += 1
                    result.media_inserted += counts["media"]
                    result.signatures_inserted += counts["signatures"]
                    result.norm_refs_inserted += counts["norm_refs"]
                    result.proc_refs_inserted += counts["proc_refs"]
                    result.images_available += counts["images_available"]
                    result.images_missing += counts["images_missing"]
                    result.images_unknown += counts["images_unknown"]
                except Exception as ex:
                    result.documents_failed += 1
                    result.errors.append(
                        f"insert doc {ma.base_id_materia}: {ex}"
                    )

            conn.commit()
        except Exception as ex:
            conn.rollback()
            result.success = False
            result.errors.append(f"transaction: {ex}")
        finally:
            conn.close()

        # Cleanup temp dir
        _cleanup_dir(extract_dir)

        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    def ingest_single_xml(self, xml_path: Path) -> ZIPIngestResult:
        """Ingest a single XML file (e.g. admin upload). Same pipeline as one-XML ZIP, no images."""
        import psycopg2  # lazy import

        t0 = time.monotonic()
        result = ZIPIngestResult(zip_path=xml_path)
        result.xml_count = 1
        result.image_count = 0

        parser = INLabsXMLParser()
        try:
            article = parser.parse_file(xml_path)
        except Exception as ex:
            result.success = False
            result.parse_errors = 1
            result.errors.append(f"parse {xml_path.name}: {ex}")
            result.elapsed_ms = int((time.monotonic() - t0) * 1000)
            return result

        parsed: list[tuple[DOUArticle, Path]] = [(article, xml_path)]
        merged_articles = group_and_merge(parsed)
        merged_articles = merge_page_fragments(merged_articles)

        filtered: list[MergedArticle] = []
        for ma in merged_articles:
            if is_index_document(ma.article):
                _log(f"  skipping index doc {ma.base_id_materia}")
                continue
            segments = split_blob_acts(ma.article, base_id_materia=ma.base_id_materia)
            if len(segments) > 1:
                for seg in segments:
                    filtered.append(MergedArticle(
                        article=seg,
                        xml_paths=ma.xml_paths,
                        is_multipart=ma.is_multipart,
                        part_count=ma.part_count,
                        base_id_materia=seg.id_materia,
                    ))
            else:
                filtered.append(ma)
        merged_articles = filtered
        result.articles_found = len(merged_articles)

        file_sha = _sha256_file(xml_path)
        file_size = xml_path.stat().st_size
        file_filename = xml_path.name
        file_month, file_section = _infer_zip_meta(file_filename)

        image_lookup: dict[str, Path] = {}

        conn = psycopg2.connect(self.dsn)
        try:
            conn.autocommit = False
            cur = conn.cursor()
            source_zip_id = self._upsert_source_zip(
                cur, file_filename, file_month, file_section, file_sha,
                file_size, 1, 0,
            )
            for ma in merged_articles:
                try:
                    counts = self._insert_document(
                        cur, ma, source_zip_id, image_lookup,
                    )
                    if counts.get("inserted"):
                        result.documents_inserted += 1
                    else:
                        result.documents_dup += 1
                    result.media_inserted += counts["media"]
                    result.signatures_inserted += counts["signatures"]
                    result.norm_refs_inserted += counts["norm_refs"]
                    result.proc_refs_inserted += counts["proc_refs"]
                    result.images_available += counts.get("images_available", 0)
                    result.images_missing += counts.get("images_missing", 0)
                    result.images_unknown += counts.get("images_unknown", 0)
                except Exception as ex:
                    result.documents_failed += 1
                    result.errors.append(f"insert doc {ma.base_id_materia}: {ex}")
            conn.commit()
        except Exception as ex:
            conn.rollback()
            result.success = False
            result.errors.append(f"transaction: {ex}")
        finally:
            conn.close()

        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    # -- DB operations --

    def _upsert_source_zip(
        self, cur: Any,
        filename: str, month: str | None, section: str | None,
        sha256: str, size_bytes: int, xml_count: int, image_count: int,
    ) -> str:
        """Insert source_zip row, return id. Skip on conflict."""
        cur.execute("""
            INSERT INTO dou.source_zip (filename, month, section, sha256, size_bytes, xml_count, image_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (filename) DO UPDATE SET filename = EXCLUDED.filename
            RETURNING id
        """, (filename, month, section, sha256, size_bytes, xml_count, image_count))
        return str(cur.fetchone()[0])

    def _upsert_edition(
        self, cur: Any,
        pub_date: Any, edition_number: str | None,
        section: str, is_extra: bool, source_zip_id: str,
    ) -> str:
        """Insert edition row, return id. Upsert on conflict."""
        cur.execute("""
            INSERT INTO dou.edition (publication_date, edition_number, section, is_extra, source_zip_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (publication_date, edition_number, section)
            DO UPDATE SET source_zip_id = EXCLUDED.source_zip_id
            RETURNING id
        """, (pub_date, edition_number, section, is_extra, source_zip_id))
        return str(cur.fetchone()[0])

    def _insert_document(
        self, cur: Any,
        ma: MergedArticle,
        source_zip_id: str,
        image_lookup: dict[str, Path],
    ) -> dict[str, int]:
        """Insert one document and all related rows.

        Returns dict with counts: inserted, media, signatures, norm_refs, proc_refs.
        """
        article = ma.article
        counts = {
            "inserted": 0,
            "media": 0,
            "signatures": 0,
            "norm_refs": 0,
            "proc_refs": 0,
            "images_available": 0,
            "images_missing": 0,
            "images_unknown": 0,
        }

        # --- Normalize fields ---
        pub_date = normalize_pub_date(article.pub_date)
        section = normalize_section(article.pub_name)
        is_extra = article.is_extra_edition
        edition_number = article.edition_number or None

        # Upsert edition
        edition_id = self._upsert_edition(
            cur, pub_date, edition_number, section, is_extra, source_zip_id,
        )

        # Extract structured fields
        art_type_norm = normalize_art_type(article.art_type)
        doc_number, doc_year = extract_document_number(article.identifica)
        issuing_organ = extract_issuing_organ(article.art_category)
        body_plain = strip_html(article.texto)
        body_canonical = _canonicalize_content(body_plain)
        content_hash = _sha256_str(body_canonical)
        natural_key_hash, strategy = _compute_natural_key_hash(article)

        # Art class as array
        art_class_arr: list[str] | None = None
        if article.art_class:
            art_class_arr = [p for p in article.art_class.split(":") if p != "00000"]

        # Source XML path (first part)
        source_xml = ma.xml_paths[0].name if ma.xml_paths else None

        # Insert document
        cur.execute("""
            INSERT INTO dou.document (
                edition_id, id_materia, id_oficio, xml_name,
                art_type, art_type_raw, art_category, art_class, page_number,
                identifica, ementa, titulo, sub_titulo,
                body_html, body_plain,
                document_number, document_year, issuing_organ,
                content_hash, natural_key_hash, identity_strategy,
                source_xml_path, is_multipart, multipart_index
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
            ON CONFLICT (id_materia) DO NOTHING
            RETURNING id
        """, (
            edition_id, ma.base_id_materia, article.id_oficio, article.name,
            art_type_norm, article.art_type, article.art_category, art_class_arr, article.number_page,
            article.identifica, article.ementa, article.titulo, article.sub_titulo,
            article.texto, body_plain,
            doc_number, doc_year, issuing_organ,
            content_hash, natural_key_hash, strategy,
            source_xml, ma.is_multipart, ma.part_count if ma.is_multipart else None,
        ))

        row = cur.fetchone()
        if row is None:
            # Document already exists (duplicate id_materia)
            return counts
        doc_id = str(row[0])
        counts["inserted"] = 1

        # --- Insert media (images) ---
        image_refs = extract_images(article.texto)
        checked_images = check_document_images(doc_id=doc_id, refs=image_refs, image_lookup=image_lookup)
        for item in checked_images:
            row = checked_image_row(item)
            cur.execute("""
                INSERT INTO dou.document_media (
                    document_id, media_name, media_type, file_extension,
                    data, size_bytes, sequence_in_document, source_filename, external_url,
                    original_url, availability_status, alt_text, context_hint,
                    fallback_text, local_path, width_px, height_px,
                    ingest_checked_at, retry_count
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                )
            """, (
                doc_id,
                row["media_name"],
                row["media_type"],
                row["file_extension"],
                item.data,
                row["size_bytes"],
                row["position_in_doc"],
                row["source_filename"],
                row["original_url"],
                row["original_url"],
                row["availability_status"],
                row["alt_text"],
                row["context_hint"],
                row["fallback_text"],
                row["local_path"],
                row["width_px"],
                row["height_px"],
                row["ingest_timestamp"],
                row["retry_count"],
            ))
            counts["media"] += 1

        image_summary = summarize_checked_images(checked_images)
        counts["images_available"] = image_summary.get("available", 0)
        counts["images_missing"] = image_summary.get("missing", 0)
        counts["images_unknown"] = image_summary.get("unknown", 0)
        if checked_images:
            rewritten_html = rewrite_document_html_images(article.texto, doc_id, checked_images)
            cur.execute(
                "UPDATE dou.document SET body_html = %s WHERE id = %s::uuid",
                (rewritten_html, doc_id),
            )

        # --- Insert signatures ---
        signatures = extract_signatures(article.texto)
        for sig in signatures:
            cur.execute("""
                INSERT INTO dou.document_signature (
                    document_id, person_name, role_title, sequence_in_document
                ) VALUES (%s, %s, %s, %s)
            """, (doc_id, sig.person_name, sig.role_title, sig.sequence))
            counts["signatures"] += 1

        # --- Insert normative references ---
        norm_refs = extract_normative_references(body_plain)
        for nr in norm_refs:
            cur.execute("""
                INSERT INTO dou.normative_reference (
                    document_id, reference_type, reference_number,
                    reference_date, reference_text, issuing_body
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                doc_id, nr.reference_type, nr.reference_number,
                nr.reference_date, nr.reference_text, nr.issuing_body,
            ))
            counts["norm_refs"] += 1

        # --- Insert procedure references ---
        proc_refs = extract_procedure_references(body_plain)
        for pr in proc_refs:
            cur.execute("""
                INSERT INTO dou.procedure_reference (
                    document_id, procedure_type, procedure_identifier
                ) VALUES (%s, %s, %s)
            """, (doc_id, pr.procedure_type, pr.procedure_identifier))
            counts["proc_refs"] += 1

        return counts

    # -- Batch API --

    def ingest_batch(
        self, zip_paths: list[Path], workers: int = 1,
    ) -> BatchIngestResult:
        """Ingest multiple ZIPs sequentially.

        Each ZIP is its own transaction — failures are isolated.
        """
        t0 = time.monotonic()
        batch = BatchIngestResult()

        for i, zp in enumerate(zip_paths, 1):
            _log(f"[{i}/{len(zip_paths)}] ingesting {zp.name}...")
            zr = self.ingest_zip(zp)

            batch.zips_processed += 1
            if zr.success:
                batch.zips_succeeded += 1
            else:
                batch.zips_failed += 1

            batch.total_documents += zr.documents_inserted
            batch.total_media += zr.media_inserted
            batch.total_signatures += zr.signatures_inserted
            batch.total_norm_refs += zr.norm_refs_inserted
            batch.total_proc_refs += zr.proc_refs_inserted
            batch.total_images_available += zr.images_available
            batch.total_images_missing += zr.images_missing
            batch.total_images_unknown += zr.images_unknown
            batch.errors.extend(zr.errors)

            _log(
                f"  → docs={zr.documents_inserted} media={zr.media_inserted} "
                f"sigs={zr.signatures_inserted} nrefs={zr.norm_refs_inserted} "
                f"prefs={zr.proc_refs_inserted} "
                f"images={{total:{zr.media_inserted} available:{zr.images_available} missing:{zr.images_missing} unknown:{zr.images_unknown}}} "
                f"({'OK' if zr.success else 'FAIL'}) {zr.elapsed_ms}ms"
            )

        batch.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return batch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_zip_meta(filename: str) -> tuple[str | None, str | None]:
    """Infer month and section from ZIP filename.

    Patterns:
        "2020-09_do1_S01092020.zip" → ("2020-09", "do1")
        "S01092020.zip"             → ("2020-09", "do1")
    """
    # Try structured name first
    m = re.match(r'^(\d{4}-\d{2})_(do\d\w?)_', filename, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2).lower()

    # Try INLabs native name: S{section}{MMYYYY}.zip
    m = re.match(r'^S(\d{2})(\d{2})(\d{4})', filename)
    if m:
        sec_code = m.group(1)
        month = m.group(2)
        year = m.group(3)
        section_map = {"01": "do1", "02": "do2", "03": "do3"}
        section = section_map.get(sec_code, f"do{sec_code}")
        return f"{year}-{month}", section

    return None, None


def _cleanup_dir(d: Path) -> None:
    """Remove a directory and all contents."""
    if not d.exists():
        return
    for f in d.iterdir():
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            _cleanup_dir(f)
    d.rmdir()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Ingest DOU ZIPs into dou.* PostgreSQL schema",
    )
    p.add_argument(
        "--data-dir", type=Path, required=True,
        help="Directory containing ZIP files",
    )
    p.add_argument(
        "--dsn",
        default=os.environ.get(
            "GABI_DSN", "host=localhost port=5433 dbname=gabi user=gabi password=gabi"
        ),
        help="PostgreSQL DSN",
    )
    p.add_argument("--limit", type=int, default=0, help="Max ZIPs to process (0=all)")

    args = p.parse_args()

    # Discover ZIPs
    zips = sorted(args.data_dir.glob("*.zip"))
    if args.limit > 0:
        zips = zips[:args.limit]

    if not zips:
        _log(f"No ZIP files found in {args.data_dir}")
        return 1

    _log(f"Found {len(zips)} ZIPs in {args.data_dir}")

    ingestor = DOUIngestor(args.dsn)
    result = ingestor.ingest_batch(zips)

    print("\n" + "=" * 60)
    print("DOU INGEST SUMMARY")
    print("=" * 60)
    print(f"  ZIPs:         {result.zips_succeeded}/{result.zips_processed} ok, {result.zips_failed} failed")
    print(f"  Documents:    {result.total_documents}")
    print(f"  Media:        {result.total_media}")
    print(f"  Signatures:   {result.total_signatures}")
    print(f"  Norm refs:    {result.total_norm_refs}")
    print(f"  Proc refs:    {result.total_proc_refs}")
    print(
        "  Images:       "
        f"available={result.total_images_available} "
        f"missing={result.total_images_missing} "
        f"unknown={result.total_images_unknown}"
    )
    print(f"  Errors:       {len(result.errors)}")
    print(f"  Time:         {result.elapsed_ms / 1000:.1f}s")
    print("=" * 60)

    return 0 if result.zips_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
