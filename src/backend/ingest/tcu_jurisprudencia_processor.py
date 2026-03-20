"""TCU Súmulas, Jurisprudência Selecionada, Respostas a Consulta, and Boletins processor.

Parses 6 CSV files from TCU open data into ES-ready documents for
the unified gabi_tcu_acordaos_v1 index, with authority_level field.

CSV format: pipe-delimited (|), quoted fields.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any

_SPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ENRICHMENT_VERSION = 1
_CHAR_LIMIT = 65_536

# URLs
SUMULA_URL = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/sumula/sumula.csv"
JURISPRUDENCIA_URL = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/jurisprudencia-selecionada/jurisprudencia-selecionada.csv"
RESPOSTA_URL = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/resposta-consulta/resposta-consulta.csv"
BOLETIM_JURIS_URL = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/boletim-jurisprudencia/boletim-jurisprudencia.csv"
BOLETIM_PESSOAL_URL = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/boletim-pessoal/boletim-pessoal.csv"
BOLETIM_LC_URL = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/boletim-informativo-lc/boletim-informativo-lc.csv"


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFC", value)
    return _SPACE_RE.sub(" ", text).strip()


def _strip_html(html: str | None) -> str:
    if not html:
        return ""
    text = _HTML_TAG_RE.sub(" ", html)
    return _normalize(text)


def _parse_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _sha256(*parts: str) -> str:
    payload = "|".join(p.lower() for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_search_all(*parts: str) -> str:
    text = _normalize(" ".join(p for p in parts if p))
    return text[:_CHAR_LIMIT]


def sumula_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert a Súmula CSV row to an ES document."""
    now = datetime.now(timezone.utc)
    key = _normalize(row.get("KEY", ""))
    numero = _normalize(row.get("NUMERO", ""))
    enunciado = _strip_html(row.get("ENUNCIADO", ""))
    excerto = _strip_html(row.get("EXCERTO", ""))
    area = _normalize(row.get("AREA", ""))
    tema = _normalize(row.get("TEMA", ""))
    subtema = _normalize(row.get("SUBTEMA", ""))
    colegiado = _normalize(row.get("COLEGIADO", ""))
    vigente = _normalize(row.get("VIGENTE", "")).upper() in ("SIM", "S", "TRUE", "1")
    referencia_legal = _normalize(row.get("REFERENCIALEGAL", ""))
    indexacao = _normalize(row.get("INDEXACAO", ""))
    data_sessao = _parse_date(row.get("DATASESSAOFORMATADA", ""))

    titulo = f"Súmula TCU {numero}" if numero else "Súmula TCU"
    search_all = _build_search_all(titulo, enunciado, excerto, indexacao, referencia_legal, area, tema)

    return {
        "doc_id": key,
        "source_type": "tcu_sumula",
        "authority_level": 3,
        "titulo": titulo,
        "sumario": enunciado[:500],
        "enunciado": enunciado,
        "excerto": excerto,
        "search_all": search_all,
        "area": area or None,
        "tema_tcu_oficial": tema or None,
        "subtema_tcu": subtema or None,
        "colegiado": colegiado or None,
        "vigente": vigente,
        "referencia_legal": referencia_legal or None,
        "indexacao": indexacao or None,
        "data_sessao": data_sessao,
        "tipo": "SÚMULA",
        "tipo_processo": _normalize(row.get("TIPOPROCESSO", "")) or None,
        "source_csv": csv_filename,
        "source_url": f"https://pesquisa.apps.tcu.gov.br/#/sumula/{key.replace('SUMULA-EJURIS-', '')}",
        "indexed_at": now.isoformat(timespec="seconds"),
        "enrichment_version": _ENRICHMENT_VERSION,
        "embedding_status": "pending",
        "deterministic_hash": _sha256(key, enunciado[:200]),
    }


