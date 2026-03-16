"""Structured field extractors for DOU HTML/text content."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(slots=True)
class SignatureMatch:
    person_name: str
    role_title: str | None
    sequence: int
    extraction_source: str


@dataclass(slots=True)
class NormativeReferenceMatch:
    reference_type: str
    reference_number: str
    reference_text: str
    reference_year: int | None = None
    reference_date: str | None = None
    reference_full: str | None = None
    issuing_body: str | None = None


@dataclass(slots=True)
class ProcedureReferenceMatch:
    procedure_type: str
    procedure_identifier: str
    procedure_year: int | None = None
    procedure_body: str | None = None


_SPACE_RE = re.compile(r"\s+")

_GENERIC_ORGAN_BUCKETS = {
    "atos do poder executivo",
    "atos do poder legislativo",
    "atos do poder judiciário",
    "atos do congresso nacional",
    "poder executivo",
    "poder legislativo",
    "poder judiciário",
    "presidência da república/secretaria especial",
    "ineditoriais",
}

_PRESIDENCY_CUE_RE = re.compile(
    r"\bpresidente da rep[úu]blica\b|\bpresid[êe]ncia da rep[úu]blica\b",
    re.IGNORECASE,
)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFC", value)
    return _SPACE_RE.sub(" ", text).strip()


def normalize_keyword(value: str | None) -> str:
    return normalize_text(value).lower()


def is_generic_organ_bucket(value: str | None) -> bool:
    return normalize_keyword(value) in _GENERIC_ORGAN_BUCKETS


def split_organization_path(art_category: str | None) -> list[str]:
    if not art_category:
        return []

    merged: list[str] = []
    for raw_part in art_category.split("/"):
        part = normalize_text(raw_part)
        if not part:
            continue
        if merged and merged[-1].endswith(","):
            merged[-1] = normalize_text(f"{merged[-1]} {part}")
            continue
        merged.append(part)
    return merged


def strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return normalize_text(text)


def normalize_art_type(art_type: str | None) -> str:
    value = normalize_keyword(art_type)
    mapping = {
        "portarias": "portaria",
        "despachos": "despacho",
        "avisos": "aviso",
        "atos": "ato",
        "extratos": "extrato",
    }
    return mapping.get(value, value)


def infer_issuing_organ(
    art_category: str | None,
    *,
    body_text: str | None = None,
    identifica: str | None = None,
    ementa: str | None = None,
) -> str:
    parts = split_organization_path(art_category)
    if not parts:
        haystack = normalize_text(" ".join(part for part in [identifica, ementa, body_text] if part))
        if _PRESIDENCY_CUE_RE.search(haystack):
            return "Presidência da República"
        return ""

    # Prefer the most specific non-generic authority, keeping umbrella buckets
    # in organization_path/art_category instead of exposing them as issuing_organ.
    for part in reversed(parts):
        if not is_generic_organ_bucket(part):
            return part

    haystack = normalize_text(" ".join(part for part in [identifica, ementa, body_text] if part))
    if _PRESIDENCY_CUE_RE.search(haystack):
        return "Presidência da República"

    # If the available category is only an umbrella bucket, it is safer to
    # leave issuing_organ empty than to store a wrong concrete authority.
    return ""


def extract_issuing_organ(art_category: str | None) -> str:
    return infer_issuing_organ(art_category)


def extract_document_number(identifica: str | None) -> tuple[str | None, int | None]:
    if not identifica:
        return None, None
    number_match = re.search(r"[Nn][º°.o]\s*([\d][\d.,/\-]*)", identifica)
    year_match = re.search(r"\b((?:19|20)\d{2})\b", identifica)
    number = number_match.group(1).strip().rstrip(",.") if number_match else None
    year = int(year_match.group(1)) if year_match else None
    return number, year


def extract_signatures_precise(html: str) -> list[SignatureMatch]:
    if not html:
        return []
    pattern = re.compile(
        r"""<p\s+class=['"]([^'"]*\b(?:assina|cargo)\b[^'"]*)['"][^>]*>(.*?)</p>""",
        re.IGNORECASE | re.DOTALL,
    )
    events: list[tuple[str, str]] = []
    for match in pattern.finditer(html):
        cls_str = match.group(1).lower()
        event_type = "assina" if "assina" in cls_str else "cargo"
        raw = match.group(2)
        if event_type == "assina" and re.search(r"<br\s*/?\s*>", raw, re.IGNORECASE):
            parts = re.split(r"<br\s*/?\s*>", raw, maxsplit=1)
            name = strip_html(parts[0])
            role = strip_html(parts[1]) if len(parts) > 1 else ""
            if name:
                events.append(("assina", name))
            if role:
                events.append(("cargo", role))
            continue
        text = strip_html(raw)
        if text:
            events.append((event_type, text))

    signatures: list[SignatureMatch] = []
    sequence = 0
    index = 0
    while index < len(events):
        event_type, text = events[index]
        if event_type != "assina":
            index += 1
            continue
        sequence += 1
        role = None
        if index + 1 < len(events) and events[index + 1][0] == "cargo":
            role = events[index + 1][1]
            index += 2
        else:
            index += 1
        signatures.append(
            SignatureMatch(
                person_name=text,
                role_title=role,
                sequence=sequence,
                extraction_source="html_assina",
            )
        )
    return signatures


