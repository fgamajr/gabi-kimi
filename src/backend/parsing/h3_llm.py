from __future__ import annotations

import re
from typing import Any

from src.backend.parsing.h2_llm import call_local_llm
from src.backend.parsing.h2_postprocess import (
    SOURCE_SCHEMA_KEYS,
    build_confidence_fields,
    classify_enrichment_status,
    clean_text,
    normalize_topics,
    validate_summary_structured,
)
from src.backend.parsing.h3_semantic import (
    H3Input,
    build_gate_decision,
    derive_quality_flags,
)
from src.backend.parsing.source_semantics import get_semantic_contract

H3_LLM_PROMPT_VERSION = "h3_v1_2_prompt_v2"
GENERIC_TOPICS = {"controle_externo", "normativo", "jurisprudencia", "regulacao", "administrativo"}
DEONTIC_RE = re.compile(
    r"\b(?:deve(?:m)?|n[aã]o deve(?:m)?|[ée]\s+vedad[oa]|fica\s+vedad[oa]|obrigat[oó]ri[oa])\b",
    re.IGNORECASE,
)
WEAK_SUMMARY_END_RE = re.compile(
    r"(?:\b(?:e|ou|por|para|com|sem|na|no|nas|nos|ao|aos|ainda)\b|[:;,/-])$",
    re.IGNORECASE,
)

# Versão v1 (conservadora demais — gerava eco do H2 e era bloqueada pelo gate de delta).
# Mantida apenas como referência histórica; não usar.
_H3_PROMPT_TEMPLATE_V1_CONSERVATIVE = (
    "Você é um refinador semântico para {source_type}.\n"
    "Sua tarefa é revisar seeds semânticos vindos do H2 e devolver apenas refinamentos grounded no texto.\n"
    "Você NÃO pode gerar spans, entidades, tags, nem reestruturar o documento.\n"
    "Campos obrigatórios do summary_structured: [{schema_keys}].\n"
    "Retorne APENAS JSON com o formato:\n"
    "{{"
    '"summary_short":"...",'
    '"summary_structured":{{}},'
    '"topics":[]'
    "}}\n"
    "Regras:\n"
    "- preserve a ideia central do H2 quando o texto não justificar mudança\n"
    "- topics devem ser específicos e em snake_case\n"
    "- summary_short deve ser curto, limpo e sem XML\n"
    "- summary_structured deve respeitar o schema da fonte\n"
    "Seed summary_short: {seed_summary_short}\n"
    "Seed summary_structured: {seed_summary_structured}\n"
    "Seed topics: {seed_topics}\n"
    "Texto:\n{text}"
)