def jurisprudencia_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert a Jurisprudência Selecionada CSV row to an ES document."""
    now = datetime.now(timezone.utc)
    key = _normalize(row.get("KEY", ""))
    num_acordao = _normalize(row.get("NUMACORDAO", ""))
    ano_acordao = _normalize(row.get("ANOACORDAO", ""))
    colegiado = _normalize(row.get("COLEGIADO", ""))
    enunciado = _strip_html(row.get("ENUNCIADO", ""))
    excerto = _strip_html(row.get("EXCERTO", ""))
    area = _normalize(row.get("AREA", ""))
    tema = _normalize(row.get("TEMA", ""))
    subtema = _normalize(row.get("SUBTEMA", ""))
    referencia_legal = _normalize(row.get("REFERENCIALEGAL", ""))
    indexacao = _normalize(row.get("INDEXACAO", ""))
    data_sessao = _parse_date(row.get("DATASESSAOFORMATADA", ""))
    paradigmatico = _normalize(row.get("PARADIGMATICO", "")).upper() in ("SIM", "S", "TRUE", "1")
    autor_tese = _normalize(row.get("AUTORTESE", ""))

    titulo = f"Tese TCU — Acórdão {num_acordao}/{ano_acordao} - {colegiado}" if num_acordao else "Tese TCU"
    search_all = _build_search_all(titulo, enunciado, excerto, indexacao, referencia_legal, area, tema)

    return {
        "doc_id": key,
        "source_type": "tcu_jurisprudencia",
        "authority_level": 2,
        "titulo": titulo,
        "sumario": enunciado[:500],
        "enunciado": enunciado,
        "excerto": excerto,
        "search_all": search_all,
        "area": area or None,
        "tema_tcu_oficial": tema or None,
        "subtema_tcu": subtema or None,
        "colegiado": colegiado or None,
        "referencia_legal": referencia_legal or None,
        "indexacao": indexacao or None,
        "data_sessao": data_sessao,
        "paradigmatico": paradigmatico,
        "relator": autor_tese or None,
        "numero_acordao": int(num_acordao) if num_acordao.isdigit() else None,
        "ano_acordao": int(ano_acordao) if ano_acordao.isdigit() else None,
        "tipo": "JURISPRUDÊNCIA SELECIONADA",
        "tipo_processo": _normalize(row.get("TIPOPROCESSO", "")) or None,
        "parent_acordao_key": f"ACORDAO-COMPLETO-{key.replace('JURISPRUDENCIA-SELECIONADA-', '')}" if key.startswith("JURISPRUDENCIA-SELECIONADA-") else None,
        "source_csv": csv_filename,
        "indexed_at": now.isoformat(timespec="seconds"),
        "enrichment_version": _ENRICHMENT_VERSION,
        "embedding_status": "pending",
        "deterministic_hash": _sha256(key, enunciado[:200]),
    }


def resposta_consulta_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert a Resposta a Consulta CSV row to an ES document."""
    now = datetime.now(timezone.utc)
    key = _normalize(row.get("KEY", ""))
    num_acordao = _normalize(row.get("NUMACORDAO", ""))
    ano_acordao = _normalize(row.get("ANOACORDAO", ""))
    colegiado = _normalize(row.get("COLEGIADO", ""))
    enunciado = _strip_html(row.get("ENUNCIADO", ""))
    excerto = _strip_html(row.get("EXCERTO", ""))
    area = _normalize(row.get("AREA", ""))
    tema = _normalize(row.get("TEMA", ""))
    subtema = _normalize(row.get("SUBTEMA", ""))
    referencia_legal = _normalize(row.get("REFERENCIALEGAL", ""))
    indexacao = _normalize(row.get("INDEXACAO", ""))
    data_sessao = _parse_date(row.get("DATASESSAOFORMATADA", ""))
    autor_tese = _normalize(row.get("AUTORTESE", ""))

    titulo = f"Resposta a Consulta — Acórdão {num_acordao}/{ano_acordao} - {colegiado}" if num_acordao else "Resposta a Consulta TCU"
    search_all = _build_search_all(titulo, enunciado, excerto, indexacao, referencia_legal, area, tema)

    return {
        "doc_id": key,
        "source_type": "tcu_resposta_consulta",
        "authority_level": 1,
        "titulo": titulo,
        "sumario": enunciado[:500],
        "enunciado": enunciado,
        "excerto": excerto,
        "search_all": search_all,
        "area": area or None,
        "tema_tcu_oficial": tema or None,
        "subtema_tcu": subtema or None,
        "colegiado": colegiado or None,
        "referencia_legal": referencia_legal or None,
        "indexacao": indexacao or None,
        "data_sessao": data_sessao,
        "relator": autor_tese or None,
        "numero_acordao": int(num_acordao) if num_acordao.isdigit() else None,
        "ano_acordao": int(ano_acordao) if ano_acordao.isdigit() else None,
        "tipo": "RESPOSTA A CONSULTA",
        "tipo_processo": _normalize(row.get("TIPOPROCESSO", "")) or None,
        "parent_acordao_key": f"ACORDAO-COMPLETO-{key.replace('JURISPRUDENCIA-SELECIONADA-', '')}" if "JURISPRUDENCIA-SELECIONADA-" in key else None,
        "source_csv": csv_filename,
        "indexed_at": now.isoformat(timespec="seconds"),
        "enrichment_version": _ENRICHMENT_VERSION,
        "embedding_status": "pending",
        "deterministic_hash": _sha256(key, enunciado[:200]),
    }


