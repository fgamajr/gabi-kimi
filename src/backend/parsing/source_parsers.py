from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import html
import re
from typing import Any

from src.backend.parsing.contracts import ParsedDocument, SourceParser
from src.backend.parsing.h1_dou_classifier import as_contract_result, classify_dou_document

_SPACE_RE = re.compile(r"\s+")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return _SPACE_RE.sub(" ", str(value)).strip()


def _to_int(value: Any) -> int | None:
    raw = _norm(value)
    if raw.isdigit():
        return int(raw)
    return None


def _to_date(value: Any) -> str | None:
    raw = _norm(value)
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _sha256_text(*parts: str) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sections_to_xml(sections: dict[str, str]) -> tuple[str, dict[str, Any]]:
    out: list[str] = []
    section_map: dict[str, Any] = {}
    cursor = 0
    for tag, raw in sections.items():
        txt = _norm(raw)
        if not txt:
            continue
        norm_tag = re.sub(r"[^a-z0-9_]+", "_", tag.lower())
        chunk = f"<{norm_tag}>{html.escape(txt)}</{norm_tag}>"
        out.append(chunk)
        section_map[norm_tag] = {"start": cursor, "len": len(chunk)}
        cursor += len(chunk) + 1
    return "\n".join(out), section_map


@dataclass(frozen=True)
class GenericSourceParser(SourceParser):
    source_type: str
    parser_version: str = "1.0.0"

    def parse(self, raw_id: str, raw_data: dict[str, Any]) -> ParsedDocument:
        structured, sections = self._parse_source(raw_data)
        body_tagged_xml, section_map = _sections_to_xml(sections)
        content_hash = _sha256_text(raw_id, body_tagged_xml, repr(structured))
        h1 = None
        if self.source_type == "dou_documents":
            h1 = as_contract_result(classify_dou_document(raw_data))
            structured["h1_tipo"] = h1.tipo
            structured["h1_subtipo"] = h1.subtipo
            structured["h1_confidence"] = h1.confidence
            structured["h1_status"] = h1.status
        return ParsedDocument(
            raw_id=raw_id,
            source_type=self.source_type,
            parser_version=self.parser_version,
            content_hash=content_hash,
            structured_fields=structured,
            sections=sections,
            body_tagged_xml=body_tagged_xml,
            section_map=section_map,
            h1=h1,
        )

    def extract_tags(self, text: str, raw_data: dict[str, Any]) -> dict[str, str]:
        _, sections = self._parse_source(raw_data)
        return sections

    def build_enrichment_prompt(self, parsed: ParsedDocument, prompt_version: str) -> str:
        return (
            f"prompt_version={prompt_version}\n"
            f"source_type={parsed.source_type}\n"
            "Extraia spans semânticos e resumo em JSON válido.\n"
            "Sem texto fora de JSON."
        )

    def _parse_source(self, raw_data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        if self.source_type == "dou_documents":
            return self._parse_dou(raw_data)
        if self.source_type == "tcu_acordao_completo":
            return self._parse_tcu_acordao(raw_data)
        if self.source_type == "tcu_jurisprudencia_selecionada":
            return self._parse_tcu_jurisprudencia(raw_data)
        if self.source_type == "tcu_resposta_consulta":
            return self._parse_tcu_resposta(raw_data)
        if self.source_type == "tcu_sumula":
            return self._parse_tcu_sumula(raw_data)
        if self.source_type == "tcu_boletim_jurisprudencia":
            return self._parse_tcu_boletim_juris(raw_data)
        if self.source_type == "tcu_boletim_pessoal":
            return self._parse_tcu_boletim_pessoal(raw_data)
        if self.source_type == "tcu_boletim_informativo_lc":
            return self._parse_tcu_boletim_lc(raw_data)
        if self.source_type == "tcu_normas":
            return self._parse_tcu_normas(raw_data)
        if self.source_type == "tcu_btcu":
            return self._parse_tcu_btcu(raw_data)
        if self.source_type == "tcu_publicacoes":
            return self._parse_tcu_publicacoes(raw_data)
        return {}, {}

    def _parse_dou(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {
            "pub_date": _to_date(row.get("pub_date")),
            "section": _norm(row.get("section_normalized") or row.get("section")),
            "art_type": _norm(row.get("art_type_normalized") or row.get("art_type")),
            "orgao_emissor": _norm(row.get("issuing_organ") or row.get("orgao")),
            "data_text": _norm(row.get("data_text")),
            "edition": _to_int(row.get("edition")),
            "page": _to_int(row.get("page")),
        }
        sections = {
            "identifica": _norm(row.get("identifica")),
            "ementa": _norm(row.get("ementa")),
            "corpo": _norm(row.get("texto")),
            "fundamento_legal": " ".join(_norm(x) for x in (row.get("references_flat") or [])),
            "vigencia": _norm(row.get("data_text")),
        }
        return structured, sections

    def _parse_tcu_acordao(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {
            "numero_acordao": _to_int(row.get("NUMACORDAO")),
            "ano_acordao": _to_int(row.get("ANOACORDAO")),
            "colegiado": _norm(row.get("COLEGIADO")),
            "tipo_processo": _norm(row.get("TIPOPROCESSO")),
            "data_sessao": _to_date(row.get("DATASESSAO")),
            "relator": _norm(row.get("RELATOR")),
            "numero_processo": _norm(row.get("PROC")),
            "assunto": _norm(row.get("ASSUNTO")),
        }
        sections = {
            "sumario": _norm(row.get("SUMARIO")),
            "relatorio": _norm(row.get("RELATORIO")),
            "voto": _norm(row.get("VOTO")),
            "acordao": _norm(row.get("ACORDAO")),
            "decisao": _norm(row.get("DECISAO")),
        }
        return structured, sections

    def _parse_tcu_jurisprudencia(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {
            "numero_acordao": _to_int(row.get("NUMACORDAO")),
            "ano_acordao": _to_int(row.get("ANOACORDAO")),
            "colegiado": _norm(row.get("COLEGIADO")),
            "data_sessao": _to_date(row.get("DATASESSAOFORMATADA")),
            "area": _norm(row.get("AREA")),
            "tema": _norm(row.get("TEMA")),
            "subtema": _norm(row.get("SUBTEMA")),
        }
        sections = {
            "enunciado": _norm(row.get("ENUNCIADO")),
            "excerto": _norm(row.get("EXCERTO")),
            "referencia_legal": _norm(row.get("REFERENCIALEGAL")),
            "indexacao": _norm(row.get("INDEXACAO")),
        }
        return structured, sections

    def _parse_tcu_resposta(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured, sections = self._parse_tcu_jurisprudencia(row)
        sections["pergunta"] = _norm(row.get("TEMA"))
        sections["resposta"] = _norm(row.get("ENUNCIADO"))
        return structured, sections

    def _parse_tcu_sumula(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {
            "numero": _to_int(row.get("NUMERO")),
            "colegiado": _norm(row.get("COLEGIADO")),
            "area": _norm(row.get("AREA")),
            "tema": _norm(row.get("TEMA")),
            "vigente": _norm(row.get("VIGENTE")).upper() in ("SIM", "S", "TRUE", "1"),
            "data_sessao": _to_date(row.get("DATASESSAOFORMATADA")),
        }
        sections = {
            "enunciado": _norm(row.get("ENUNCIADO")),
            "excerto": _norm(row.get("EXCERTO")),
            "referencia_legal": _norm(row.get("REFERENCIALEGAL")),
        }
        return structured, sections

    def _parse_tcu_boletim_juris(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {"titulo": _norm(row.get("TITULO")), "referencia": _norm(row.get("REFERENCIA"))}
        sections = {
            "titulo": _norm(row.get("TITULO")),
            "enunciado": _norm(row.get("ENUNCIADO")),
            "texto_acordao": _norm(row.get("TEXTOACORDAO")),
        }
        return structured, sections

    def _parse_tcu_boletim_pessoal(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {"titulo": _norm(row.get("TITULO")), "numero": _norm(row.get("NUMERO"))}
        sections = {
            "titulo": _norm(row.get("TITULO")),
            "enunciado": _norm(row.get("ENUNCIADO")),
            "texto_acordao": _norm(row.get("TEXTOACORDAO")),
        }
        return structured, sections

    def _parse_tcu_boletim_lc(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {"titulo": _norm(row.get("TITULO")), "colegiado": _norm(row.get("COLEGIADO"))}
        sections = {
            "titulo": _norm(row.get("TITULO")),
            "enunciado": _norm(row.get("ENUNCIADO")),
            "texto_info": _norm(row.get("TEXTOINFO")),
            "texto_acordao": _norm(row.get("TEXTOACORDAO")),
        }
        return structured, sections

    def _parse_tcu_normas(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {
            "tipo_norma": _norm(row.get("TIPONORMA")),
            "numero_norma": _to_int(row.get("NUMNORMA")),
            "ano_norma": _to_int(row.get("ANONORMA")),
            "data_inicio_vigencia": _to_date(row.get("DATAINICIOVIGENCIA")),
            "data_fim_vigencia": _to_date(row.get("DATAFIMVIGENCIA")),
            "data_dou": _to_date(row.get("DATADOU")),
            "situacao": _norm(row.get("SITUACAO")),
        }
        sections = {
            "titulo": _norm(row.get("TITULO")),
            "assunto": _norm(row.get("ASSUNTO")),
            "texto_norma": _norm(row.get("TEXTONORMA")),
            "texto_anexo": _norm(row.get("TEXTOANEXO")),
            "normas_relacionadas": _norm(row.get("NORMARELACIONADA")),
        }
        return structured, sections

    def _parse_tcu_btcu(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {
            "parent_btcu_id": _norm(row.get("parent_btcu_id")),
            "chunk_sequence": _to_int(row.get("chunk_sequence")),
            "caderno": _norm(row.get("caderno")),
            "data_publicacao": _to_date(row.get("data_publicacao")),
            "section_type": _norm(row.get("section_type")),
        }
        sections = {
            "section_title": _norm(row.get("section_title")),
            "assunto": _norm(row.get("assunto")),
            "texto_completo": _norm(row.get("texto_completo")),
            "acordaos_citados": " ".join(_norm(x) for x in (row.get("acordaos_citados") or [])),
            "base_legal": " ".join(_norm(x) for x in (row.get("normative_references") or [])),
        }
        return structured, sections

    def _parse_tcu_publicacoes(self, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        structured = {
            "slug": _norm(row.get("slug")),
            "pub_type": _norm(row.get("pub_type")),
            "pub_date": _to_date(row.get("pub_date")),
            "page_count": _to_int(row.get("page_count")),
        }
        sections = {
            "title": _norm(row.get("title")),
            "description": _norm(row.get("description")),
            "body_plain": _norm(row.get("body_plain")),
        }
        return structured, sections


SOURCE_TYPES: tuple[str, ...] = (
    "dou_documents",
    "tcu_acordao_completo",
    "tcu_jurisprudencia_selecionada",
    "tcu_resposta_consulta",
    "tcu_sumula",
    "tcu_boletim_jurisprudencia",
    "tcu_boletim_pessoal",
    "tcu_boletim_informativo_lc",
    "tcu_normas",
    "tcu_btcu",
    "tcu_publicacoes",
)

PARSER_REGISTRY: dict[str, SourceParser] = {
    source_type: GenericSourceParser(source_type=source_type) for source_type in SOURCE_TYPES
}