H3_PROMPT_TEMPLATE = (
    "Você é um refinador semântico para {source_type}.\n"
    "O H2 entregou seeds heurísticos abaixo. Eles costumam falhar de três formas:\n"
    "  (a) summary_short ecoa o título/cabeçalho em vez de descrever a decisão;\n"
    "  (b) topics vêm genéricos (ex.: 'jurisprudencia', 'decisao', 'tcu') sem refletir o assunto real;\n"
    "  (c) summary_structured tem campos vazios ou repetindo o seed.\n"
    "Sua tarefa é CORRIGIR ativamente esses três casos quando houver evidência no texto.\n"
    "Você NÃO pode inventar entidades, números, datas, nomes, valores ou citações que não estejam no texto.\n"
    "Você NÃO pode gerar spans, tags ou reestruturar o documento.\n"
    "Campos obrigatórios do summary_structured: [{schema_keys}].\n"
    "Retorne APENAS JSON com o formato:\n"
    "{{"
    '"summary_short":"...",'
    '"summary_structured":{{}},'
    '"topics":[]'
    "}}\n"
    "Regras:\n"
    "- Reescreva summary_short apenas quando o seed ecoar título, cabeçalho, ementa "
    "ou texto excessivamente genérico; produza 1 ou 2 frases curtas explicando a tese "
    "ou decisão material do caso.\n"
    "- Em topics, devolva de 1 a 4 termos em snake_case, específicos do assunto; "
    "evite tópicos genéricos como jurisprudencia, controle_externo, normativo, "
    "decisao ou tcu, salvo se vierem acompanhados de tema material mais específico.\n"
    "- Preserve literalmente fatos e identificadores explícitos do texto, como número "
    "de processo, relator, colegiado, datas, valores, artigos e nomes próprios; "
    "só reescreva campos interpretativos do summary_structured para ganhar clareza "
    "sem inventar conteúdo.\n"
    "- Em jurisprudência ou enunciados prescritivos, preserve o tom normativo do seed; "
    "não troque verbos deônticos como 'deve', 'não deve' ou 'é vedado' por paráfrases "
    "descritivas mais fracas.\n"
    "- Se faltar evidência para melhorar um campo, mantenha o valor do seed em vez de "
    "inventar ou generalizar; não preencha lacunas com inferência fraca.\n"
    "- Nunca invente precedente, fundamento legal, sanção, órgão, resultado, valor ou "
    "participante que não apareça no texto; na dúvida, prefira devolver o seed quase "
    "intacto.\n"
    "- Quando houver lista, tabela ou redação truncada, resuma o efeito jurídico ou "
    "administrativo em linguagem natural grounded no texto, sem copiar blocos "
    "literais longos.\n"
    "Seed summary_short: {seed_summary_short}\n"
    "Seed summary_structured: {seed_summary_structured}\n"
    "Seed topics: {seed_topics}\n"
    "Texto:\n{text}"
)


def build_h3_prompt(text: str, inp: H3Input) -> str:
    contract = get_semantic_contract(inp.source_type)
    schema_keys = ", ".join(contract.semantic_fields or SOURCE_SCHEMA_KEYS.get(inp.source_type, ("tema", "ponto_principal")))
    primary_sections = ", ".join(contract.primary_sections) or "texto"
    ementary_fields = ", ".join(contract.ementary_fields) or "-"
    return H3_PROMPT_TEMPLATE.format(
        source_type=inp.source_type,
        schema_keys=schema_keys,
        seed_summary_short=inp.h2_summary_short or "",
        seed_summary_structured=inp.h2_summary_structured or {},
        seed_topics=inp.h2_topics or [],
        text=(
            f"Seções primárias com maior peso semântico: {primary_sections}\n"
            f"Campos ementários que não devem dominar o resumo: {ementary_fields}\n"
            f"{text[:12000]}"
        ),
    )


def _normalize_comparison_text(value: Any) -> str | None:
    cleaned = clean_text(str(value) if value is not None else None).lower()
    return cleaned or None


def _normalize_topics_for_comparison(topics: list[str] | None) -> list[str]:
    normalized = {
        topic
        for topic in (_normalize_comparison_text(item) for item in (topics or []))
        if topic
    }
    return sorted(normalized)


def _token_set(value: Any) -> set[str]:
    cleaned = _normalize_comparison_text(value) or ""
    return {token for token in re.findall(r"[a-z0-9_]{3,}", cleaned) if token}


def _jaccard_similarity(left: Any, right: Any) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _summary_needs_refinement(value: Any) -> bool:
    cleaned = clean_text(str(value) if value is not None else None)
    if not cleaned:
        return True
    if len(cleaned) > 220:
        return True
    if WEAK_SUMMARY_END_RE.search(cleaned):
        return True
    if re.search(r"^(?:dou|tcu)\s*:", cleaned, re.IGNORECASE):
        return True
    return False


def _summary_change_counts(projected: Any, refined: Any) -> bool:
    projected_text = clean_text(str(projected) if projected is not None else None)
    refined_text = clean_text(str(refined) if refined is not None else None)
    if not projected_text or not refined_text:
        return False
    if DEONTIC_RE.search(projected_text) and not DEONTIC_RE.search(refined_text):
        return False
    if _summary_needs_refinement(projected_text):
        return True
    return _jaccard_similarity(projected_text, refined_text) < 0.55