def enunciado_hash(enunciado: str) -> str:
    """Hash normalized enunciado for deduplication."""
    normalized = re.sub(r"\s+", " ", _strip_html(enunciado).lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _boletim_base(row: dict[str, str], csv_filename: str, source_type: str) -> dict[str, Any]:
    """Shared logic for all 3 boletim types."""
    now = datetime.now(timezone.utc)
    key = _normalize(row.get("KEY", ""))
    titulo = _normalize(row.get("TITULO", ""))
    enunciado = _strip_html(row.get("ENUNCIADO", ""))
    excerto = _strip_html(row.get("TEXTOACORDAO", "") or row.get("TEXTOINFO", ""))
    referencia = _normalize(row.get("REFERENCIA", ""))
    colegiado = _normalize(row.get("COLEGIADO", ""))

    search_all = _build_search_all(titulo, enunciado, excerto, referencia)

    return {
        "doc_id": key,
        "source_type": source_type,
        "authority_level": 1,
        "titulo": titulo,
        "sumario": enunciado[:500],
        "enunciado": enunciado,
        "excerto": excerto,
        "search_all": search_all,
        "colegiado": colegiado or None,
        "tipo": "BOLETIM",
        "data_sessao": None,
        "source_csv": csv_filename,
        "indexed_at": now.isoformat(timespec="seconds"),
        "enrichment_version": _ENRICHMENT_VERSION,
        "embedding_status": "pending",
        "deterministic_hash": _sha256(key, enunciado[:200]),
        "_enunciado_hash": enunciado_hash(enunciado),
    }


def boletim_juris_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert Boletim de Jurisprudência row to ES doc."""
    return _boletim_base(row, csv_filename, "tcu_boletim_jurisprudencia")


def boletim_pessoal_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert Boletim de Pessoal row to ES doc."""
    return _boletim_base(row, csv_filename, "tcu_boletim_pessoal")


def boletim_lc_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert Boletim de Licitações e Contratos row to ES doc."""
    return _boletim_base(row, csv_filename, "tcu_boletim_lc")


def iter_csv_rows(filepath: str):
    """Iterate over CSV rows as dicts. Handles TCU's pipe-delimited format."""
    csv.field_size_limit(sys.maxsize)
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|", quotechar='"')
        for row in reader:
            yield row
