from __future__ import annotations

import re
from typing import Any


H2_ENRICHMENT_VERSION = "1.1.0"

TOPIC_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("licitacao", re.compile(r"\blicita[cç][aã]o\b|\bedital\b|\bpreg[aã]o\b|\bconcorr[eê]ncia\b", re.IGNORECASE)),
    ("pessoal", re.compile(r"\bnomea[rd]?\b|\bexonera\b|\bdesigna\b|\bcargo\b", re.IGNORECASE)),
    ("controle_externo", re.compile(r"\bac[oó]rd[aã]o\b|\bcolegiado\b|\brelator\b|\btcu\b", re.IGNORECASE)),
    ("regulacao", re.compile(r"\banvisa\b|\bregistro\b|\bproduto\b|\bmedicamento\b|\bradiof[aá]rmaco\b", re.IGNORECASE)),
    ("normativo", re.compile(r"\bportaria\b|\bresolu[cç][aã]o\b|\blei\b|\bdecreto\b|\binstru[cç][aã]o normativa\b", re.IGNORECASE)),
    ("consulta", re.compile(r"\bconsulta\b|\bresposta\b", re.IGNORECASE)),
    ("jurisprudencia", re.compile(r"\benunciado\b|\bexcerto\b|\bs[uú]mula\b|\bjurisprud[eê]ncia\b", re.IGNORECASE)),
)

