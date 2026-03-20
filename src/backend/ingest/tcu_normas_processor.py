"""TCU Normas processor — CSV row → ES document for gabi_tcu_normas_v1.

Handles Portarias, Resoluções, Instruções Normativas, etc. do TCU.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any

NORMA_URL = "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv"

_SPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ENRICHMENT_VERSION = 1
_CHAR_LIMIT = 65_536
_BODY_LIMIT = 500_000


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
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _sha256(*parts: str) -> str:
    payload = "|".join(p.lower() for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def norma_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert a Norma CSV row to an ES document."""
    now = datetime.now(timezone.utc)
    key = _normalize(row.get("KEY", ""))
    tipo_norma = _normalize(row.get("TIPONORMA", ""))
    num_norma = _normalize(row.get("NUMNORMA", ""))
    ano_norma = _normalize(row.get("ANONORMA", ""))
    titulo = _normalize(row.get("TITULO", ""))
    assunto = _strip_html(row.get("ASSUNTO", ""))
    texto_norma = _strip_html(row.get("TEXTONORMA", ""))[:_BODY_LIMIT]
    texto_anexo = _strip_html(row.get("TEXTOANEXO", ""))[:_BODY_LIMIT]
    situacao = _normalize(row.get("SITUACAO", ""))
    vigente = situacao.lower() in ("vigente", "em vigor", "vigente com alteração")
    origem = _normalize(row.get("ORIGEM", "")).strip("[]")
    unidade_autora = _normalize(row.get("UNIDADEBASICAAUTORA", "")).strip("[]")
    numero_processo = _normalize(row.get("NUMEROPROCESSOFORMATADO", "") or row.get("NUMEROPROCESSO", ""))
    link_btcu = _normalize(row.get("LINKBTCU", ""))
    tema = _normalize(row.get("TEMA", ""))
    norma_relacionada = _normalize(row.get("NORMARELACIONADA", ""))
    num_dou = _normalize(row.get("NUMDOU", ""))
    secao_dou = _normalize(row.get("NUMSECAODOU", ""))
    pagina_dou = _normalize(row.get("NUMPAGINADOU", ""))
    data_dou = _parse_date(row.get("DATADOU", ""))
    data_inicio = _parse_date(row.get("DATAINICIOVIGENCIA", ""))
    data_fim = _parse_date(row.get("DATAFIMVIGENCIA", ""))

    search_all = _normalize(" ".join(p for p in [titulo, assunto, texto_norma[:_CHAR_LIMIT], tema] if p))[:_CHAR_LIMIT]

    return {
        "doc_id": key,
        "source_type": "tcu_norma",
        "authority_level": 2 if vigente else 0,
        "tipo_norma": tipo_norma or None,
        "numero_norma": int(num_norma) if num_norma.isdigit() else None,
        "ano_norma": int(ano_norma) if ano_norma.isdigit() else None,
        "titulo": titulo or None,
        "assunto": assunto or None,
        "texto_norma": texto_norma or None,
        "texto_anexo": texto_anexo or None,
        "search_all": search_all or None,
        "situacao": situacao or None,
        "vigente": vigente,
        "data_inicio_vigencia": data_inicio,
        "data_fim_vigencia": data_fim,
        "origem": origem or None,
        "unidade_autora": unidade_autora or None,
        "numero_processo": numero_processo or None,
        "link_btcu": link_btcu or None,
        "tema": tema or None,
        "norma_relacionada": norma_relacionada or None,
        "num_dou": num_dou or None,
        "secao_dou": secao_dou or None,
        "pagina_dou": pagina_dou or None,
        "data_dou": data_dou,
        "source_csv": csv_filename,
        "indexed_at": now.isoformat(timespec="seconds"),
        "embedding_status": "pending",
        "deterministic_hash": _sha256(key, titulo or "", assunto or ""),
    }


def iter_csv_rows(filepath: str):
    csv.field_size_limit(sys.maxsize)
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|", quotechar='"')
        for row in reader:
            yield row
