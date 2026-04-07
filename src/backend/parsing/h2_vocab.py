from __future__ import annotations

from typing import Final

ALLOWED_TAGS_VERSION: Final[str] = "1.1.0"

# Source-of-truth stays in code for deterministic validation/versioning.
SOURCE_ALLOWED_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "dou_documents": (
        "identifica",
        "ementa",
        "fundamento_legal",
        "vigencia",
        "corpo",
        "processo",
        "assinatura",
    ),
    "tcu_acordao_completo": (
        "sumario",
        "relatorio",
        "voto",
        "acordao",
        "decisao",
        "referencia_legal",
        "processo",
        "assinatura",
    ),
    "tcu_jurisprudencia_selecionada": (
        "enunciado",
        "excerto",
        "referencia_legal",
        "indexacao",
        "processo",
        "assinatura",
    ),
    "tcu_resposta_consulta": (
        "pergunta",
        "resposta",
        "enunciado",
        "excerto",
        "referencia_legal",
        "indexacao",
        "processo",
        "assinatura",
    ),
    "tcu_sumula": (
        "enunciado",
        "excerto",
        "referencia_legal",
        "processo",
        "assinatura",
    ),
    "tcu_boletim_jurisprudencia": (
        "titulo",
        "enunciado",
        "texto_acordao",
        "referencia_legal",
        "processo",
        "assinatura",
    ),
    "tcu_boletim_pessoal": (
        "titulo",
        "enunciado",
        "texto_acordao",
        "referencia_legal",
        "processo",
        "assinatura",
    ),
    "tcu_boletim_informativo_lc": (
        "titulo",
        "enunciado",
        "texto_info",
        "texto_acordao",
        "referencia_legal",
        "processo",
        "assinatura",
    ),
    "tcu_normas": (
        "titulo",
        "assunto",
        "texto_norma",
        "texto_anexo",
        "normas_relacionadas",
        "processo",
        "assinatura",
    ),
    "tcu_btcu": (
        "section_title",
        "assunto",
        "texto_completo",
        "acordaos_citados",
        "base_legal",
        "processo",
        "assinatura",
    ),
    "tcu_publicacoes": (
        "title",
        "description",
        "body_plain",
        "referencia_legal",
        "processo",
        "assinatura",
    ),
}


def tags_for_source(source_type: str) -> tuple[str, ...]:
    return SOURCE_ALLOWED_TAGS.get(source_type, tuple())