_NORM_REF_TYPES = {
    "lei complementar": "lei_complementar",
    "lei": "lei",
    "decreto-lei": "decreto_lei",
    "decreto": "decreto",
    "resolução": "resolucao",
    "portaria": "portaria",
    "instrução normativa": "instrucao_normativa",
    "deliberação": "deliberacao",
    "medida provisória": "medida_provisoria",
    "emenda constitucional": "emenda_constitucional",
    "súmula": "sumula",
}
_NORM_REF_TYPE_PATTERN = "|".join(re.escape(key) for key in sorted(_NORM_REF_TYPES, key=len, reverse=True))
_NORM_REF_RE = re.compile(
    rf"""
    (?P<type>{_NORM_REF_TYPE_PATTERN})
    (?:\s+(?P<qualifier>(?:Interministerial|Conjunta|Complementar|Executivo|Executiva)(?:\s+[A-Z][A-Za-z/]+)?))?
    (?:\s+(?P<body>[A-Z][A-Za-z/]+))?
    \s+[Nn][º°.]\s*
    (?P<number>\d[\d./\-]*)
    (?:
        ,?\s+de\s+
        (?P<date>\d{{1,2}}[º°]?\s+de\s+\w+\s+de\s+\d{{4}})
    )?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_normative_references(text: str) -> list[NormativeReferenceMatch]:
    if not text:
        return []
    refs: list[NormativeReferenceMatch] = []
    seen: set[str] = set()
    for match in _NORM_REF_RE.finditer(text):
        ref_type_raw = normalize_keyword(match.group("type"))
        ref_type = _NORM_REF_TYPES.get(ref_type_raw, ref_type_raw)
        number = normalize_text(match.group("number")).rstrip(",.")
        date_str = normalize_text(match.group("date") or "") or None
        full_text = normalize_text(match.group(0))
        dedup_key = f"{ref_type}|{number}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        qualifier = normalize_text(match.group("qualifier") or "")
        body = normalize_text(match.group("body") or "")
        issuing_body = None
        if qualifier:
            parts = qualifier.split()
            if len(parts) > 1:
                issuing_body = parts[-1]
        elif body:
            issuing_body = body
        year_match = re.search(r"\b((?:19|20)\d{2})\b", number)
        year = int(year_match.group(1)) if year_match else None
        refs.append(
            NormativeReferenceMatch(
                reference_type=ref_type,
                reference_number=number,
                reference_text=full_text,
                reference_year=year,
                reference_date=date_str,
                reference_full=f"{ref_type} {number}",
                issuing_body=issuing_body,
            )
        )
    return refs


_PROC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("processo_etico", re.compile(r"Processo\s+[ÉE]tico\s+[Nn][º°]?\s*:?\s*([\d./\-]+)", re.IGNORECASE)),
    ("processo_sei", re.compile(r"Processo\s+SEI\s+[Nn]?[º°]?\s*:?\s*([\d./\-]+)", re.IGNORECASE)),
    ("processo_administrativo", re.compile(r"Processo\s+(?:Administrativo\s+)?[Nn][º°]\s*:?\s*([\d./\-]+)", re.IGNORECASE)),
    ("proad", re.compile(r"PROAD\s+[Nn][º°]\s*([\d./\-]+)", re.IGNORECASE)),
]


def extract_procedure_references(text: str) -> list[ProcedureReferenceMatch]:
    if not text:
        return []
    refs: list[ProcedureReferenceMatch] = []
    seen: set[str] = set()
    for procedure_type, pattern in _PROC_PATTERNS:
        for match in pattern.finditer(text):
            identifier = normalize_text(match.group(1)).rstrip(",.")
            if identifier in seen:
                continue
            seen.add(identifier)
            refs.append(
                ProcedureReferenceMatch(
                    procedure_type=procedure_type,
                    procedure_identifier=identifier,
                )
            )
    return refs
