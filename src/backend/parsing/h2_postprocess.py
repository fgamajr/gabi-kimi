from __future__ import annotations

import html
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


H2_ENRICHMENT_VERSION = "1.2.0"

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
    r"\b(?:Lei(?:\s+Complementar)?|Decreto(?:-Lei)?|Portaria|Resolu[cç][aã]o|Instru[cç][aã]o Normativa)"
    r"\s*(?:n[º°o.]?\s*)?\d[\d./-]*",
    re.IGNORECASE,
)
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
PROCESSO_RE = re.compile(
    r"\b(?:Processo|Proc\.?|TC)\s*(?:n[º°o.]?\s*)?(?:[A-Z]{1,4}\s*)?\d[\d./-]{6,}\b",
    re.IGNORECASE,
)
SIGNATURE_CANDIDATE_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}(?:\s+(?:DE|DA|DO|DAS|DOS|E|[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,})){1,6}\b"
)
SIGNATURE_ROLE_RE = re.compile(
    r"\b(?:ministro|secret[áa]ri[oa]|diretor(?:a)?(?:-geral)?|presidente|relator|procurador(?:a)?|"
    r"superintendente|coordenador(?:a)?(?:-geral)?|gerente(?:-geral)?|chefe|auditor|conselheiro|"
    r"juiz|desembargador|governador|prefeito|senador|deputado|reitor)\b",
    re.IGNORECASE,
)
ORG_SUFFIX_RE = re.compile(
    r"\b[A-Z][A-Z0-9 .,&/-]{4,}\s(?:LTDA|S/A|SA|EIRELI|ME|MINIST[EÉ]RIO|AG[EÊ]NCIA|TRIBUNAL|SECRETARIA)\b"
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SOURCE_NAME_RE = re.compile(r"^(dou_documents|tcu_[a-z0-9_]+)$", re.IGNORECASE)
BAD_ORG_ENTITY_RE = re.compile(
    r"\b(?:de|do|da|das|dos|para|com|que|fica|resolve|torna|disp[oõ]e|considerando|"
    r"trata-se|homologo|nomeia|exonera|designa)\b",
    re.IGNORECASE,
)
TRUNCATED_ENTITY_RE = re.compile(r"[-./:;,]$")
ONLY_NUMBER_RE = re.compile(r"^\d+(?:[./-]\d+)*$")
GENERIC_TOPICS = {"administrativo", "controle_externo", "normativo", "regulacao", "jurisprudencia"}
SIGNATURE_MAX_SPANS = 5
SIGNATURE_MAX_CHARS = 80
SIGNATURE_CONTEXT_CHARS = 60
ORGANIZACAO_MAX_CHARS = 60
FORBIDDEN_SIGNATURE_TOKENS = {
    "TRIBUNAL",
    "MINISTERIO",
    "MINISTÉRIO",
    "AGENCIA",
    "AGÊNCIA",
    "SECRETARIA",
    "SUPERINTENDENCIA",
    "SUPERINTENDÊNCIA",
    "COMISSAO",
    "COMISSÃO",
    "PARTIDO",
    "CAMARA",
    "CÂMARA",
    "SENADO",
    "COORDENACAO",
    "COORDENAÇÃO",
    "DIRETORIA",
    "GERENCIA",
    "GERÊNCIA",
    "ANP",
    "ANVISA",
    "TCU",
}
SOURCE_STATUS_RULES: dict[str, dict[str, int | bool | float]] = {
    "dou_documents": {"min_structured": 2, "min_useful_tags": 2, "require_entities": 0, "min_overall": 0.7},
    "tcu_acordao_completo": {"min_structured": 3, "min_useful_tags": 2, "require_entities": 0, "min_overall": 0.72},
    "tcu_jurisprudencia_selecionada": {"min_structured": 3, "min_useful_tags": 2, "require_entities": 0, "min_overall": 0.72},
    "tcu_resposta_consulta": {"min_structured": 3, "min_useful_tags": 2, "require_entities": 0, "min_overall": 0.72},
    "tcu_sumula": {"min_structured": 2, "min_useful_tags": 1, "require_entities": 0, "min_overall": 0.7},
    "tcu_boletim_jurisprudencia": {"min_structured": 2, "min_useful_tags": 2, "require_entities": 0, "min_overall": 0.74, "allow_done_full": 0},
    "tcu_boletim_pessoal": {"min_structured": 2, "min_useful_tags": 1, "require_entities": 0, "min_overall": 0.72, "allow_done_full": 0},
    "tcu_boletim_informativo_lc": {"min_structured": 2, "min_useful_tags": 2, "require_entities": 0, "min_overall": 0.72},
    "tcu_normas": {"min_structured": 3, "min_useful_tags": 1, "require_entities": 0, "min_overall": 0.72},
    "tcu_btcu": {"min_structured": 2, "min_useful_tags": 2, "require_entities": 1, "min_overall": 0.76, "allow_done_full": 0},
    "tcu_publicacoes": {"min_structured": 2, "min_useful_tags": 2, "require_entities": 0, "min_overall": 0.74},
}
SECTION_TAGS_BY_SOURCE: dict[str, tuple[str, ...]] = {
    "dou_documents": ("identifica", "fundamento_legal"),
    "tcu_acordao_completo": ("sumario", "decisao", "referencia_legal"),
    "tcu_jurisprudencia_selecionada": ("enunciado", "excerto", "referencia_legal", "indexacao"),
    "tcu_resposta_consulta": ("pergunta", "resposta", "referencia_legal", "indexacao"),
    "tcu_sumula": ("enunciado", "excerto", "referencia_legal"),
    "tcu_boletim_jurisprudencia": ("titulo", "enunciado"),
    "tcu_boletim_pessoal": ("titulo", "enunciado"),
    "tcu_boletim_informativo_lc": ("titulo", "enunciado", "texto_info"),
    "tcu_normas": ("titulo", "assunto", "normas_relacionadas"),
    "tcu_btcu": ("section_title", "assunto", "base_legal"),
    "tcu_publicacoes": ("titulo", "descricao"),
}
SECTION_TAG_ALIASES_BY_SOURCE: dict[str, dict[str, str]] = {
    "tcu_publicacoes": {
        "titulo": "title",
        "descricao": "description",
        "corpo": "body_plain",
    }
}

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


def _normalize_entity_value(value: Any) -> str | None:
    cleaned = _normalize_string(value)
    if not cleaned:
        return None
    cleaned = SPACE_RE.sub(" ", cleaned).strip(" \t\r\n-.,;:/")
    if not cleaned or TRUNCATED_ENTITY_RE.search(cleaned):
        return None
    return cleaned


def _canonical_entity_key(entity_type: str, value: str) -> str:
    normalized = clean_text(value).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return f"{entity_type}:{normalized}"


def _is_bad_organization(value: str) -> bool:
    if len(value) > ORGANIZACAO_MAX_CHARS:
        return True
    if BAD_ORG_ENTITY_RE.search(value):
        return True
    if sum(1 for token in value.split() if token.isupper()) < 2:
        return True
    return False


def _normalize_legal_reference(value: str) -> str | None:
    match = LEGAL_REFERENCE_RE.search(value)
    if not match:
        return None
    cleaned = clean_text(match.group(0))
    cleaned = re.sub(r"(?i)\bn[º°o.]?\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -.,;:/")
    if not re.search(r"\d", cleaned):
        return None
    return cleaned


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
    seen: set[str] = set()
    for item in payload or []:
        try:
            model = LegalEntityModel.model_validate(item)
        except ValidationError:
            continue
        entity_type = _normalize_string(model.type)
        entity_value = _normalize_entity_value(model.value)
        if not entity_type or not entity_value:
            continue
        if entity_type == "base_legal":
            entity_value = _normalize_legal_reference(entity_value) or ""
        if entity_type == "organizacao" and _is_bad_organization(entity_value):
            continue
        if not entity_value:
            continue
        key = _canonical_entity_key(entity_type, entity_value)
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
    text = clean_text(value)
    if len(text) <= limit:
        return text
    punct_idx = max(text.rfind(sep, 0, limit) for sep in (". ", "! ", "? ", "; ", ": "))
    if punct_idx >= max(15, limit // 4):
        return text[: punct_idx + 1].strip()
    lookahead_limit = min(len(text), limit + 120)
    forward_candidates = [text.find(sep, limit, lookahead_limit) for sep in (". ", "! ", "? ", "; ")]
    forward_idx = min((idx for idx in forward_candidates if idx != -1), default=-1)
    if forward_idx != -1:
        return text[: forward_idx + 1].strip()
    space_idx = text.rfind(" ", 0, limit)
    if space_idx >= max(15, limit // 4):
        return text[:space_idx].strip()
    return text[:limit].strip()


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
    if source_type == "tcu_jurisprudencia_selecionada":
        if structured.get("tema") and "jurisprudencia" not in topics:
            topics.append("jurisprudencia")
        tema = clean_text(str(structured.get("tema") or ""))
        subtema = clean_text(str(structured.get("subtema") or ""))
        if re.search(r"\blicita[cç][aã]o\b", f"{tema} {subtema}", re.IGNORECASE) and "licitacao" not in topics:
            topics.append("licitacao")
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
    if source_type.startswith("tcu_") and not topics:
        topics.append("controle_externo")
    if not topics:
        topics.append("administrativo")
    return topics[:8]


def derive_legal_entities(
    text: str, structured: dict[str, Any]
) -> list[dict[str, str]]:
    cleaned = clean_text(text)
    entities: list[dict[str, str]] = []
    seen: set[str] = set()

    for key in ("orgao_emissor", "colegiado", "relator", "numero_processo"):
        value = _normalize_entity_value(structured.get(key))
        if value:
            item = _canonical_entity_key(key, value)
            if item not in seen:
                seen.add(item)
                entities.append({"type": key, "value": value})

    for match in CNPJ_RE.findall(cleaned):
        item = _canonical_entity_key("cnpj", match)
        if item not in seen:
            seen.add(item)
            entities.append({"type": "cnpj", "value": match})

    for match in CPF_RE.findall(cleaned):
        item = _canonical_entity_key("cpf", match)
        if item not in seen:
            seen.add(item)
            entities.append({"type": "cpf", "value": match})

    for match in PROCESSO_RE.findall(cleaned):
        value = _normalize_entity_value(match)
        item = _canonical_entity_key("processo", value or "")
        if value and item not in seen:
            seen.add(item)
            entities.append({"type": "processo", "value": value})

    for match in LEGAL_REFERENCE_RE.findall(cleaned):
        value = _normalize_legal_reference(match)
        item = _canonical_entity_key("base_legal", value or "")
        if value and item not in seen:
            seen.add(item)
            entities.append({"type": "base_legal", "value": value})

    for match in ORG_SUFFIX_RE.findall(cleaned):
        value = _normalize_entity_value(match)
        if not value or _is_bad_organization(value):
            continue
        item = _canonical_entity_key("organizacao", value)
        if item not in seen:
            seen.add(item)
            entities.append({"type": "organizacao", "value": value})

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


def _section_tags_for_source(source_type: str, allowed_tags: tuple[str, ...]) -> tuple[str, ...]:
    preferred = SECTION_TAGS_BY_SOURCE.get(source_type, ())
    return tuple(tag for tag in preferred if tag in allowed_tags)


def _section_value(
    source_type: str,
    section_map: dict[str, Any],
    tag: str,
) -> dict[str, Any] | None:
    meta = section_map.get(tag)
    if isinstance(meta, dict):
        return meta
    alias = SECTION_TAG_ALIASES_BY_SOURCE.get(source_type, {}).get(tag)
    if alias:
        aliased = section_map.get(alias)
        if isinstance(aliased, dict):
            return aliased
    return None


def _iter_signature_spans(text: str, text_len: int) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    min_start = max(0, text_len - 2500) if text_len > 5000 else 0
    for match in SIGNATURE_CANDIDATE_RE.finditer(text):
        if match.start() < min_start:
            continue
        candidate = clean_text(match.group(0))
        if len(candidate) > SIGNATURE_MAX_CHARS:
            continue
        upper_tokens = {token for token in candidate.split() if token not in {"DE", "DA", "DO", "DAS", "DOS", "E"}}
        if upper_tokens & FORBIDDEN_SIGNATURE_TOKENS:
            continue
        context = text[match.end() : min(text_len, match.end() + SIGNATURE_CONTEXT_CHARS)]
        if not SIGNATURE_ROLE_RE.search(context):
            continue
        _add_span(
            spans,
            tag="assinatura",
            start=match.start(),
            end=match.end(),
            text_len=text_len,
        )
        if len(spans) >= SIGNATURE_MAX_SPANS:
            break
    return spans


def derive_heuristic_spans(
    *,
    source_type: str,
    text: str,
    section_map: dict[str, Any] | None,
    allowed_tags: tuple[str, ...],
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    text_len = len(text)
    section_map = section_map or {}

    for tag in _section_tags_for_source(source_type, allowed_tags):
        meta = _section_value(source_type, section_map, tag)
        if meta is None:
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
        for span in _iter_signature_spans(text, text_len):
            _add_span(
                spans,
                tag=span["tag"],
                start=span["start_char"],
                end=span["end_char"],
                text_len=text_len,
            )

    return sorted(spans, key=lambda item: (item["start_char"], item["end_char"], item["tag"]))


def _split_sentences(text: str) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _is_low_signal_sentence(value: str | None) -> bool:
    cleaned = clean_text(value)
    if not cleaned:
        return True
    return bool(
        " ANEXO " in f" {cleaned.upper()} "
        or
        re.match(r"^(?:art\.?|arts?\.?|\d+[ºo]?,?|§|inciso|al[ií]nea)\b", cleaned, re.IGNORECASE)
        or re.match(r"^\d+[./-]?\d*", cleaned)
        or "NOME DA EMPRESA" in cleaned.upper()
    )


def _pick_best_sentence(sentences: list[str], *, skip_low_signal: bool = False) -> str | None:
    for sentence in sentences:
        summarized = summarize_text(sentence, limit=220)
        if skip_low_signal and _is_low_signal_sentence(summarized):
            continue
        if summarized:
            return summarized
    return None


def _first_specific_topic(topics: list[str]) -> str | None:
    for topic in topics:
        if topic not in GENERIC_TOPICS:
            return topic
    return topics[0] if topics else None


def _meaningful_value(value: Any) -> str | None:
    cleaned = _normalize_string(value)
    if not cleaned or ONLY_NUMBER_RE.fullmatch(cleaned):
        return None
    return cleaned


def build_summary_structured(
    source_type: str,
    text: str,
    structured: dict[str, Any],
    topics: list[str],
    legal_entities: list[dict[str, str]],
) -> dict[str, Any]:
    sentences = _split_sentences(text)
    first_sentence = _pick_best_sentence(sentences) or summarize_text(text, limit=220)
    second_sentence = _pick_best_sentence(sentences[1:], skip_low_signal=True)

    if source_type == "dou_documents":
        fundamento = [
            x["value"] for x in legal_entities if x["type"] == "base_legal"
        ][:6]
        return {
            "tipo_ato": structured.get("h1_tipo") or structured.get("art_type"),
            "subtipo_ato": structured.get("h1_subtipo") or structured.get("art_type"),
            "objeto": first_sentence,
            "fundamento_legal": fundamento,
            "efeito_principal": second_sentence or None,
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
            "pergunta": summarize_text(structured.get("tema") or first_sentence, limit=220),
            "resposta_curta": summarize_text(first_sentence, limit=220),
        }
    if source_type == "tcu_sumula":
        return {
            "numero": structured.get("numero"),
            "tema": structured.get("tema"),
            "tese_central": summarize_text(first_sentence, limit=220),
            "vigente": structured.get("vigente"),
        }
    if source_type == "tcu_boletim_jurisprudencia":
        return {
            "titulo": summarize_text(structured.get("titulo"), limit=180) or first_sentence,
            "tema": _first_specific_topic(topics) or "jurisprudencia",
            "tese_central": summarize_text(first_sentence, limit=220),
        }
    if source_type == "tcu_boletim_pessoal":
        return {
            "titulo": summarize_text(structured.get("titulo"), limit=180) or first_sentence,
            "tema": _first_specific_topic(topics) or "pessoal",
            "efeito_administrativo": summarize_text(first_sentence, limit=220),
        }
    if source_type == "tcu_boletim_informativo_lc":
        return {
            "titulo": summarize_text(structured.get("titulo"), limit=180) or first_sentence,
            "tema": _first_specific_topic(topics) or "licitacao",
            "ponto_principal": summarize_text(first_sentence, limit=220),
        }
    if source_type == "tcu_normas":
        return {
            "tipo_norma": structured.get("tipo_norma"),
            "numero": structured.get("numero_norma"),
            "ano": structured.get("ano_norma"),
            "assunto": summarize_text(structured.get("assunto") or first_sentence, limit=220),
            "vigencia": structured.get("data_inicio_vigencia")
            or structured.get("data_dou"),
        }
    if source_type == "tcu_btcu":
        base_legal = next((x["value"] for x in legal_entities if x["type"] == "base_legal"), None)
        return {
            "section_title": summarize_text(
                structured.get("section_title") or structured.get("section_type"),
                limit=180,
            )
            or _first_specific_topic(topics)
            or "btcu",
            "assunto": summarize_text(structured.get("assunto") or first_sentence, limit=220),
            "base_legal": base_legal,
            "decisao_principal": summarize_text(second_sentence or first_sentence, limit=220),
        }
    if source_type == "tcu_publicacoes":
        assunto = _first_specific_topic(topics) or structured.get("pub_type")
        return {
            "title": summarize_text(structured.get("title"), limit=180) or first_sentence,
            "pub_type": structured.get("pub_type"),
            "assunto": summarize_text(assunto, limit=120) if assunto else None,
            "ponto_principal": summarize_text(first_sentence, limit=220),
        }
    key_a = next(iter(structured.keys()), None)
    key_b = next(iter(topics), None)
    primary = _meaningful_value(structured.get(key_a)) if key_a else None
    return {
        SOURCE_SCHEMA_KEYS.get(source_type, ("ponto_principal",))[0]: summarize_text(primary or first_sentence, limit=220),
        "tema": key_b,
        "ponto_principal": summarize_text(second_sentence or first_sentence, limit=220),
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


def useful_tags(tags: list[str]) -> list[str]:
    return [tag for tag in tags if tag != "assinatura"]


def build_confidence_fields(
    source_type: str,
    *,
    tags: list[str],
    summary_structured: dict[str, Any] | None,
    topics: list[str] | None,
    legal_entities: list[dict[str, str]] | None,
) -> dict[str, float]:
    schema_keys = SOURCE_SCHEMA_KEYS.get(source_type, ())
    structured_score = 0
    if summary_structured:
        structured_score = sum(
            1
            for key in schema_keys
            if summary_structured.get(key) not in (None, "", [], {})
        )
    unique_useful_tags = list(dict.fromkeys(useful_tags(tags)))
    signature_count = max(0, len(tags) - len(unique_useful_tags))
    topic_values = topics or []
    specific_topics = [topic for topic in topic_values if topic not in GENERIC_TOPICS]
    entity_values = legal_entities or []
    entity_types = {item["type"] for item in entity_values}

    tag_conf = 0.0
    if unique_useful_tags:
        tag_conf = min(0.9, 0.55 + 0.12 * min(len(unique_useful_tags), 3) - 0.05 * signature_count)
    elif tags:
        tag_conf = 0.2

    structured_conf = 0.0
    if schema_keys:
        structured_conf = min(0.9, 0.35 + 0.55 * (structured_score / max(1, len(schema_keys))))
    elif summary_structured:
        structured_conf = 0.6

    topics_conf = 0.0
    if topic_values:
        topics_conf = 0.3 if not specific_topics else min(0.85, 0.55 + 0.1 * min(len(specific_topics), 3))

    entities_conf = 0.0
    if entity_values:
        entities_conf = min(0.9, 0.45 + 0.1 * min(len(entity_types), 3) + 0.05 * min(len(entity_values), 4))

    overall = round(
        (0.35 * tag_conf) + (0.25 * structured_conf) + (0.2 * entities_conf) + (0.2 * topics_conf),
        3,
    )
    return {
        "tag_spans": round(max(0.0, tag_conf), 3),
        "summary_structured": round(max(0.0, structured_conf), 3),
        "topics": round(max(0.0, topics_conf), 3),
        "legal_entities": round(max(0.0, entities_conf), 3),
        "overall": max(0.0, overall),
    }


def classify_enrichment_status(
    source_type: str,
    *,
    used_fallback: bool,
    tags: list[str],
    summary_short: str | None,
    summary_structured: dict[str, Any] | None,
    topics: list[str] | None,
    legal_entities: list[dict[str, str]] | None,
    confidence_fields: dict[str, float] | None,
) -> str:
    rules = SOURCE_STATUS_RULES.get(source_type, SOURCE_STATUS_RULES["dou_documents"])
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
    useful = useful_tags(tags)
    useful_tags_count = len(set(useful))
    has_non_signature_spans = useful_tags_count > 0
    overall = float((confidence_fields or {}).get("overall") or 0.0)
    if used_fallback:
        return "done_fallback"
    if (
        has_summary
        and has_topics
        and bool(rules.get("allow_done_full", 1))
        and has_non_signature_spans
        and structured_score >= int(rules["min_structured"])
        and useful_tags_count >= int(rules["min_useful_tags"])
        and overall >= float(rules["min_overall"])
        and (not bool(rules["require_entities"]) or has_entities)
    ):
        return "done_full"
    if (
        has_summary
        and has_topics
        and (structured_score > 0 or has_entities or useful_tags_count > 0 or bool(tags))
    ):
        return "done_partial"
    return "done_fallback"
