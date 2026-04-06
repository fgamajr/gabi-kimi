"""Catalog of TCU CSV sources that feed colunar raw.*_raw Postgres tables.

Out of scope (scraping / non-CSV): tcu_btcu, tcu_publicacoes — keep existing scrape → JSONB pipelines.

Normas use norma.csv (CSV). All URLs are TCU dados abertos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.backend.ingest.tcu_jurisprudencia_processor import (
    BOLETIM_JURIS_URL,
    BOLETIM_LC_URL,
    BOLETIM_PESSOAL_URL,
    JURISPRUDENCIA_URL,
    RESPOSTA_URL,
    SUMULA_URL,
)
from src.backend.ingest.tcu_normas_processor import NORMA_URL
from src.backend.ingest.tcu_processor import CSV_COLUMNS

TCU_ACORDAO_CSV_URL_TEMPLATE: Final[str] = (
    "https://sites.tcu.gov.br/dados-abertos/jurisprudencia"
    "/arquivos/acordao-completo/acordao-completo-{year}.csv"
)

# Approximate expected row counts (parity checks) — see ops/migrations/source_separate_raw.py
EXPECTED_ROW_COUNTS: Final[dict[str, int]] = {
    "raw.tcu_acordao_completo_raw": 520_353,
    "raw.tcu_jurisprudencia_selecionada_raw": 17_549,
    "raw.tcu_resposta_consulta_raw": 523,
    "raw.tcu_sumula_raw": 294,
    "raw.tcu_boletim_jurisprudencia_raw": 5_837,
    "raw.tcu_boletim_pessoal_raw": 1_500,
    "raw.tcu_boletim_informativo_lc_raw": 1_977,
    "raw.tcu_normas_raw": 16_443,
}

# Headers from live TCU CSVs — validate_csv_headers uses set equality; TCU drift → update catalog.
_JURISPRUDENCIA_HEADERS: Final[tuple[str, ...]] = (
    "KEY",
    "NUMACORDAO",
    "ANOACORDAO",
    "COLEGIADO",
    "AREA",
    "TEMA",
    "SUBTEMA",
    "ENUNCIADO",
    "EXCERTO",
    "NUMSUMULA",
    "DATASESSAOFORMATADA",
    "AUTORTESE",
    "FUNCAOAUTORTESE",
    "TIPOPROCESSO",
    "TIPORECURSO",
    "INDEXACAO",
    "INDEXADORESCONSOLIDADOS",
    "PARAGRAFOLC",
    "REFERENCIALEGAL",
    "PUBLICACAOAPRESENTACAO",
    "PARADIGMATICO",
)

_RESPOSTA_HEADERS: Final[tuple[str, ...]] = (
    "KEY",
    "NUMACORDAO",
    "ANOACORDAO",
    "COLEGIADO",
    "NUMACORDAOFORMATADO",
    "AREA",
    "TEMA",
    "SUBTEMA",
    "ENUNCIADO",
    "EXCERTO",
    "DATASESSAOFORMATADA",
    "AUTORTESE",
    "FUNCAOAUTORTESE",
    "TIPOPROCESSO",
    "TIPORECURSO",
    "INDEXACAO",
    "INDEXADORESCONSOLIDADOS",
    "PARAGRAFOLC",
    "REFERENCIALEGAL",
    "PUBLICACAOAPRESENTACAO",
)

_SUMULA_HEADERS: Final[tuple[str, ...]] = (
    "KEY",
    "NUMERO",
    "ENUNCIADO",
    "TIPOPROCESSO",
    "AREA",
    "TEMA",
    "SUBTEMA",
    "APROVACAO",
    "NUMAPROVACAO",
    "ANOAPROVACAO",
    "COLEGIADO",
    "FUNCAOAUTORTESE",
    "AUTORTESE",
    "INDEXACAO",
    "VIGENTE",
    "DATASESSAOFORMATADA",
    "EXCERTO",
    "REFERENCIALEGAL",
    "INDEXADORESCONSOLIDADOS",
    "PUBLICACAO",
)

_BOLETIM_JURIS_HEADERS: Final[tuple[str, ...]] = (
    "KEY",
    "TITULO",
    "ENUNCIADO",
    "REFERENCIA",
    "TEXTOACORDAO",
)

_BOLETIM_PESSOAL_HEADERS: Final[tuple[str, ...]] = (
    "KEY",
    "TITULO",
    "ENUNCIADO",
    "NUMERO",
    "REFERENCIA",
    "TEXTOACORDAO",
)

_BOLETIM_LC_HEADERS: Final[tuple[str, ...]] = (
    "KEY",
    "TITULO",
    "COLEGIADO",
    "TEXTOACORDAO",
    "ENUNCIADO",
    "NUMERO",
    "TEXTOINFO",
)

_NORMA_HEADERS: Final[tuple[str, ...]] = (
    "KEY",
    "UNIDADEBASICAAUTORA",
    "ORIGEM",
    "NUMNORMA",
    "ANONORMA",
    "TIPONORMA",
    "NUMEROPROCESSO",
    "NUMEROPROCESSOFORMATADO",
    "TITULO",
    "ASSUNTO",
    "TEXTONORMA",
    "DATAINICIOVIGENCIA",
    "DATAFIMVIGENCIA",
    "SITUACAO",
    "LINKBTCU",
    "TEXTOANEXO",
    "ARQUIVONORMA",
    "PAGINABTCU",
    "TEMA",
    "TAGSVCE",
    "NORMARELACIONADA",
    "NUMDOU",
    "NUMSECAODOU",
    "NUMPAGINADOU",
    "DATADOU",
    "INFOSGERAIS",
)


@dataclass(frozen=True)
class TcuCsvRawSource:
    """One TCU CSV open-data feed → one raw Postgres table."""

    name: str
    table: str
    source_type: str
    url: str | None
    url_template_year: bool
    csv_columns: tuple[str, ...]


def acordao_url(year: int) -> str:
    return TCU_ACORDAO_CSV_URL_TEMPLATE.format(year=year)


TCU_CSV_RAW_SOURCES: Final[tuple[TcuCsvRawSource, ...]] = (
    TcuCsvRawSource(
        name="acordao_completo",
        table="raw.tcu_acordao_completo_raw",
        source_type="tcu_acordao_completo",
        url=None,
        url_template_year=True,
        csv_columns=tuple(CSV_COLUMNS),
    ),
    TcuCsvRawSource(
        name="jurisprudencia_selecionada",
        table="raw.tcu_jurisprudencia_selecionada_raw",
        source_type="tcu_jurisprudencia_selecionada",
        url=JURISPRUDENCIA_URL,
        url_template_year=False,
        csv_columns=_JURISPRUDENCIA_HEADERS,
    ),
    TcuCsvRawSource(
        name="resposta_consulta",
        table="raw.tcu_resposta_consulta_raw",
        source_type="tcu_resposta_consulta",
        url=RESPOSTA_URL,
        url_template_year=False,
        csv_columns=_RESPOSTA_HEADERS,
    ),
    TcuCsvRawSource(
        name="sumula",
        table="raw.tcu_sumula_raw",
        source_type="tcu_sumula",
        url=SUMULA_URL,
        url_template_year=False,
        csv_columns=_SUMULA_HEADERS,
    ),
    TcuCsvRawSource(
        name="boletim_jurisprudencia",
        table="raw.tcu_boletim_jurisprudencia_raw",
        source_type="tcu_boletim_jurisprudencia",
        url=BOLETIM_JURIS_URL,
        url_template_year=False,
        csv_columns=_BOLETIM_JURIS_HEADERS,
    ),
    TcuCsvRawSource(
        name="boletim_pessoal",
        table="raw.tcu_boletim_pessoal_raw",
        source_type="tcu_boletim_pessoal",
        url=BOLETIM_PESSOAL_URL,
        url_template_year=False,
        csv_columns=_BOLETIM_PESSOAL_HEADERS,
    ),
    TcuCsvRawSource(
        name="boletim_informativo_lc",
        table="raw.tcu_boletim_informativo_lc_raw",
        source_type="tcu_boletim_informativo_lc",
        url=BOLETIM_LC_URL,
        url_template_year=False,
        csv_columns=_BOLETIM_LC_HEADERS,
    ),
    TcuCsvRawSource(
        name="norma",
        table="raw.tcu_normas_raw",
        source_type="tcu_normas",
        url=NORMA_URL,
        url_template_year=False,
        csv_columns=_NORMA_HEADERS,
    ),
)


def source_by_name(name: str) -> TcuCsvRawSource:
    for s in TCU_CSV_RAW_SOURCES:
        if s.name == name:
            return s
    names = ", ".join(x.name for x in TCU_CSV_RAW_SOURCES)
    raise KeyError(f"unknown source {name!r}; choose one of: {names}")