LEGAL_REFERENCE_RE = re.compile(
    r"\b(?:Lei|Decreto|Portaria|Resolu[cç][aã]o|Instru[cç][aã]o Normativa)\s*(?:n[º°\.]?\s*)?[\d./-]+",
    re.IGNORECASE,
)
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
ORG_SUFFIX_RE = re.compile(
    r"\b[A-Z][A-Z0-9 .,&/-]{4,}\s(?:LTDA|S/A|SA|EIRELI|ME|MINIST[EÉ]RIO|AG[EÊ]NCIA|TRIBUNAL|SECRETARIA)\b"
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

SOURCE_SCHEMA_KEYS: dict[str, tuple[str, ...]] = {
    "dou_documents": ("tipo_ato", "subtipo_ato", "objeto", "fundamento_legal", "efeito_principal", "vigencia"),
    "tcu_acordao_completo": ("numero", "colegiado", "relator", "tipo_processo", "objeto", "decisao_principal"),
    "tcu_jurisprudencia_selecionada": ("area", "tema", "subtema", "tese_central"),
    "tcu_resposta_consulta": ("area", "tema", "pergunta", "resposta_curta"),
    "tcu_sumula": ("numero", "tema", "tese_central", "vigente"),
    "tcu_boletim_jurisprudencia": ("titulo", "tema", "tese_central"),
    "tcu_boletim_pessoal": ("titulo", "tema", "efeito_administrativo"),
    "tcu_boletim_informativo_lc": ("titulo", "tema", "ponto_principal"),
    "tcu_normas": ("tipo_norma", "numero", "ano", "assunto", "vigencia"),
    "tcu_btcu": ("section_title", "assunto", "base_legal", "decisao_principal"),
    "tcu_publicacoes": ("title", "pub_type", "assunto", "ponto_principal"),
}


def clean_text(value: str | None) -> str:
    text = TAG_RE.sub(" ", value or "")
    return SPACE_RE.sub(" ", text).strip()


def summarize_text(value: str | None, limit: int = 320) -> str:
    return clean_text(value)[:limit]


def fallback_tags(allowed_tags: tuple[str, ...], section_map: dict[str, Any] | None) -> list[str]:
    if not section_map:
        return []
    allowed = set(allowed_tags)
    return [tag for tag in section_map.keys() if tag in allowed]


def derive_topics(source_type: str, text: str, structured: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        [
            source_type,
            clean_text(text),
            " ".join(str(v) for v in structured.values() if v not in (None, "", [], {})),
        ]
    )
    topics: list[str] = []
    for topic, pattern in TOPIC_RULES:
        if pattern.search(haystack):
            topics.append(topic)
    if source_type.startswith("tcu_") and "controle_externo" not in topics:
        topics.append("controle_externo")
    if not topics:
        topics.append("administrativo")
    return topics[:8]


def derive_legal_entities(text: str, structured: dict[str, Any]) -> list[dict[str, str]]:
    cleaned = clean_text(text)
    entities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for key in ("orgao_emissor", "colegiado", "relator", "numero_processo"):
        value = str(structured.get(key) or "").strip()
        if value:
            item = ("campo", value)
            if item not in seen:
                seen.add(item)
                entities.append({"type": key, "value": value})

    for match in CNPJ_RE.findall(cleaned):
        item = ("cnpj", match)
        if item not in seen:
            seen.add(item)
            entities.append({"type": "cnpj", "value": match})

    for match in LEGAL_REFERENCE_RE.findall(cleaned):
        item = ("base_legal", match)
        if item not in seen:
            seen.add(item)
            entities.append({"type": "base_legal", "value": match})

    for match in ORG_SUFFIX_RE.findall(cleaned):
        item = ("organizacao", match)
        if item not in seen:
            seen.add(item)
            entities.append({"type": "organizacao", "value": match})

    return entities[:16]


def build_summary_structured(
    source_type: str,
    text: str,
    structured: dict[str, Any],
    topics: list[str],
    legal_entities: list[dict[str, str]],
) -> dict[str, Any]:
    cleaned = clean_text(text)
    first_sentence = cleaned.split(". ")[0][:220]

    if source_type == "dou_documents":
        return {
            "tipo_ato": structured.get("h1_tipo") or structured.get("art_type"),
            "subtipo_ato": structured.get("h1_subtipo") or structured.get("art_type"),
            "objeto": first_sentence,
            "fundamento_legal": [x["value"] for x in legal_entities if x["type"] == "base_legal"][:6],
            "efeito_principal": first_sentence,
            "vigencia": structured.get("data_text") or structured.get("pub_date"),
        }
    if source_type == "tcu_acordao_completo":
        return {
            "numero": structured.get("numero_acordao"),
            "colegiado": structured.get("colegiado"),
            "relator": structured.get("relator"),
            "tipo_processo": structured.get("tipo_processo"),
            "objeto": structured.get("assunto") or first_sentence,
            "decisao_principal": first_sentence,
        }
    if source_type == "tcu_jurisprudencia_selecionada":
        return {
            "area": structured.get("area"),
            "tema": structured.get("tema"),
            "subtema": structured.get("subtema"),
            "tese_central": first_sentence,
        }
    if source_type == "tcu_resposta_consulta":
        return {
            "area": structured.get("area"),
            "tema": structured.get("tema"),
            "pergunta": structured.get("tema"),
            "resposta_curta": first_sentence,
        }
    if source_type == "tcu_sumula":
        return {
            "numero": structured.get("numero"),
            "tema": structured.get("tema"),
            "tese_central": first_sentence,
            "vigente": structured.get("vigente"),
        }
    if source_type == "tcu_normas":
        return {
            "tipo_norma": structured.get("tipo_norma"),
            "numero": structured.get("numero_norma"),
            "ano": structured.get("ano_norma"),
            "assunto": structured.get("assunto") or first_sentence,
            "vigencia": structured.get("data_inicio_vigencia") or structured.get("data_dou"),
        }
    key_a = next(iter(structured.keys()), None)
    key_b = next(iter(topics), None)
    return {
        SOURCE_SCHEMA_KEYS.get(source_type, ("ponto_principal",))[0]: structured.get(key_a) or first_sentence,
        "tema": key_b,
        "ponto_principal": first_sentence,
    }


def build_summary_short(source_type: str, text: str, structured: dict[str, Any], topics: list[str]) -> str:
    cleaned = clean_text(text)
    if source_type == "dou_documents":
        prefix = "DOU"
        detail = structured.get("h1_subtipo") or structured.get("art_type") or "ato"
        return f"{prefix}: {detail}. {cleaned[:220]}".strip()
    if source_type == "tcu_acordao_completo":
        numero = structured.get("numero_acordao")
        colegiado = structured.get("colegiado") or "TCU"
        return f"Acórdão {numero or ''} {colegiado}. {cleaned[:220]}".strip()
    label = source_type.replace("_", " ")
    topic_txt = ", ".join(topics[:2])
    return f"{label}: {topic_txt}. {cleaned[:220]}".strip()


def classify_enrichment_status(
    source_type: str,
    *,
    used_fallback: bool,
    spans_count: int,
    tags_count: int,
    summary_short: str | None,
    summary_structured: dict[str, Any] | None,
    topics: list[str] | None,
    legal_entities: list[dict[str, str]] | None,
) -> str:
    schema_keys = SOURCE_SCHEMA_KEYS.get(source_type, ())
    structured_score = 0
    if summary_structured:
        structured_score = sum(1 for key in schema_keys if summary_structured.get(key) not in (None, "", [], {}))
    has_topics = bool(topics)
    has_summary = bool((summary_short or "").strip())
    has_entities = bool(legal_entities)
    if used_fallback:
        return "done_fallback"
    if has_summary and has_topics and structured_score >= max(1, min(3, len(schema_keys))) and spans_count > 0:
        return "done_full"
    if has_summary and has_topics and (structured_score > 0 or has_entities or tags_count > 0):
        return "done_partial"
    return "done_fallback"
