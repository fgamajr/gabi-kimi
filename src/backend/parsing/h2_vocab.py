from __future__ import annotations

from typing import Final

ALLOWED_TAGS_VERSION: Final[str] = "1.0.0"

# Source-of-truth stays in code for deterministic validation/versioning.
SOURCE_ALLOWED_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "dou_documents": (
        "identifica",
        "ementa",
        "fundamentacao_legal",
        "vigencia",
        "corpo",
        "objeto",
        "datas",
        "valores",
        "atores",
    ),
    "tcu_acordao_completo": (
        "sumario",
        "relatorio",
        "voto",
        "acordao",
        "dispositivo",
        "fundamentacao",
        "base_legal",
        "decisao",
    ),
    "tcu_jurisprudencia_selecionada": (
        "enunciado",
        "excerto",
        "fundamentacao",
        "tese",
        "base_legal",
    ),
    "tcu_resposta_consulta": (
        "pergunta",
        "resposta",
        "fundamentacao",
        "base_legal",
    ),
    "tcu_sumula": (
        "enunciado",
        "vigencia",
        "base_legal",
    ),
    "tcu_boletim_jurisprudencia": (
        "enunciado",
        "texto_acordao",
        "fundamentacao",
        "decisao",
    ),
    "tcu_boletim_pessoal": (
        "enunciado",
        "texto_acordao",
        "efeito_administrativo",
    ),
    "tcu_boletim_informativo_lc": (
        "enunciado",
        "texto_info",
        "texto_acordao",
        "fundamentacao",
    ),
    "tcu_normas": (
        "titulo",
        "texto_norma",
        "texto_anexo",
        "vigencia",
        "base_legal",
    ),
    "tcu_btcu": (
        "section_title",
        "texto_completo",
        "acordaos_citados",
        "base_legal",
        "decisao",
    ),
    "tcu_publicacoes": (
        "title",
        "description",
        "body_plain",
        "recomendacoes",
        "base_legal",
    ),
}


def tags_for_source(source_type: str) -> tuple[str, ...]:
    return SOURCE_ALLOWED_TAGS.get(source_type, tuple())
