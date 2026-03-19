"""TCU Acórdão processor — CSV row → enriched ES document.

Parses CSV rows from TCU open data (acordao-completo-YYYY.csv), strips HTML,
extracts derived fields (dispositivo_tipo, normative_references, temas, etc.),
and produces ES-ready documents for gabi_tcu_acordaos_v1.

CSV format: pipe-delimited (|), quoted fields, 33 columns.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from src.backend.ingest.field_extractors import extract_normative_references

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "KEY", "TIPO", "TITULO", "NUMACORDAO", "ANOACORDAO", "NUMATA",
    "COLEGIADO", "DATASESSAO", "RELATOR", "SITUACAO", "PROC",
    "ACORDAOSRELACIONADOS", "TIPOPROCESSO", "INTERESSADOS", "ENTIDADE",
    "RELATORDELIBERACAORECORRIDA", "MINISTROREVISOR",
    "MINISTROAUTORVOTOVENCEDOR", "REPRESENTANTEMP", "UNIDADETECNICA",
    "ADVOGADO", "ASSUNTO", "SUMARIO", "ACORDAO", "DECISAO", "QUORUM",
    "MINISTROALEGOUIMPEDIMENTOSESSAO", "RECURSOS", "RELATORIO", "VOTO",
    "DECLARACAOVOTO", "VOTOCOMPLEMENTAR", "VOTOMINISTROREVISOR",
]

ENRICHMENT_VERSION = 1

_SEARCH_ALL_LIMIT = 65_536
_BODY_TEXT_LIMIT = 500_000  # 500KB per text field for ES
_SPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# ---------------------------------------------------------------------------
# Dispositivo extraction patterns (high value)
# ---------------------------------------------------------------------------

DISPOSITION_PATTERNS: dict[str, re.Pattern[str]] = {
    "regular": re.compile(r"julgar\s+regulares?\b", re.IGNORECASE),
    "regular_com_ressalva": re.compile(r"julgar\s+regulares?\s+com\s+ressalvas?", re.IGNORECASE),
    "irregular": re.compile(r"julgar\s+irregulares?\b", re.IGNORECASE),
    "aplicar_multa": re.compile(r"aplicar\s+(?:a\s+)?multa", re.IGNORECASE),
    "imputar_debito": re.compile(r"imputar\s+(?:o\s+)?d[eé]bito", re.IGNORECASE),
    "determinar": re.compile(r"\bdeterminar\b(?:\s+(?:ao|[àa]\s))", re.IGNORECASE),
    "recomendar": re.compile(r"\brecomendar\b", re.IGNORECASE),
    "dar_ciencia": re.compile(r"dar\s+ci[eê]ncia\b", re.IGNORECASE),
    "arquivar": re.compile(r"\barquivar\b", re.IGNORECASE),
    "inabilitar": re.compile(r"\binabilitar\b", re.IGNORECASE),
    "declarar_inidoneidade": re.compile(r"declarar\s+(?:a\s+)?inidon[eê]", re.IGNORECASE),
}

# Severity order for dispositivo_resumo (most severe first)
_DISPOSITION_SEVERITY = [
    "declarar_inidoneidade", "inabilitar", "irregular", "imputar_debito",
    "aplicar_multa", "regular_com_ressalva", "regular", "determinar",
    "recomendar", "dar_ciencia", "arquivar",
]

# ---------------------------------------------------------------------------
# TCU tema classification
# ---------------------------------------------------------------------------

_TEMA_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "licitacao": [
        re.compile(r"\blicita[çc][aã]o\b", re.IGNORECASE),
        re.compile(r"\bpreg[aã]o\b", re.IGNORECASE),
        re.compile(r"\bconcorr[eê]ncia\b", re.IGNORECASE),
        re.compile(r"\blei\s+(?:n[°º.]?\s*)?(?:8\.?666|14\.?133)\b", re.IGNORECASE),
    ],
    "pessoal": [
        re.compile(r"\bpessoal\b", re.IGNORECASE),
        re.compile(r"\baposentadoria\b", re.IGNORECASE),
        re.compile(r"\bpens[aã]o\b", re.IGNORECASE),
        re.compile(r"\badmiss[aã]o\b", re.IGNORECASE),
        re.compile(r"\bconcurso\s+p[uú]blico\b", re.IGNORECASE),
    ],
    "convenio": [
        re.compile(r"\bconv[eê]nio\b", re.IGNORECASE),
        re.compile(r"\btransfer[eê]ncia\s+volunt[aá]ria\b", re.IGNORECASE),
        re.compile(r"\bsiconv\b", re.IGNORECASE),
    ],
    "obra_publica": [
        re.compile(r"\bobra\b", re.IGNORECASE),
        re.compile(r"\bconstru[çc][aã]o\b", re.IGNORECASE),
        re.compile(r"\bfiscobras\b", re.IGNORECASE),
    ],
    "desestatizacao": [
        re.compile(r"\bdesestatiza[çc][aã]o\b", re.IGNORECASE),
        re.compile(r"\bconcess[aã]o\b", re.IGNORECASE),
        re.compile(r"\bprivatiza[çc][aã]o\b", re.IGNORECASE),
    ],
    "saude": [
        re.compile(r"\bsa[uú]de\b", re.IGNORECASE),
        re.compile(r"\bSUS\b"),
        re.compile(r"\bhospital\b", re.IGNORECASE),
    ],
    "educacao": [
        re.compile(r"\beduca[çc][aã]o\b", re.IGNORECASE),
        re.compile(r"\bensino\b", re.IGNORECASE),
        re.compile(r"\bFUNDEB\b", re.IGNORECASE),
    ],
    "meio_ambiente": [
        re.compile(r"\bmeio\s+ambiente\b", re.IGNORECASE),
        re.compile(r"\bambiental\b", re.IGNORECASE),
        re.compile(r"\bIBAMA\b", re.IGNORECASE),
    ],
    "previdencia": [
        re.compile(r"\bprevid[eê]ncia\b", re.IGNORECASE),
        re.compile(r"\bINSS\b"),
        re.compile(r"\bprevidenci[aá]rio\b", re.IGNORECASE),
    ],
    "defesa": [
        re.compile(r"\bdefesa\b", re.IGNORECASE),
        re.compile(r"\bmilitar\b", re.IGNORECASE),
        re.compile(r"\bfor[çc]as\s+armadas\b", re.IGNORECASE),
    ],
}

# Acórdão citation pattern
_ACORDAO_CITATION_RE = re.compile(
    r"Ac[oó]rd[aã]o\s+(?:n[°º.]?\s*)?(\d+)/(\d{4})\s*[-–]\s*(Plen[aá]rio|Primeira\s+C[aâ]mara|Segunda\s+C[aâ]mara)",
    re.IGNORECASE,
)

# Also extract from XML-like tags if present
_ACORDAO_TAG_RE = re.compile(
    r"<acordao_decisao_tcu[^>]*>.*?</acordao_decisao_tcu>",
    re.IGNORECASE | re.DOTALL,
)

# Monetary value pattern
_VALOR_RE = re.compile(r"R\$\s*([\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})?)(?!\d)")

# Recurso type patterns
_RECURSO_PATTERNS: dict[str, re.Pattern[str]] = {
    "pedido_reexame": re.compile(r"pedido\s+de\s+reexame", re.IGNORECASE),
    "recurso_reconsideracao": re.compile(r"recurso\s+de\s+reconsidera[çc][aã]o", re.IGNORECASE),
    "recurso_revisao": re.compile(r"recurso\s+de\s+revis[aã]o", re.IGNORECASE),
    "embargos_declaracao": re.compile(r"embargos?\s+de\s+declara[çc][aã]o", re.IGNORECASE),
    "agravo": re.compile(r"\bagravo\b", re.IGNORECASE),
}

# Common organs
_ORGAO_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bMinistério da Saúde\b", re.IGNORECASE), "Ministério da Saúde"),
    (re.compile(r"\bMinistério da Educação\b", re.IGNORECASE), "Ministério da Educação"),
    (re.compile(r"\bMinistério da Defesa\b", re.IGNORECASE), "Ministério da Defesa"),
    (re.compile(r"\bMinistério da Fazenda\b", re.IGNORECASE), "Ministério da Fazenda"),
    (re.compile(r"\bPetrobras\b", re.IGNORECASE), "Petrobras"),
    (re.compile(r"\bBanco do Brasil\b", re.IGNORECASE), "Banco do Brasil"),
    (re.compile(r"\bCaixa Econômica\b", re.IGNORECASE), "Caixa Econômica Federal"),
    (re.compile(r"\bBNDES\b"), "BNDES"),
    (re.compile(r"\bDNIT\b"), "DNIT"),
    (re.compile(r"\bFUNASA\b"), "FUNASA"),
    (re.compile(r"\bANVISA\b"), "ANVISA"),
    (re.compile(r"\bANATEL\b"), "ANATEL"),
    (re.compile(r"\bANEEL\b"), "ANEEL"),
    (re.compile(r"\bINCRA\b"), "INCRA"),
    (re.compile(r"\bINSS\b"), "INSS"),
    (re.compile(r"\bIBAMA\b"), "IBAMA"),
    (re.compile(r"\bFNDE\b"), "FNDE"),
    (re.compile(r"\bSUS\b"), "SUS"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFC", value)
    return _SPACE_RE.sub(" ", text).strip()


def _strip_html(html: str) -> str:
    if not html:
        return ""
    # Extract info from custom XML tags before stripping
    text = _HTML_TAG_RE.sub(" ", html)
    return _normalize(text)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _parse_date(date_str: str) -> str | None:
    """Parse DD/MM/YYYY to ISO YYYY-MM-DD."""
    date_str = date_str.strip()
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float_br(value: str) -> float | None:
    """Parse Brazilian number format: 1.234,56 → 1234.56."""
    cleaned = value.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _sha256(*parts: str) -> str:
    payload = "|".join(p.lower() for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _colegiado_abbrev(colegiado: str) -> str:
    """Abbreviate colegiado for acordao_id."""
    c = colegiado.strip().lower()
    if "plenário" in c or "plenario" in c:
        return "Plenário"
    if "primeira" in c:
        return "1ª Câmara"
    if "segunda" in c:
        return "2ª Câmara"
    return colegiado.strip()


# ---------------------------------------------------------------------------
# Derived field extractors
# ---------------------------------------------------------------------------

def extract_dispositivo_tipo(text: str) -> list[str]:
    """Extract disposition types from acordao/decisao text."""
    found: list[str] = []
    for name, pattern in DISPOSITION_PATTERNS.items():
        if pattern.search(text):
            found.append(name)
    # regular_com_ressalva is more specific — remove plain "regular" if both present
    if "regular_com_ressalva" in found and "regular" in found:
        found.remove("regular")
    return found


def extract_dispositivo_resumo(tipos: list[str]) -> str | None:
    """Pick the most severe disposition type as the summary."""
    for severity in _DISPOSITION_SEVERITY:
        if severity in tipos:
            return severity
    return tipos[0] if tipos else None


def extract_acordaos_citados(text: str) -> list[str]:
    """Extract cited acórdãos from text."""
    seen: set[str] = set()
    results: list[str] = []

    # From XML tags
    for tag_match in _ACORDAO_TAG_RE.finditer(text):
        tag_text = tag_match.group(0)
        for m in _ACORDAO_CITATION_RE.finditer(tag_text):
            ref = f"Acórdão {m.group(1)}/{m.group(2)}-{m.group(3)}"
            key = ref.lower()
            if key not in seen:
                seen.add(key)
                results.append(ref)

    # From plain text
    for m in _ACORDAO_CITATION_RE.finditer(text):
        ref = f"Acórdão {m.group(1)}/{m.group(2)}-{m.group(3)}"
        key = ref.lower()
        if key not in seen:
            seen.add(key)
            results.append(ref)

    return results


def extract_valores_monetarios(text: str) -> tuple[list[str], float | None]:
    """Extract monetary values and max value."""
    valores: list[str] = []
    max_val: float | None = None
    for m in _VALOR_RE.finditer(text):
        raw = m.group(1)
        valores.append(f"R$ {raw}")
        parsed = _parse_float_br(raw)
        if parsed is not None:
            if max_val is None or parsed > max_val:
                max_val = parsed
    return valores[:50], max_val  # cap at 50


def classify_temas(text: str, assunto: str, tipo_processo: str) -> tuple[list[str], str | None]:
    """Classify into TCU topic categories."""
    haystack = f"{assunto} {tipo_processo} {text[:2000]}"
    temas: list[str] = []
    for tema, patterns in _TEMA_PATTERNS.items():
        if any(p.search(haystack) for p in patterns):
            temas.append(tema)
    primary = temas[0] if temas else None
    return temas, primary


def extract_orgaos_citados(text: str) -> list[str]:
    """Extract mentioned government organs."""
    seen: set[str] = set()
    results: list[str] = []
    sample = text[:10000]  # cap for performance
    for pattern, name in _ORGAO_PATTERNS:
        if pattern.search(sample) and name not in seen:
            seen.add(name)
            results.append(name)
    return results


def classify_recurso(tipo_processo: str, recursos: str) -> tuple[bool, str | None]:
    """Determine if this is a recurso and its type."""
    haystack = f"{tipo_processo} {recursos}"
    for tipo, pattern in _RECURSO_PATTERNS.items():
        if pattern.search(haystack):
            return True, tipo
    if recursos.strip():
        return True, None
    return False, None


def split_entidade(entidade: str) -> list[str]:
    """Split semicolon-separated entity list."""
    if not entidade:
        return []
    return [_normalize(e) for e in entidade.split(";") if _normalize(e)]


def count_interessados(interessados: str) -> int:
    """Count number of interested parties."""
    if not interessados.strip():
        return 0
    # Split by semicolons or period-separated entries
    parts = re.split(r"[;.]", interessados)
    return sum(1 for p in parts if _normalize(p))


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

def csv_row_to_es_doc(row: dict[str, str], csv_filename: str) -> dict[str, Any]:
    """Convert a single CSV row to an ES-ready document."""
    now = datetime.now(timezone.utc)

    # --- Direct fields ---
    key = _normalize(row.get("KEY", ""))
    titulo = _normalize(row.get("TITULO", ""))
    numero_acordao = _parse_int(row.get("NUMACORDAO", ""))
    ano_acordao = _parse_int(row.get("ANOACORDAO", ""))
    colegiado = _normalize(row.get("COLEGIADO", ""))
    tipo = _normalize(row.get("TIPO", ""))
    tipo_processo_raw = _normalize(row.get("TIPOPROCESSO", ""))
    # Extract just the type name without code
    tipo_processo = re.sub(r"\s*\([^)]+\)\s*$", "", tipo_processo_raw).strip()
    situacao = _normalize(row.get("SITUACAO", ""))
    proc = _normalize(row.get("PROC", ""))
    numero_ata = _normalize(row.get("NUMATA", ""))
    data_sessao_raw = _normalize(row.get("DATASESSAO", ""))
    data_sessao = _parse_date(data_sessao_raw)

    relator = _normalize(row.get("RELATOR", ""))
    relator_delib = _normalize(row.get("RELATORDELIBERACAORECORRIDA", ""))
    ministro_revisor = _normalize(row.get("MINISTROREVISOR", ""))
    ministro_voto_vencedor = _normalize(row.get("MINISTROAUTORVOTOVENCEDOR", ""))
    representante_mp = _normalize(row.get("REPRESENTANTEMP", ""))
    unidade_tecnica = _normalize(row.get("UNIDADETECNICA", ""))

    advogados = _normalize(row.get("ADVOGADO", ""))
    interessados = _normalize(row.get("INTERESSADOS", ""))
    entidade = _normalize(row.get("ENTIDADE", ""))
    assunto = _normalize(row.get("ASSUNTO", ""))

    # Text fields — strip HTML and truncate
    sumario = _truncate(_strip_html(row.get("SUMARIO", "")), _BODY_TEXT_LIMIT)
    acordao_texto = _truncate(_strip_html(row.get("ACORDAO", "")), _BODY_TEXT_LIMIT)
    relatorio = _truncate(_strip_html(row.get("RELATORIO", "")), _BODY_TEXT_LIMIT)
    voto = _truncate(_strip_html(row.get("VOTO", "")), _BODY_TEXT_LIMIT)
    decisao = _truncate(_strip_html(row.get("DECISAO", "")), _BODY_TEXT_LIMIT)
    declaracao_voto = _truncate(_strip_html(row.get("DECLARACAOVOTO", "")), _BODY_TEXT_LIMIT)
    voto_complementar = _truncate(_strip_html(row.get("VOTOCOMPLEMENTAR", "")), _BODY_TEXT_LIMIT)
    voto_revisor = _truncate(_strip_html(row.get("VOTOMINISTROREVISOR", "")), _BODY_TEXT_LIMIT)
    quorum = _normalize(row.get("QUORUM", ""))
    recursos = _normalize(row.get("RECURSOS", ""))

    acordaos_relacionados_raw = _normalize(row.get("ACORDAOSRELACIONADOS", ""))
    acordaos_relacionados = [
        _normalize(a) for a in acordaos_relacionados_raw.split(";")
        if _normalize(a)
    ] if acordaos_relacionados_raw else []

    # --- Derived ID ---
    acordao_id = ""
    if numero_acordao is not None and ano_acordao is not None and colegiado:
        acordao_id = f"{numero_acordao}/{ano_acordao}-{_colegiado_abbrev(colegiado)}"

    # --- search_all ---
    search_all_parts = [sumario, acordao_texto, relatorio, voto]
    search_all = _truncate(
        _normalize(" ".join(p for p in search_all_parts if p)),
        _SEARCH_ALL_LIMIT,
    )

    # --- Normative references (reuse DOU extractor) ---
    all_text = f"{sumario} {acordao_texto} {voto} {relatorio}"
    norm_refs = extract_normative_references(all_text)
    normative_references = [
        ref.reference_full or f"{ref.reference_type} {ref.reference_number}"
        for ref in norm_refs
    ]

    # --- Acórdãos citados ---
    # Use raw text (before HTML strip) if available for tag extraction
    raw_all = f"{row.get('ACORDAO', '')} {row.get('VOTO', '')} {row.get('RELATORIO', '')}"
    acordaos_citados = extract_acordaos_citados(raw_all)

    # --- Dispositivo ---
    dispositivo_text = f"{acordao_texto} {decisao}"
    dispositivo_tipo = extract_dispositivo_tipo(dispositivo_text)
    dispositivo_resumo = extract_dispositivo_resumo(dispositivo_tipo)

    # --- Monetary values ---
    valores_monetarios, valor_maximo = extract_valores_monetarios(dispositivo_text)

    # --- Boolean flags ---
    tem_debito = bool(re.search(r"imputar\s+(?:o\s+)?d[eé]bito", dispositivo_text, re.IGNORECASE))
    tem_multa = bool(re.search(r"aplicar\s+(?:a\s+)?multa", dispositivo_text, re.IGNORECASE))

    # --- Temas ---
    temas_tcu, tema_primario = classify_temas(all_text, assunto, tipo_processo)

    # --- Organs cited ---
    orgaos_citados = extract_orgaos_citados(all_text)

    # --- Process flags ---
    is_embargo = "embargo" in tipo_processo.lower()
    is_recurso, tipo_recurso = classify_recurso(tipo_processo, recursos)

    # --- Entity list ---
    entidade_list = split_entidade(entidade)

    # --- Completeness ---
    text_fields = [sumario, acordao_texto, relatorio, voto, decisao, declaracao_voto]
    filled = sum(1 for f in text_fields if f)
    completeness_score = round(filled / len(text_fields), 2) if text_fields else 0.0
    text_length = sum(len(f) for f in text_fields)

    # --- Deterministic hash ---
    deterministic_hash = _sha256(
        key, titulo, acordao_texto[:500], str(numero_acordao), str(ano_acordao),
    )

    # --- Source URL ---
    source_url = (
        f"https://contas.tcu.gov.br/pesquisaJurisprudencia/#/detalhamento/11/"
        f"*/KEY%3A%22{key}%22/DTRELEVANCIA%20desc/false/1/false"
    ) if key else None

    return {
        # Identity
        "doc_id": key,
        "acordao_id": acordao_id or None,
        "deterministic_hash": deterministic_hash,

        # Direct fields
        "titulo": titulo or None,
        "numero_acordao": numero_acordao,
        "ano_acordao": ano_acordao,
        "tipo": tipo or None,
        "colegiado": colegiado or None,
        "tipo_processo": tipo_processo or None,
        "situacao": situacao or None,
        "numero_processo": proc or None,
        "numero_ata": numero_ata or None,
        "data_sessao": data_sessao,

        "relator": relator or None,
        "relator_deliberacao_recorrida": relator_delib or None,
        "ministro_revisor": ministro_revisor or None,
        "ministro_voto_vencedor": ministro_voto_vencedor or None,
        "representante_mp": representante_mp or None,
        "unidade_tecnica": unidade_tecnica or None,

        "advogados": advogados or None,
        "interessados": interessados or None,
        "entidade": entidade or None,
        "entidade_list": entidade_list or None,
        "assunto": assunto or None,

        # Text fields
        "sumario": sumario or None,
        "acordao_texto": acordao_texto or None,
        "relatorio": relatorio or None,
        "voto": voto or None,
        "decisao": decisao or None,
        "declaracao_voto": declaracao_voto or None,
        "voto_complementar": voto_complementar or None,
        "voto_revisor": voto_revisor or None,
        "quorum": quorum or None,
        "acordaos_relacionados": acordaos_relacionados or None,
        "recursos": recursos or None,

        # Concatenated search
        "search_all": search_all or None,

        # Derived: references
        "normative_references": normative_references or None,
        "reference_count": len(normative_references),
        "acordaos_citados": acordaos_citados or None,
        "acordaos_citados_count": len(acordaos_citados),

        # Derived: dispositivo
        "dispositivo_tipo": dispositivo_tipo or None,
        "dispositivo_resumo": dispositivo_resumo,
        "valores_monetarios": valores_monetarios or None,
        "valor_maximo": valor_maximo,
        "tem_debito": tem_debito,
        "tem_multa": tem_multa,

        # Derived: temas
        "temas_tcu": temas_tcu or None,
        "tema_primario": tema_primario,
        "orgaos_citados": orgaos_citados or None,

        # Process flags
        "is_embargo": is_embargo,
        "is_recurso": is_recurso,
        "tipo_recurso": tipo_recurso,

        # Completeness
        "num_interessados": count_interessados(interessados),
        "text_length": text_length,
        "has_relatorio": bool(relatorio),
        "has_voto": bool(voto),
        "completeness_score": completeness_score,

        # System
        "source_type": "tcu_acordao",
        "source_csv": csv_filename,
        "source_url": source_url,
        "indexed_at": now.isoformat(timespec="seconds"),
        "enrichment_version": ENRICHMENT_VERSION,
        "embedding_status": "pending",
    }


def iter_csv_rows(filepath: str):
    """Iterate over CSV rows as dicts. Handles TCU's pipe-delimited format."""
    import sys
    csv.field_size_limit(sys.maxsize)

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|", quotechar='"')
        for row in reader:
            yield row
