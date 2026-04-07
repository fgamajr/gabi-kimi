from __future__ import annotations

import html
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


H2_ENRICHMENT_VERSION = "1.1.0"

TOPIC_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "licitacao",
        re.compile(
            r"\blicita[cç][aã]o\b|\bedital\b|\bpreg[aã]o\b|\bconcorr[eê]ncia\b",
            re.IGNORECASE,
        ),
    ),
    (
        "pessoal",
        re.compile(r"\bnomea[rd]?\b|\bexonera\b|\bdesigna\b|\bcargo\b", re.IGNORECASE),
    ),
    (
        "controle_externo",
        re.compile(
            r"\bac[oó]rd[aã]o\b|\bcolegiado\b|\brelator\b|\btcu\b", re.IGNORECASE
        ),
    ),
    (
        "regulacao",
        re.compile(
            r"\banvisa\b|\bregistro\b|\bproduto\b|\bmedicamento\b|\bradiof[aá]rmaco\b",
            re.IGNORECASE,
        ),
    ),
    (
        "normativo",
        re.compile(
            r"\bportaria\b|\bresolu[cç][aã]o\b|\blei\b|\bdecreto\b|\binstru[cç][aã]o normativa\b",
            re.IGNORECASE,
        ),
    ),
    ("consulta", re.compile(r"\bconsulta\b|\bresposta\b", re.IGNORECASE)),
    (
        "jurisprudencia",
        re.compile(
            r"\benunciado\b|\bexcerto\b|\bs[uú]mula\b|\bjurisprud[eê]ncia\b",
            re.IGNORECASE,
        ),
    ),
    (
        "saude_publica",
        re.compile(
            r"\banvisa\b|\bsa[uú]de\b|\bmedicamento\b|\bhospital\b|\bsanit[aá]ri",
            re.IGNORECASE,
        ),
    ),
    (
        "energia",
        re.compile(
            r"\banp\b|\bpetr[oó]leo\b|\bg[aá]s natural\b|\bcombust[ií]vel\b|\beletric",
            re.IGNORECASE,
        ),
    ),
    (
        "infraestrutura",
        re.compile(
            r"\brodovia\b|\bferrovia\b|\baeroporto\b|\bporto\b|\binfraestrutura\b",
            re.IGNORECASE,
        ),
    ),
    (
        "orcamento",
        re.compile(
            r"\bor[cç]ament[aá]ri[oa]\b|\bdota[cç][aã]o\b|\bcr[eé]dito adicional\b",
            re.IGNORECASE,
        ),
    ),
    (
        "educacao",
        re.compile(
            r"\beduca[cç][aã]o\b|\buniversidade\b|\bprofessor\b|\bbolsa\b",
            re.IGNORECASE,
        ),
    ),
    (
        "meio_ambiente",
        re.compile(
            r"\bambiental\b|\bmeio ambiente\b|\blicenciamento\b|\bibama\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tributario",
        re.compile(
            r"\btribut[aá]ri[oa]\b|\bimposto\b|\breceita federal\b|\bpis\b|\bcofins\b",
            re.IGNORECASE,
        ),
    ),
    (
        "previdencia",
        re.compile(r"\baposentadoria\b|\bpens[aã]o\b|\binss\b|\bprevid", re.IGNORECASE),
    ),
    (
        "servidor_publico",
        re.compile(
            r"\bservidor\b|\bquadro de pessoal\b|\bcargo efetivo\b", re.IGNORECASE
        ),
    ),
)
TOPIC_TAXONOMY: tuple[str, ...] = tuple(topic for topic, _ in TOPIC_RULES) + (
    "administrativo",
)
TOPIC_ALIASES: dict[str, str] = {
    "licitacoes": "licitacao",
    "licitacao_publica": "licitacao",
    "rh": "pessoal",
    "recursos_humanos": "pessoal",
    "saude": "saude_publica",
    "saude_sanitaria": "saude_publica",
    "orcamentario": "orcamento",
    "ambiental": "meio_ambiente",
    "previdenciario": "previdencia",
}

