from __future__ import annotations

import hashlib
import html
import io
import logging
import os
from pathlib import Path
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from lxml import etree

from src.backend.data.models.document import (
    DouDocument,
    Metadata,
    NormativeReference,
    ProcedureReference,
    Reference,
    Signature,
    StructuredData,
)
from src.backend.ingest.field_extractors import (
    extract_document_number,
    extract_normative_references,
    extract_procedure_references,
    extract_signatures_precise,
    infer_issuing_organ,
    is_generic_organ_bucket,
    normalize_art_type,
    normalize_keyword,
    normalize_text,
    split_organization_path,
    strip_html,
)
from src.backend.ingest.reconstruction import (
    ParsedArticle,
    ReconstructedArticle,
    canonical_source_url,
    group_and_merge_articles,
    is_index_document,
    merge_page_fragments,
    split_blob_reconstructed,
)


logger = logging.getLogger(__name__)

_ATTR_LEAKED_TAG_RE = re.compile(r"</\w+>(?=\")")
_SIGNATURE_PLACEHOLDER_RE = re.compile(r"^\(?\s*of\.\s*el\..*\)?$", re.IGNORECASE)
_MONTH_SECTION_MAP = {
    "DO1": "do1",
    "DO1E": "do1e",
    "DO2": "do2",
    "DO2E": "do2e",
    "DO3": "do3",
    "DO3E": "do3e",
}