def _specific_topic_count(topics: list[str] | None) -> int:
    return sum(1 for topic in topics or [] if topic not in GENERIC_TOPICS)


def _topics_change_counts(projected: list[str], refined: list[str]) -> bool:
    projected_normalized = _normalize_topics_for_comparison(projected)
    refined_normalized = _normalize_topics_for_comparison(refined)
    if projected_normalized == refined_normalized:
        return False
    projected_specific = _specific_topic_count(projected_normalized)
    refined_specific = _specific_topic_count(refined_normalized)
    if refined_specific > projected_specific:
        return True
    if refined_specific == projected_specific == 0:
        return False
    return refined_specific > 0 and refined_normalized != projected_normalized


def _normalize_structured_value(value: Any) -> Any:
    if isinstance(value, list):
        items = [_normalize_structured_value(item) for item in value]
        compact = [item for item in items if item not in (None, "", [], {})]
        if not compact:
            return None
        if all(not isinstance(item, (dict, list)) for item in compact):
            return sorted(compact)
        return compact
    if isinstance(value, dict):
        normalized = {
            key: normalized_value
            for key, normalized_value in (
                (key, _normalize_structured_value(item))
                for key, item in sorted(value.items())
            )
            if normalized_value not in (None, "", [], {})
        }
        return normalized or None
    if isinstance(value, str):
        return _normalize_comparison_text(value)
    return value