LEGAL_REFERENCE_RE = re.compile(
    r"\b(?:Lei|Decreto|Portaria|Resolu[cç][aã]o|Instru[cç][aã]o Normativa)\s*(?:n[º°\.]?\s*)?[\d./-]+",
    re.IGNORECASE,
)
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
PROCESSO_RE = re.compile(
    r"\b(?:Processo|Proc\.?|TC)\s*(?:n[º°o.]?\s*)?(?:[A-Z]{1,4}\s*)?[\d./-]{7,}\b",
    re.IGNORECASE,
)
SIGNATURE_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}){1,6}\b(?=[^<\n]{0,120}\b(?:MINISTRO|SECRET[ÁA]RIO|DIRETOR(?:A)?|PRESIDENTE|RELATOR|PROCURADOR|SUPERINTENDENTE|COORDENADOR|GERENTE|CHEFE)\b)",
    re.IGNORECASE,
)
ORG_SUFFIX_RE = re.compile(
    r"\b[A-Z][A-Z0-9 .,&/-]{4,}\s(?:LTDA|S/A|SA|EIRELI|ME|MINIST[EÉ]RIO|AG[EÊ]NCIA|TRIBUNAL|SECRETARIA)\b"
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SOURCE_NAME_RE = re.compile(r"^(dou_documents|tcu_[a-z0-9_]+)$", re.IGNORECASE)

SOURCE_SCHEMA_KEYS: dict[str, tuple[str, ...]] = {
    "dou_documents": (
        "tipo_ato",
        "subtipo_ato",
        "objeto",
        "fundamento_legal",
        "efeito_principal",
        "vigencia",
    ),
    "tcu_acordao_completo": (
        "numero",
        "colegiado",
        "relator",
        "tipo_processo",
        "objeto",
        "decisao_principal",
    ),
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


class LegalEntityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    value: str


class DouSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo_ato: str | None = None
    subtipo_ato: str | None = None
    objeto: str | None = None
    fundamento_legal: list[str] = []
    efeito_principal: str | None = None
    vigencia: str | None = None


class TcuAcordaoSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numero: str | None = None
    colegiado: str | None = None
    relator: str | None = None
    tipo_processo: str | None = None
    objeto: str | None = None
    decisao_principal: str | None = None


class TcuJurisprudenciaSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str | None = None
    tema: str | None = None
    subtema: str | None = None
    tese_central: str | None = None


class TcuRespostaConsultaSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str | None = None
    tema: str | None = None
    pergunta: str | None = None
    resposta_curta: str | None = None


class TcuSumulaSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numero: str | None = None
    tema: str | None = None
    tese_central: str | None = None
    vigente: str | None = None


class TcuBoletimJurisprudenciaSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str | None = None
    tema: str | None = None
    tese_central: str | None = None


class TcuBoletimPessoalSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str | None = None
    tema: str | None = None
    efeito_administrativo: str | None = None


class TcuBoletimInformativoLcSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str | None = None
    tema: str | None = None
    ponto_principal: str | None = None


class TcuNormasSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo_norma: str | None = None
    numero: str | None = None
    ano: str | None = None
    assunto: str | None = None
    vigencia: str | None = None


class TcuBtcuSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_title: str | None = None
    assunto: str | None = None
    base_legal: str | None = None
    decisao_principal: str | None = None


class TcuPublicacoesSummaryStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    pub_type: str | None = None
    assunto: str | None = None
    ponto_principal: str | None = None


SUMMARY_MODEL_BY_SOURCE: dict[str, type[BaseModel]] = {
    "dou_documents": DouSummaryStructured,
    "tcu_acordao_completo": TcuAcordaoSummaryStructured,
    "tcu_jurisprudencia_selecionada": TcuJurisprudenciaSummaryStructured,
    "tcu_resposta_consulta": TcuRespostaConsultaSummaryStructured,
    "tcu_sumula": TcuSumulaSummaryStructured,
    "tcu_boletim_jurisprudencia": TcuBoletimJurisprudenciaSummaryStructured,
    "tcu_boletim_pessoal": TcuBoletimPessoalSummaryStructured,
    "tcu_boletim_informativo_lc": TcuBoletimInformativoLcSummaryStructured,
    "tcu_normas": TcuNormasSummaryStructured,
    "tcu_btcu": TcuBtcuSummaryStructured,
    "tcu_publicacoes": TcuPublicacoesSummaryStructured,
}


def _normalize_string(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return clean_text(str(value)) or None


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        cleaned = _normalize_string(value)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _normalize_topic(value: str | None) -> str | None:
    cleaned = _normalize_string(value)
    if not cleaned:
        return None
    normalized = cleaned.lower().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    normalized = TOPIC_ALIASES.get(normalized, normalized)
    if normalized not in TOPIC_TAXONOMY:
        return None
    return normalized


def normalize_topics(
    source_type: str, topics: list[str] | None, text: str, structured: dict[str, Any]
) -> list[str]:
    out: list[str] = []
    for topic in topics or []:
        normalized = _normalize_topic(topic)
        if not normalized:
            continue
        if SOURCE_NAME_RE.match(normalized):
            continue
        if normalized not in out:
            out.append(normalized)
    if out:
        return out[:8]
    return derive_topics(source_type, text, structured)


def validate_summary_structured(
    source_type: str, payload: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload:
        return None
    model_cls = SUMMARY_MODEL_BY_SOURCE.get(source_type)
    if model_cls is None:
        return None
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            normalized[key] = _normalize_string_list(value)
            continue
        normalized[key] = _normalize_string(value)
    try:
        model = model_cls.model_validate(normalized)
    except ValidationError:
        return None
    return model.model_dump()


def validate_legal_entities(
    payload: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in payload or []:
        try:
            model = LegalEntityModel.model_validate(item)
        except ValidationError:
            continue
        entity_type = _normalize_string(model.type)
        entity_value = _normalize_string(model.value)
        if not entity_type or not entity_value:
            continue
        key = (entity_type, entity_value)
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": entity_type, "value": entity_value})
    return out[:16]


def clean_text(value: str | None) -> str:
    text = value or ""
    previous = None
    while previous != text:
        previous = text
        text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def summarize_text(value: str | None, limit: int = 320) -> str:
    return clean_text(value)[:limit]


def fallback_tags(
    allowed_tags: tuple[str, ...], section_map: dict[str, Any] | None
) -> list[str]:
    if not section_map:
        return []
    allowed = set(allowed_tags)
    return [tag for tag in section_map.keys() if tag in allowed]


def derive_topics(source_type: str, text: str, structured: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        [
            source_type,
            clean_text(text),
            " ".join(
                str(v) for v in structured.values() if v not in (None, "", [], {})
            ),
        ]
    )
    topics: list[str] = []
    for topic, pattern in TOPIC_RULES:
        if pattern.search(haystack):
            topics.append(topic)
    if source_type.startswith("tcu_") and "controle_externo" not in topics:
        topics.append("controle_externo")
    orgao = clean_text(str(structured.get("orgao_emissor") or ""))
    if (
        re.search(r"\banvisa\b|\bsa[uú]de\b", orgao, re.IGNORECASE)
        and "saude_publica" not in topics
    ):
        topics.append("saude_publica")
    if (
        re.search(r"\banp\b|\bpetr[oó]leo\b|\bg[aá]s\b", orgao, re.IGNORECASE)
        and "energia" not in topics
    ):
        topics.append("energia")
    if not topics:
        topics.append("administrativo")
    return topics[:8]


def derive_legal_entities(
    text: str, structured: dict[str, Any]
) -> list[dict[str, str]]:
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

    for match in CPF_RE.findall(cleaned):
        item = ("cpf", match)
        if item not in seen:
            seen.add(item)
            entities.append({"type": "cpf", "value": match})

    for match in PROCESSO_RE.findall(cleaned):
        value = clean_text(match)
        item = ("processo", value)
        if value and item not in seen:
            seen.add(item)
            entities.append({"type": "processo", "value": value})

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


def _add_span(
    spans: list[dict[str, Any]],
    *,
    tag: str,
    start: int,
    end: int,
    text_len: int,
) -> None:
    start = max(0, start)
    end = min(end, text_len)
    if end <= start:
        return
    for span in spans:
        if start < span["end_char"] and end > span["start_char"]:
            return
    spans.append(
        {
            "tag": tag,
            "start_char": start,
            "end_char": end,
            "confidence": 1.0,
        }
    )


def _inner_section_bounds(
    text: str, start: int, length: int
) -> tuple[int, int] | None:
    chunk_end = min(len(text), start + length)
    open_end = text.find(">", start, chunk_end)
    close_start = text.rfind("</", start, chunk_end)
    if open_end == -1 or close_start == -1 or close_start <= open_end:
        return None
    return open_end + 1, close_start


def _source_legal_tag(allowed_tags: tuple[str, ...]) -> str | None:
    for candidate in ("fundamento_legal", "referencia_legal", "base_legal"):
        if candidate in allowed_tags:
            return candidate
    return None


def derive_heuristic_spans(
    *,
    source_type: str,
    text: str,
    section_map: dict[str, Any] | None,
    allowed_tags: tuple[str, ...],
) -> list[dict[str, Any]]:
    del source_type
    spans: list[dict[str, Any]] = []
    text_len = len(text)
    section_map = section_map or {}

    for tag in ("identifica", _source_legal_tag(allowed_tags)):
        if not tag or tag not in allowed_tags:
            continue
        meta = section_map.get(tag)
        if not isinstance(meta, dict):
            continue
        start = int(meta.get("start") or 0)
        length = int(meta.get("len") or 0)
        bounds = _inner_section_bounds(text, start, length)
        if not bounds:
            continue
        _add_span(spans, tag=tag, start=bounds[0], end=bounds[1], text_len=text_len)

    if "processo" in allowed_tags:
        for match in PROCESSO_RE.finditer(text):
            _add_span(
                spans,
                tag="processo",
                start=match.start(),
                end=match.end(),
                text_len=text_len,
            )

    if "assinatura" in allowed_tags:
        for match in SIGNATURE_RE.finditer(text):
            _add_span(
                spans,
                tag="assinatura",
                start=match.start(),
                end=match.end(),
                text_len=text_len,
            )

    return sorted(spans, key=lambda item: (item["start_char"], item["end_char"], item["tag"]))


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
            "fundamento_legal": [
                x["value"] for x in legal_entities if x["type"] == "base_legal"
            ][:6],
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
            "vigencia": structured.get("data_inicio_vigencia")
            or structured.get("data_dou"),
        }
    key_a = next(iter(structured.keys()), None)
    key_b = next(iter(topics), None)
    return {
        SOURCE_SCHEMA_KEYS.get(source_type, ("ponto_principal",))[0]: structured.get(
            key_a
        )
        or first_sentence,
        "tema": key_b,
        "ponto_principal": first_sentence,
    }


def _first_sentence(text: str, max_len: int = 280) -> str:
    text = clean_text(text)
    if not text:
        return ""
    for sep in (". ", "! ", "? "):
        if sep in text:
            return text[: text.index(sep) + 2].strip()
    return text[:max_len].strip()


def build_summary_short(
    source_type: str, text: str, structured: dict[str, Any], topics: list[str]
) -> str:
    first = _first_sentence(text)
    if source_type == "dou_documents":
        prefix = "DOU"
        detail = structured.get("h1_subtipo") or structured.get("art_type") or "ato"
        return f"{prefix}: {detail}. {first}".strip()
    if source_type == "tcu_acordao_completo":
        numero = structured.get("numero_acordao")
        colegiado = structured.get("colegiado") or "TCU"
        return f"Acórdão {numero or ''} {colegiado}. {first}".strip()
    label = source_type.replace("_", " ")
    topic_txt = ", ".join(topics[:2])
    return f"{label}: {topic_txt}. {first}".strip()


def classify_enrichment_mode(
    *,
    used_fallback: bool,
    llm_summary_used: bool,
    llm_structured_used: bool,
    llm_topics_used: bool,
    llm_entities_used: bool,
    llm_spans_used: bool,
) -> str:
    if used_fallback:
        return "fallback"
    if any(
        (
            llm_summary_used,
            llm_structured_used,
            llm_topics_used,
            llm_entities_used,
            llm_spans_used,
        )
    ):
        return "llm"
    return "heuristic"


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
        structured_score = sum(
            1
            for key in schema_keys
            if summary_structured.get(key) not in (None, "", [], {})
        )
    has_topics = bool(topics)
    has_summary = bool((summary_short or "").strip())
    has_entities = bool(legal_entities)
    if used_fallback:
        return "done_fallback"
    if (
        has_summary
        and has_topics
        and structured_score >= max(1, min(3, len(schema_keys)))
        and spans_count > 0
    ):
        return "done_full"
    if (
        has_summary
        and has_topics
        and (structured_score > 0 or has_entities or tags_count > 0)
    ):
        return "done_partial"
    return "done_fallback"
