"""Legal norm query normalization helpers for Brazilian legal search."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("nº", " numero ")
    normalized = normalized.replace("n°", " numero ")
    normalized = normalized.replace(" no ", " numero ")
    normalized = re.sub(r"[^\w\s./-]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _alias_key(value: str) -> str:
    normalized = _fold_text(value)
    normalized = normalized.replace("/", " ")
    normalized = normalized.replace(".", "")
    normalized = normalized.replace("-", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _format_pt_number(digits: str) -> str:
    if not digits or not digits.isdigit():
        return digits
    if len(digits) <= 3:
        return digits
    chunks: list[str] = []
    value = digits
    while value:
        chunks.append(value[-3:])
        value = value[:-3]
    return ".".join(reversed(chunks))


def _coerce_year(value: str | int | None) -> int | None:
    if value is None:
        return None
    year_raw = str(value).strip()
    if not year_raw or not year_raw.isdigit():
        return None
    year_num = int(year_raw)
    if len(year_raw) == 4:
        return year_num
    if len(year_raw) != 2:
        return None
    current_two_digits = datetime.utcnow().year % 100
    century = 2000 if year_num <= current_two_digits + 1 else 1900
    return century + year_num


def _normalize_number(number: str) -> str:
    return re.sub(r"\D+", "", number or "")


@dataclass(frozen=True)
class FamousNorm:
    norm_type: str | None
    number: str
    year: int | None
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class NormQuery:
    norm_type: str | None
    number: str
    number_digits: str
    year: int | None
    aliases: tuple[str, ...]
    matched_alias: str | None = None

    @property
    def year_short(self) -> str | None:
        if self.year is None:
            return None
        return str(self.year)[-2:]

    @property
    def canonical_number(self) -> str:
        return _format_pt_number(self.number_digits) if self.number_digits else self.number

    @property
    def canonical_id(self) -> str:
        parts = [self.norm_type or "norma", self.number_digits or self.number]
        if self.year is not None:
            parts.append(str(self.year))
        return "_".join(part for part in parts if part)

    @property
    def number_variants(self) -> tuple[str, ...]:
        variants: list[str] = []
        bases = [self.number, self.number_digits, self.canonical_number]
        years = [None, str(self.year) if self.year is not None else None, self.year_short]
        seen: set[str] = set()
        for base in bases:
            clean_base = str(base or "").strip()
            if not clean_base:
                continue
            for year in years:
                candidate = clean_base if not year else f"{clean_base}/{year}"
                if candidate not in seen:
                    variants.append(candidate)
                    seen.add(candidate)
        return tuple(variants)

    @property
    def normalized_aliases(self) -> tuple[str, ...]:
        values: list[str] = []
        seen: set[str] = set()
        for alias in self.aliases:
            cleaned = alias.strip()
            if cleaned and cleaned.casefold() not in seen:
                values.append(cleaned)
                seen.add(cleaned.casefold())
        return tuple(values)

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.norm_type,
            "number": self.number_digits or self.number,
            "display_number": self.canonical_number,
            "year": self.year,
            "id": self.canonical_id,
            "aliases": list(self.normalized_aliases),
            "matched_alias": self.matched_alias,
        }


_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\blei\s+complementar\b", re.IGNORECASE), "lei complementar"),
    (re.compile(r"\bmedida\s+provisoria\b", re.IGNORECASE), "medida provisória"),
    (re.compile(r"\bdecreto[\s-]*lei\b", re.IGNORECASE), "decreto-lei"),
    (re.compile(r"\binstrucao\s+normativa\b", re.IGNORECASE), "instrução normativa"),
    (re.compile(r"\bportaria\s+interministerial\b", re.IGNORECASE), "portaria interministerial"),
    (re.compile(r"\bportaria\b", re.IGNORECASE), "portaria"),
    (re.compile(r"\bdecreto\b", re.IGNORECASE), "decreto"),
    (re.compile(r"\blei\b", re.IGNORECASE), "lei"),
    (re.compile(r"\bresolucao\b", re.IGNORECASE), "resolução"),
    (re.compile(r"\bdespacho\b", re.IGNORECASE), "despacho"),
    (re.compile(r"\bedital\b", re.IGNORECASE), "edital"),
)

_NUMBER_WITH_YEAR_RE = re.compile(
    r"\b(?P<number>\d{1,3}(?:[.\-]\d{3})+|\d{2,8})(?:\s*/\s*(?P<year>\d{2,4}))?\b",
    re.IGNORECASE,
)
_SHORT_LAW_RE = re.compile(r"\b(?:l|lei)\s*(?P<number>\d{3,8})(?:\s*/\s*(?P<year>\d{2,4}))?\b", re.IGNORECASE)

_FAMOUS_NORMS: tuple[FamousNorm, ...] = (
    FamousNorm("lei", "9394", 1996, ("ldb", "lei de diretrizes e bases", "lei de diretrizes e bases da educacao")),
    FamousNorm("lei", "13709", 2018, ("lgpd", "lei geral de protecao de dados", "lei geral de protecao de dados pessoais")),
    FamousNorm("lei", "8078", 1990, ("cdc", "codigo de defesa do consumidor", "código de defesa do consumidor")),
    FamousNorm("lei", "8069", 1990, ("eca", "estatuto da crianca e do adolescente", "estatuto da criança e do adolescente")),
    FamousNorm("decreto-lei", "5452", 1943, ("clt", "consolidacao das leis do trabalho", "consolidação das leis do trabalho")),
)

_ALIAS_TO_NORM: dict[str, FamousNorm] = {}
for norm in _FAMOUS_NORMS:
    for alias in norm.aliases:
        _ALIAS_TO_NORM[_alias_key(alias)] = norm


def _detect_type(query: str, inferred_type: str | None) -> str | None:
    if inferred_type:
        return inferred_type
    for pattern, value in _TYPE_PATTERNS:
        if pattern.search(query):
            return value
    return None


def _detect_alias(query: str) -> tuple[FamousNorm | None, str | None]:
    folded = _alias_key(query)
    for alias_key, norm in _ALIAS_TO_NORM.items():
        if folded == alias_key or f" {alias_key} " in f" {folded} ":
            return norm, alias_key
    return None, None


def detect_legal_norm(query: str, *, inferred_type: str | None = None) -> NormQuery | None:
    raw = str(query or "").strip()
    if not raw or raw == "*":
        return None

    folded = _fold_text(raw)
    alias_norm, matched_alias = _detect_alias(folded)
    norm_type = _detect_type(folded, inferred_type) or (alias_norm.norm_type if alias_norm else None)

    match = _NUMBER_WITH_YEAR_RE.search(folded)
    if match is None and (norm_type == "lei" or matched_alias or _SHORT_LAW_RE.search(folded) is not None):
        match = _SHORT_LAW_RE.search(folded)
        if match is not None and norm_type is None:
            norm_type = "lei"
    if match is None and alias_norm is None:
        return None

    number_raw = match.group("number") if match is not None else alias_norm.number  # type: ignore[union-attr]
    year_raw = match.group("year") if match is not None else alias_norm.year  # type: ignore[union-attr]
    number_digits = _normalize_number(number_raw)
    if not number_digits:
        return None

    year = _coerce_year(year_raw)
    if year is None and alias_norm is not None:
        year = alias_norm.year

    aliases: list[str] = []
    if norm_type:
        aliases.extend(
            [
                f"{norm_type} {number_digits}",
                f"{norm_type} {_format_pt_number(number_digits)}",
            ]
        )
        if year is not None:
            aliases.extend(
                [
                    f"{norm_type} {number_digits}/{year}",
                    f"{norm_type} {_format_pt_number(number_digits)}/{year}",
                    f"{norm_type} {number_digits}/{str(year)[-2:]}",
                    f"{norm_type} {_format_pt_number(number_digits)}/{str(year)[-2:]}",
                ]
            )
    aliases.append(number_digits)
    aliases.append(_format_pt_number(number_digits))
    if alias_norm is not None:
        aliases.extend(alias_norm.aliases)

    return NormQuery(
        norm_type=norm_type,
        number=number_raw,
        number_digits=number_digits,
        year=year,
        aliases=tuple(dict.fromkeys(alias.strip() for alias in aliases if alias and alias.strip())),
        matched_alias=matched_alias,
    )