def _canonical_structured_summary(
    source_type: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    keys = SOURCE_SCHEMA_KEYS.get(source_type) or tuple(sorted(payload))
    normalized: dict[str, Any] = {}
    for key in keys:
        normalized_value = _normalize_structured_value(payload.get(key))
        if normalized_value not in (None, "", [], {}):
            normalized[key] = normalized_value
    return normalized


def _semantic_delta_breakdown(
    source_type: str,
    *,
    projected_summary_short: str | None,
    projected_summary_structured: dict[str, Any] | None,
    projected_topics: list[str],
    refined_summary_short: str | None,
    refined_summary_structured: dict[str, Any] | None,
    refined_topics: list[str],
) -> dict[str, Any]:
    summary_changed = _normalize_comparison_text(projected_summary_short) != _normalize_comparison_text(
        refined_summary_short
    )
    structured_changed = _canonical_structured_summary(
        source_type,
        projected_summary_structured,
    ) != _canonical_structured_summary(source_type, refined_summary_structured)
    topics_changed = _normalize_topics_for_comparison(projected_topics) != _normalize_topics_for_comparison(
        refined_topics
    )
    summary_counts = summary_changed and _summary_change_counts(
        projected_summary_short,
        refined_summary_short,
    )
    topics_counts = topics_changed and _topics_change_counts(projected_topics, refined_topics)
    changed_fields = [
        field
        for field, changed in (
            ("summary_short", summary_changed),
            ("summary_structured", structured_changed),
            ("topics", topics_changed),
        )
        if changed
    ]
    return {
        "delta_material": bool(structured_changed or summary_counts or topics_counts),
        "summary_changed": summary_changed,
        "summary_counts": summary_counts,
        "structured_changed": structured_changed,
        "topics_changed": topics_changed,
        "topics_counts": topics_counts,
        "changed_fields": changed_fields,
    }


def _resolve_llm_topics(
    inp: H3Input,
    projected_topics: list[str],
    llm_output: dict[str, Any],
    *,
    raw_text: str,
) -> list[str]:
    raw_topics = llm_output.get("topics")
    if not isinstance(raw_topics, list) or not raw_topics:
        return list(projected_topics)
    normalized = normalize_topics(
        inp.source_type,
        raw_topics,
        raw_text,
        inp.structured_fields_subset or {},
    )
    return normalized or list(projected_topics)


def apply_h3_llm_output(
    inp: H3Input,
    projected: dict[str, Any],
    *,
    raw_text: str,
    llm_output: dict[str, Any],
) -> dict[str, Any]:
    semantic_summary_short = (
        clean_text(llm_output.get("summary_short"))
        or projected["semantic_summary_short"]
    )
    semantic_summary_structured = (
        validate_summary_structured(
            inp.source_type,
            llm_output.get("summary_structured")
            if isinstance(llm_output.get("summary_structured"), dict)
            else None,
        )
        or projected["semantic_summary_structured"]
    )
    semantic_topics = _resolve_llm_topics(
        inp,
        projected["semantic_topics"],
        llm_output,
        raw_text=raw_text,
    )
    delta = _semantic_delta_breakdown(
        inp.source_type,
        projected_summary_short=projected["semantic_summary_short"],
        projected_summary_structured=projected["semantic_summary_structured"],
        projected_topics=projected["semantic_topics"],
        refined_summary_short=semantic_summary_short,
        refined_summary_structured=semantic_summary_structured,
        refined_topics=semantic_topics,
    )
    if not delta["delta_material"]:
        return dict(projected)

    confidence_fields = build_confidence_fields(
        inp.source_type,
        tags=inp.tags_flat or [],
        summary_structured=semantic_summary_structured,
        topics=semantic_topics,
        legal_entities=inp.legal_entities or [],
    )
    interpretation = float(
        confidence_fields.get("overall")
        or projected["interpretation_confidence_overall"]
        or 0.0
    )
    semantic_status = classify_enrichment_status(
        inp.source_type,
        used_fallback=False,
        tags=inp.tags_flat or [],
        summary_short=semantic_summary_short,
        summary_structured=semantic_summary_structured,
        topics=semantic_topics,
        legal_entities=inp.legal_entities or [],
        confidence_fields=confidence_fields,
    )
    quality_flags = derive_quality_flags(
        inp,
        summary_short=semantic_summary_short,
        summary_structured=semantic_summary_structured,
        topics=semantic_topics,
        confidence_overall=interpretation,
        semantic_status=semantic_status,
        semantic_mode="llm",
    )
    out = dict(projected)
    out.update(
        {
            "semantic_mode": "llm",
            "used_layers": ["heuristic", "llm"],
            "semantic_status": semantic_status,
            "semantic_summary_short": semantic_summary_short,
            "semantic_summary_structured": semantic_summary_structured,
            "semantic_topics": semantic_topics,
            "gate_decision": build_gate_decision(
                inp,
                quality_flags,
                confidence_overall=interpretation,
                semantic_status=semantic_status,
                semantic_mode="llm",
            ),
            "quality_flags": quality_flags,
            "interpretation_confidence_overall": interpretation,
        }
    )
    return out


def refine_semantic_projection_with_llm(
    inp: H3Input,
    projected: dict[str, Any],
    *,
    raw_text: str,
    model: str,
    llm_mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = build_h3_prompt(raw_text, inp)
    llm_output = call_local_llm(prompt=prompt, model=model, mode=llm_mode)
    candidate_summary_short = (
        clean_text(llm_output.get("summary_short"))
        or projected["semantic_summary_short"]
    )
    candidate_summary_structured = (
        validate_summary_structured(
            inp.source_type,
            llm_output.get("summary_structured")
            if isinstance(llm_output.get("summary_structured"), dict)
            else None,
        )
        or projected["semantic_summary_structured"]
    )
    candidate_topics = _resolve_llm_topics(
        inp,
        projected["semantic_topics"],
        llm_output,
        raw_text=raw_text,
    )
    delta = _semantic_delta_breakdown(
        inp.source_type,
        projected_summary_short=projected["semantic_summary_short"],
        projected_summary_structured=projected["semantic_summary_structured"],
        projected_topics=projected["semantic_topics"],
        refined_summary_short=candidate_summary_short,
        refined_summary_structured=candidate_summary_structured,
        refined_topics=candidate_topics,
    )
    refined = apply_h3_llm_output(
        inp, projected, raw_text=raw_text, llm_output=llm_output
    )
    meta = dict(llm_output.get("__meta") or {})
    meta.update(delta)
    meta["promoted"] = refined.get("semantic_mode") == "llm"
    return refined, meta