class DouProcessor:
    def __init__(self) -> None:
        self.parser = etree.XMLParser(recover=True, encoding="utf-8")

    def parse_date(self, date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str.strip(), "%d/%m/%Y")
        except ValueError:
            logger.warning("Failed to parse date: %s", date_str)
            return None

    def _extract_text(self, element: Any) -> str:
        if element is None:
            return ""
        return "".join(element.itertext()).strip()

    def _sanitize_xml(self, xml_content: bytes) -> tuple[str, bool]:
        decoded = xml_content.decode("utf-8-sig", errors="replace")
        if "</Identifica>" not in decoded[:800]:
            return decoded, False
        sanitized = _ATTR_LEAKED_TAG_RE.sub("", decoded)
        return sanitized, sanitized != decoded

    def _parse_article(self, xml_content: bytes, filename: str) -> tuple[ParsedArticle | None, list[str], bool]:
        warnings: list[str] = []
        xml_text, was_sanitized = self._sanitize_xml(xml_content)
        try:
            root = etree.fromstring(xml_text.encode("utf-8"), parser=self.parser)
        except Exception as exc:
            logger.error("Error parsing %s: %s", filename, exc)
            return None, [f"parse_error:{exc}"], was_sanitized

        article = root.find(".//article")
        if article is None and root.tag == "article":
            article = root
        if article is None:
            return None, ["missing_article"], was_sanitized

        body = article.find("body")
        if body is None:
            return None, ["missing_body"], was_sanitized

        texto_elem = body.find("Texto")
        texto_html = ""
        if texto_elem is not None:
            raw_html = etree.tostring(texto_elem, encoding="unicode", method="html")
            texto_html = html.unescape(raw_html)
            texto_html = re.sub(r"^<Texto[^>]*>", "", texto_html).strip()
            texto_html = re.sub(r"</Texto>$", "", texto_html).strip()

        parsed = ParsedArticle(
            source_xml_path=filename,
            raw_id=article.get("id", ""),
            id_materia=article.get("idMateria", ""),
            id_oficio=article.get("idOficio", ""),
            xml_name=article.get("name", ""),
            pub_name=article.get("pubName", ""),
            pub_date=article.get("pubDate", ""),
            edition_number=article.get("editionNumber", ""),
            number_page=article.get("numberPage", ""),
            pdf_page=article.get("pdfPage", ""),
            art_type_raw=article.get("artType", ""),
            art_category=article.get("artCategory", ""),
            art_class_raw=article.get("artClass", ""),
            art_size=article.get("artSize", ""),
            art_notes=article.get("artNotes", ""),
            highlight_type=article.get("highlightType", ""),
            highlight_priority=article.get("highlightPriority", ""),
            highlight=article.get("highlight", ""),
            highlight_image=article.get("highlightimage", ""),
            highlight_image_name=article.get("highlightimagename", ""),
            identifica=self._extract_text(body.find("Identifica")),
            data_text=self._extract_text(body.find("Data")),
            ementa=self._extract_text(body.find("Ementa")),
            titulo=self._extract_text(body.find("Titulo")),
            sub_titulo=self._extract_text(body.find("SubTitulo")),
            texto_html=texto_html,
        )
        if was_sanitized:
            warnings.append("xml_sanitized")
        return parsed, warnings, was_sanitized

    def _parse_zip_articles(self, zip_bytes: bytes, zip_filename: str, extract_to: str | None) -> tuple[list[ParsedArticle], dict[str, list[str]], dict[str, bool]]:
        parsed_articles: list[ParsedArticle] = []
        warnings_by_file: dict[str, list[str]] = {}
        sanitized_by_file: dict[str, bool] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            if extract_to:
                zip_name_no_ext = os.path.splitext(zip_filename)[0]
                target_dir = os.path.join(extract_to, zip_name_no_ext)
                os.makedirs(target_dir, exist_ok=True)
                archive.extractall(target_dir)
                logger.info("Extracted %s to %s", zip_filename, target_dir)

            for filename in sorted(archive.namelist()):
                if not filename.lower().endswith(".xml"):
                    continue
                with archive.open(filename) as handle:
                    article, warnings, was_sanitized = self._parse_article(handle.read(), filename)
                warnings_by_file[filename] = warnings
                sanitized_by_file[filename] = was_sanitized
                if article:
                    parsed_articles.append(article)
        return parsed_articles, warnings_by_file, sanitized_by_file

    def _section_normalized(self, pub_name: str | None) -> str | None:
        if not pub_name:
            return None
        return _MONTH_SECTION_MAP.get(pub_name, normalize_keyword(pub_name))

    def _organization_path(self, art_category: str | None) -> list[str]:
        return split_organization_path(art_category)

    def _art_class_hierarchy(self, art_class_raw: str | None) -> list[str]:
        if not art_class_raw:
            return []
        return [part for part in art_class_raw.split(":") if part and part != "00000"]

    def _canonicalize_content(self, text: str) -> str:
        out = normalize_text(text)
        out = re.sub(r"(?im)^\s*di[aá]rio oficial da uni[aã]o.*$", "", out)
        out = re.sub(r"\s+", " ", out).strip()
        return out

    def _sha256(self, *parts: str) -> str:
        payload = "|".join(normalize_keyword(part) for part in parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _build_structured_data(self, article: ParsedArticle, pub_date: datetime | None, signatures: list[Signature]) -> StructuredData:
        act_number, act_year = extract_document_number(article.identifica)
        if act_year is None and pub_date is not None:
            act_year = pub_date.year
        primary_signer = self._primary_signer(signatures)
        return StructuredData(act_number=act_number, act_year=act_year, signer=primary_signer)

    def _legacy_references(self, normative_refs: list[NormativeReference]) -> list[Reference]:
        refs: list[Reference] = []
        for item in normative_refs:
            ref_type = "cita"
            if item.is_revocation:
                ref_type = "revoga"
            elif item.is_amendment:
                ref_type = "altera"
            refs.append(Reference(type=ref_type, target=item.reference_full or item.reference_number))
        return refs

    def _build_signatures(self, html_content: str) -> list[Signature]:
        signatures: list[Signature] = []
        for match in extract_signatures_precise(html_content):
            person_name = normalize_text(match.person_name)
            signatures.append(
                Signature(
                    person_name=person_name,
                    role_title=match.role_title,
                    sequence=match.sequence,
                    person_name_normalized=normalize_keyword(person_name),
                    role_title_normalized=normalize_keyword(match.role_title) or None,
                    is_placeholder=bool(_SIGNATURE_PLACEHOLDER_RE.match(person_name)),
                    extraction_source=match.extraction_source,
                )
            )
        return signatures

    def _primary_signer(self, signatures: list[Signature]) -> str | None:
        for signature in signatures:
            if not signature.is_placeholder and signature.person_name:
                return signature.person_name
        return None

    def _searchable_signers(self, signatures: list[Signature]) -> list[str]:
        return [signature.person_name for signature in signatures if signature.person_name and not signature.is_placeholder]

    def _build_quality_score(self, article: ParsedArticle, body_text: str, signatures: list[Signature], normative_refs: list[NormativeReference]) -> float:
        checks = [
            bool(article.identifica),
            bool(body_text),
            bool(article.pub_date),
            bool(article.pub_name),
            bool(article.art_type_raw),
            bool(signatures),
            bool(normative_refs),
        ]
        return round(sum(1 for ok in checks if ok) / len(checks), 4)

    def _build_search_all(
        self,
        article: ParsedArticle,
        body_text: str,
        references_flat: list[str],
        signatures: list[Signature],
        affected_entities: list[str],
    ) -> str:
        parts = [
            article.identifica,
            article.ementa,
            article.titulo,
            article.sub_titulo,
            body_text,
            " ".join(references_flat),
            " ".join(self._searchable_signers(signatures)),
            " ".join(affected_entities),
        ]
        return normalize_text(" ".join(part for part in parts if part))

    def _build_logical_doc_id(self, reconstructed: ReconstructedArticle, article: ParsedArticle, body_text: str) -> str:
        if article.id_materia:
            return article.id_materia
        title_seed = normalize_keyword(article.identifica)[:80]
        return self._sha256(
            article.pub_date,
            article.pub_name,
            article.art_type_raw,
            title_seed,
            str(reconstructed.part_count),
            body_text[:200],
        )[:32]

    def _build_document(
        self,
        reconstructed: ReconstructedArticle,
        zip_filename: str,
        warnings_by_file: dict[str, list[str]],
        sanitized_by_file: dict[str, bool],
    ) -> DouDocument | None:
        article = reconstructed.article
        pub_date = self.parse_date(article.pub_date)
        if pub_date is None:
            logger.error("Missing or invalid pubDate in reconstructed article %s", article.source_xml_path)
            return None

        body_text = strip_html(article.texto_html)
        canonical_body = self._canonicalize_content(body_text)
        section_normalized = self._section_normalized(article.pub_name)
        art_type_normalized = normalize_art_type(article.art_type_raw)
        issuing_organ = infer_issuing_organ(
            article.art_category,
            body_text=canonical_body,
            identifica=article.identifica,
            ementa=article.ementa,
        )
        organization_path = self._organization_path(article.art_category)
        art_class_hierarchy = self._art_class_hierarchy(article.art_class_raw)
        source_url = canonical_source_url(article.pdf_page)
        signatures = self._build_signatures(article.texto_html)
        searchable_signers = self._searchable_signers(signatures)
        primary_signer = self._primary_signer(signatures)

        normative_ref_models = [
            NormativeReference(
                reference_type=item.reference_type,
                reference_number=item.reference_number,
                reference_text=item.reference_text,
                reference_full=item.reference_full,
                reference_year=item.reference_year,
                reference_date=item.reference_date,
                issuing_body=item.issuing_body,
            )
            for item in extract_normative_references(canonical_body)
        ]
        procedure_ref_models = [
            ProcedureReference(
                procedure_type=item.procedure_type,
                procedure_identifier=item.procedure_identifier,
                procedure_year=item.procedure_year,
                procedure_body=item.procedure_body,
            )
            for item in extract_procedure_references(canonical_body)
        ]
        references_flat = [
            item.reference_full or f"{item.reference_type} {item.reference_number}"
            for item in normative_ref_models
        ]
        affected_entities = sorted(
            {
                entity
                for entity in [issuing_organ, *organization_path]
                if entity and not is_generic_organ_bucket(entity)
            }
        )
        search_all = self._build_search_all(article, canonical_body, references_flat, signatures, affected_entities)
        structured = self._build_structured_data(article, pub_date, signatures)
        logical_doc_id = self._build_logical_doc_id(reconstructed, article, canonical_body)
        natural_key_hash = self._sha256(
            art_type_normalized,
            structured.act_number or "",
            str(structured.act_year or ""),
            issuing_organ,
        )
        content_hash = self._sha256(canonical_body)
        edition_id = self._sha256(article.pub_date, article.edition_number, section_normalized or "")
        occurrence_hash = self._sha256(edition_id, article.number_page, source_url or "")
        parse_quality_score = self._build_quality_score(article, canonical_body, signatures, normative_ref_models)
        extraction_warnings = sorted(
            {
                warning
                for path in reconstructed.merged_from_xml_paths
                for warning in warnings_by_file.get(path, [])
            }
        )
        was_sanitized = any(sanitized_by_file.get(path, False) for path in reconstructed.merged_from_xml_paths)
        normalized_title = normalize_keyword(article.identifica or article.titulo)
        published_at = pub_date.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        doc = DouDocument(
            _id=logical_doc_id,
            source_id=article.source_xml_path,
            source_zip=zip_filename,
            source_type="liferay",
            source_xml_path=article.source_xml_path,
            source_url=source_url,
            raw_id=article.raw_id or None,
            id_materia=article.id_materia or None,
            id_oficio=article.id_oficio or None,
            xml_name=article.xml_name or None,
            logical_doc_id=logical_doc_id,
            pub_date=pub_date,
            section=article.pub_name or "",
            section_code=article.pub_name or None,
            section_normalized=section_normalized,
            edition=article.edition_number or None,
            edition_id=edition_id,
            edition_date=published_at,
            edition_type="extra" if normalize_keyword(article.art_notes) == "extra" else "regular",
            page=int(article.number_page) if article.number_page.isdigit() else None,
            art_type=article.art_type_raw or None,
            art_type_raw=article.art_type_raw or None,
            art_type_normalized=art_type_normalized or None,
            art_category=article.art_category or None,
            art_class_raw=article.art_class_raw or None,
            art_class_hierarchy=art_class_hierarchy,
            art_notes=article.art_notes or None,
            pub_name=article.pub_name or None,
            orgao=issuing_organ or None,
            organization_path=organization_path,
            organization_path_string="/".join(organization_path) if organization_path else None,
            issuing_organ=issuing_organ or None,
            pdf_page=article.pdf_page or None,
            identifica=article.identifica or None,
            ementa=article.ementa or None,
            texto=canonical_body,
            data_text=article.data_text or None,
            content_html=article.texto_html or None,
            titulo=article.titulo or None,
            sub_titulo=article.sub_titulo or None,
            normalized_title=normalized_title or None,
            search_all=search_all or None,
            text_language="pt-BR",
            structured=structured,
            references=self._legacy_references(normative_ref_models),
            normative_references=normative_ref_models,
            procedure_references=procedure_ref_models,
            affected_entities=affected_entities,
            affected_entities_normalized=[normalize_keyword(entity) for entity in affected_entities],
            signatures=signatures,
            primary_signer=primary_signer,
            primary_signer_normalized=normalize_keyword(primary_signer) or None,
            signers_all_flat=searchable_signers,
            signature_count=len(signatures),
            has_multiple_signers=len(signatures) > 1,
            references_flat=references_flat,
            reference_types=sorted({item.reference_type for item in normative_ref_models}),
            reference_count=len(normative_ref_models),
            has_images=False,
            image_count=0,
            is_multipart=reconstructed.is_multipart,
            multipart_seq=reconstructed.multipart_seq,
            multipart_index=reconstructed.multipart_seq,
            part_count=reconstructed.part_count,
            merged_from_xml_paths=reconstructed.merged_from_xml_paths,
            was_page_fragment_merged=reconstructed.was_page_fragment_merged,
            was_blob_split=reconstructed.was_blob_split,
            split_segment_index=reconstructed.split_segment_index,
            reconstruction_status=reconstructed.reconstruction_status,
            reconstruction_notes=reconstructed.reconstruction_notes or [],
            natural_key_hash=natural_key_hash,
            content_hash=content_hash,
            occurrence_hash=occurrence_hash,
            identity_strategy="logical_doc_v2",
            parse_quality_score=parse_quality_score,
            parse_errors=[],
            extraction_method="zip_reconstruction_v2",
            reconstruction_confidence=1.0 if not reconstructed.was_page_fragment_merged else 0.95,
            is_extra_edition=normalize_keyword(article.art_notes) == "extra",
            is_retification="retifica" in normalize_keyword(article.identifica),
            is_revocation="revoga" in canonical_body.lower(),
            was_sanitized=was_sanitized,
            sanitization_reason="xml_leaked_tag" if was_sanitized else None,
            is_tombstone=False,
            metadata=Metadata(
                origin_file=article.source_xml_path,
                processing_version="v3.0-p0",
                parser_version="zip-reconstruction-v2",
                normalizer_version="field-contract-v2",
                extraction_warnings=extraction_warnings,
                validation_errors=[],
                was_sanitized=was_sanitized,
                sanitization_reason="xml_leaked_tag" if was_sanitized else None,
            ),
            published_at=published_at,
            indexed_at=now,
            updated_at=now,
        )
        return doc

    def process_xml(self, xml_content: bytes, filename: str, zip_filename: str) -> DouDocument | None:
        article, warnings, sanitized = self._parse_article(xml_content, filename)
        if article is None:
            return None
        reconstructed = ReconstructedArticle(
            article=article,
            logical_doc_id_seed=article.id_materia or Path(filename).stem,
            merged_from_xml_paths=[filename],
            is_multipart=False,
            multipart_seq=0,
            part_count=1,
            reconstruction_notes=[],
        )
        return self._build_document(
            reconstructed,
            zip_filename,
            warnings_by_file={filename: warnings},
            sanitized_by_file={filename: sanitized},
        )

    def process_zip(self, zip_bytes: bytes, zip_filename: str, extract_to: str | None = None) -> list[DouDocument]:
        documents: list[DouDocument] = []
        try:
            parsed_articles, warnings_by_file, sanitized_by_file = self._parse_zip_articles(
                zip_bytes,
                zip_filename,
                extract_to,
            )
            reconstructed = group_and_merge_articles(parsed_articles)
            reconstructed = merge_page_fragments(reconstructed)
            filtered: list[ReconstructedArticle] = []
            for item in reconstructed:
                if is_index_document(item.article):
                    logger.info("Skipping index document %s", item.article.source_xml_path)
                    continue
                split_items = split_blob_reconstructed(item)
                if len(split_items) > 1:
                    for idx, split_item in enumerate(split_items, 1):
                        filtered.append(
                            ReconstructedArticle(
                                article=split_item.article,
                                logical_doc_id_seed=split_item.logical_doc_id_seed,
                                merged_from_xml_paths=split_item.merged_from_xml_paths,
                                is_multipart=split_item.is_multipart,
                                multipart_seq=idx,
                                part_count=split_item.part_count,
                                was_page_fragment_merged=split_item.was_page_fragment_merged,
                                was_blob_split=True,
                                split_segment_index=split_item.split_segment_index,
                                reconstruction_status=split_item.reconstruction_status,
                                reconstruction_notes=split_item.reconstruction_notes,
                            )
                        )
                else:
                    filtered.append(item)

            for item in filtered:
                document = self._build_document(item, zip_filename, warnings_by_file, sanitized_by_file)
                if document:
                    documents.append(document)
        except zipfile.BadZipFile:
            logger.error("Bad ZIP file: %s", zip_filename)
        except Exception as exc:
            logger.error("Error processing ZIP %s: %s", zip_filename, exc)
        return documents
