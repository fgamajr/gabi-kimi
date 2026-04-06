from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from src.backend.parsing.contracts import H1ClassificationResult

H1_VERSION: Final[str] = "1.0.0"


@dataclass(frozen=True)
class H1Classification:
    tipo: str | None
    subtipo: str | None
    confidence: float
    method: str
    version: str = H1_VERSION
    status: str = "done"


_RULES: Final[tuple[tuple[str, str, re.Pattern[str]], ...]] = (
    ("NORMATIVO", "LEI", re.compile(r"\blei\s+(?:n[º°\.]?\s*)?\d+", re.IGNORECASE)),
    ("NORMATIVO", "DECRETO", re.compile(r"\bdecreto(?:-lei)?\b", re.IGNORECASE)),
    (
        "NORMATIVO",
        "PORTARIA",
        re.compile(r"\bportaria\s+(?:n[º°\.]?\s*)?\d*", re.IGNORECASE),
    ),
    (
        "NORMATIVO",
        "RESOLUCAO",
        re.compile(r"\bresolu[cç][aã]o\s+(?:n[º°\.]?\s*)?\d*", re.IGNORECASE),
    ),
    (
        "NORMATIVO",
        "INSTRUCAO_NORMATIVA",
        re.compile(r"\binstru[cç][aã]o\s+normativa\b", re.IGNORECASE),
    ),
    (
        "PESSOAL",
        "NOMEACAO",
        re.compile(r"\bnomea[rd]?\b|\bnomear\b|\bnomeia\b", re.IGNORECASE),
    ),
    (
        "PESSOAL",
        "EXONERACAO",
        re.compile(r"\bexoner[ao]\b|\bexonerar\b|\bdispensa\b", re.IGNORECASE),
    ),
    (
        "PESSOAL",
        "DESIGNACAO",
        re.compile(r"\bdesigna(?:r|ç[aã]o)?\b", re.IGNORECASE),
    ),
    (
        "LICITACAO",
        "EDITAL",
        re.compile(r"\bedital\b", re.IGNORECASE),
    ),
    (
        "LICITACAO",
        "AVISO_LICITACAO",
        re.compile(r"\baviso\s+de\s+licita[cç][aã]o\b|\bpreg[aã]o\b", re.IGNORECASE),
    ),
    (
        "LICITACAO",
        "RESULTADO_LICITACAO",
        re.compile(r"\bresultado\s+de\s+julgamento\b|\bhomologa[cç][aã]o\b", re.IGNORECASE),
    ),
    ("AVISO", "COMUNICADO", re.compile(r"\baviso\b|\bcomunicado\b", re.IGNORECASE)),
)


def _concat_context(raw_data: dict[str, object]) -> str:
    fields = (
        str(raw_data.get("identifica") or ""),
        str(raw_data.get("titulo") or ""),
        str(raw_data.get("ementa") or ""),
        str(raw_data.get("texto") or raw_data.get("content_html") or ""),
        str(raw_data.get("art_type_normalized") or raw_data.get("art_type") or ""),
    )
    return "\n".join(x for x in fields if x).strip()


def classify_dou_document(raw_data: dict[str, object]) -> H1Classification:
    text = _concat_context(raw_data)
    if not text:
        return H1Classification(
            tipo=None,
            subtipo=None,
            confidence=0.0,
            method="rule_based",
            status="pending",
        )

    hits: list[tuple[str, str]] = []
    for tipo, subtipo, pattern in _RULES:
        if pattern.search(text):
            hits.append((tipo, subtipo))

    if not hits:
        return H1Classification(
            tipo="OUTROS",
            subtipo="UNKNOWN",
            confidence=0.35,
            method="rule_based",
            status="pending",
        )

    # First matching rule wins, but penalize conflicts.
    tipo, subtipo = hits[0]
    unique_subtypes = {s for _, s in hits}
    if len(unique_subtypes) == 1:
        conf = 0.93
    elif len(unique_subtypes) <= 2:
        conf = 0.78
    else:
        conf = 0.62

    status = "done" if conf >= 0.75 else "pending"
    return H1Classification(
        tipo=tipo,
        subtipo=subtipo,
        confidence=conf,
        method="rule_based",
        status=status,
    )


def as_contract_result(cls: H1Classification) -> H1ClassificationResult:
    return H1ClassificationResult(
        tipo=cls.tipo,
        subtipo=cls.subtipo,
        confidence=cls.confidence,
        method=cls.method,
        version=cls.version,
        status=cls.status,
    )
