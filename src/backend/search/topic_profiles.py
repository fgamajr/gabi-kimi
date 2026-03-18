"""Curated topic profiles for high-value DOU browse/search intents."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


_MATCH_STOPWORDS = frozenset(
    {
        "a",
        "as",
        "o",
        "os",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "para",
        "por",
        "com",
        "sobre",
        "publica",
        "publico",
        "publicas",
        "publicos",
    }
)


@dataclass(frozen=True)
class TopicProfile:
    id: str
    label: str
    query: str
    aliases: tuple[str, ...]
    intent: str = "trending_browse"
    required_groups: tuple[tuple[str, ...], ...] = ()
    should_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    required_art_types: tuple[str, ...] = ()
    preferred_art_types: tuple[tuple[str, float], ...] = ()
    excluded_art_types: tuple[str, ...] = ()
    preferred_sections: tuple[tuple[str, float], ...] = ()
    organ_boosts: tuple[tuple[str, float], ...] = ()
    recency_scale: str = "45d"
    recency_weight: float = 3.5
    pure_act_type: bool = False
    text_gate_mode: str = "expanded"

    def to_metadata(self) -> dict[str, Any]:
        data = asdict(self)
        data["aliases"] = list(self.aliases)
        data["required_groups"] = [list(group) for group in self.required_groups]
        data["should_terms"] = list(self.should_terms)
        data["exclude_terms"] = list(self.exclude_terms)
        data["required_art_types"] = list(self.required_art_types)
        data["preferred_art_types"] = [{"value": value, "weight": weight} for value, weight in self.preferred_art_types]
        data["excluded_art_types"] = list(self.excluded_art_types)
        data["preferred_sections"] = [{"value": value, "weight": weight} for value, weight in self.preferred_sections]
        data["organ_boosts"] = [{"value": value, "weight": weight} for value, weight in self.organ_boosts]
        data["pure_act_type"] = self.pure_act_type
        data["text_gate_mode"] = self.text_gate_mode
        return data


def _normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    normalized = unicodedata.normalize("NFD", lowered)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", normalized)


def _tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", _normalize_text(value)) if token not in _MATCH_STOPWORDS]


TOPIC_PROFILES: tuple[TopicProfile, ...] = (
    TopicProfile(
        id="concursos_publicos",
        label="Concursos Públicos",
        query="concurso publico",
        aliases=(
            "concurso",
            "concursos",
            "concurso publico",
            "concursos publicos",
            "edital concurso",
            "processo seletivo",
            "processo seletivo simplificado",
            "selecao publica",
            "seleção pública",
        ),
        required_groups=(
            (
                "concurso",
                "concursos",
                "processo seletivo",
                "processo seletivo simplificado",
                "selecao publica",
                "seleção pública",
            ),
        ),
        should_terms=(
            "edital",
            "retificacao",
            "retificação",
            "homologacao",
            "homologação",
            "resultado final",
            "inscricao",
            "inscrição",
            "candidato",
            "banca",
        ),
        exclude_terms=(
            "chamamento publico",
            "chamamento público",
            "consulta publica",
            "consulta pública",
            "licitacao",
            "licitação",
            "pregao",
            "pregão",
            "credenciamento",
            "leilao",
            "leilão",
        ),
        required_art_types=("edital", "aviso", "portaria"),
        preferred_art_types=(("edital", 8.0), ("aviso", 0.6), ("portaria", 0.4)),
        excluded_art_types=("extrato",),
        preferred_sections=(("DO3", 4.5),),
        organ_boosts=(("universidade", 2.5), ("instituto federal", 2.5), ("ebserh", 2.0), ("mec", 1.2)),
        recency_scale="30d",
        recency_weight=4.5,
    ),
    TopicProfile(
        id="licitacoes",
        label="Licitações",
        query="licitacao",
        aliases=(
            "licitacao",
            "licitacoes",
            "licitação",
            "licitações",
            "pregao",
            "pregão",
            "concorrencia",
            "concorrência",
            "aviso de licitacao",
            "aviso de licitação",
        ),
        required_groups=(("licitacao", "licitação", "pregao", "pregão", "concorrencia", "concorrência"),),
        should_terms=("edital", "pregao eletronico", "pregão eletrônico", "registro de precos", "registro de preços"),
        exclude_terms=("concurso publico", "concurso público", "consulta publica", "consulta pública"),
        required_art_types=("edital", "aviso", "extrato"),
        preferred_art_types=(("edital", 5.5), ("aviso", 4.5), ("extrato", 0.8)),
        preferred_sections=(("DO3", 4.0),),
        recency_scale="30d",
        recency_weight=4.0,
        pure_act_type=True,
        text_gate_mode="simple",
    ),
    TopicProfile(
        id="nomeacoes",
        label="Nomeações",
        query="nomeacao",
        aliases=("nomeacao", "nomeações", "nomeacao", "designacao", "exoneracao", "posse"),
        required_groups=(("nomeacao", "nomeação", "nomeacoes", "nomeações", "designacao", "designação"),),
        should_terms=("cargo", "comissionado", "funcao", "função", "das", "fcpe", "servidor"),
        exclude_terms=("concurso publico", "concurso público", "licitacao", "licitação", "consulta publica", "consulta pública"),
        required_art_types=("portaria", "decreto"),
        preferred_art_types=(("portaria", 5.0), ("decreto", 2.0)),
        preferred_sections=(("DO2", 4.0),),
        recency_scale="20d",
        recency_weight=3.0,
    ),
    TopicProfile(
        id="aposentadorias",
        label="Aposentadorias",
        query="aposentadoria",
        aliases=("aposentadoria", "aposentadorias", "pensao", "pensão", "pensoes", "pensões"),
        required_groups=(("aposentadoria", "aposentadorias", "pensao", "pensão", "pensoes", "pensões"),),
        should_terms=("servidor", "regime proprio", "regime próprio"),
        exclude_terms=("concurso publico", "concurso público", "licitacao", "licitação"),
        required_art_types=("portaria",),
        preferred_art_types=(("portaria", 4.0),),
        preferred_sections=(("DO2", 4.0),),
        recency_scale="20d",
        recency_weight=2.5,
    ),
    TopicProfile(
        id="consultas_publicas",
        label="Consultas Públicas",
        query="consulta publica",
        aliases=(
            "consulta publica",
            "consulta pública",
            "tomada de subsidios",
            "tomada de subsídios",
            "audiencia publica",
            "audiência pública",
        ),
        required_groups=(("consulta publica", "consulta pública", "tomada de subsidios", "tomada de subsídios"),),
        should_terms=("contribuicoes", "contribuições", "sociedade", "participacao social", "participação social"),
        exclude_terms=("concurso publico", "concurso público", "licitacao", "licitação", "nomeacao", "nomeação"),
        preferred_art_types=(("aviso", 5.0), ("resolucao", 3.0), ("portaria", 2.5)),
        preferred_sections=(("DO1", 3.0),),
        recency_scale="30d",
        recency_weight=4.0,
    ),
    TopicProfile(
        id="portarias_normativas",
        label="Portarias",
        query="portaria",
        aliases=("portaria", "portarias", "portaria normativa"),
        required_groups=(("portaria", "portarias"),),
        should_terms=("aprova", "institui", "altera", "regulamenta", "dispõe sobre", "dispoe sobre"),
        exclude_terms=(
            "nomeacao",
            "nomeação",
            "nomeacoes",
            "nomeações",
            "exoneracao",
            "exoneração",
            "ferias",
            "férias",
            "aposentadoria",
            "pensao",
            "pensão",
            "portaria de pessoal",
        ),
        required_art_types=("portaria",),
        preferred_art_types=(("portaria", 5.0),),
        preferred_sections=(("DO1", 3.5),),
        organ_boosts=(("ministerio", 1.0), ("agencia", 1.0), ("anvisa", 1.2), ("anpd", 1.2)),
        recency_scale="30d",
        recency_weight=3.5,
        pure_act_type=True,
    ),
    TopicProfile(
        id="decretos",
        label="Decretos",
        query="decreto",
        aliases=("decreto", "decretos", "decreto legislativo"),
        required_groups=(("decreto", "decretos"),),
        should_terms=("regulamenta", "altera", "dispõe sobre", "dispoe sobre", "promulga"),
        exclude_terms=("nomeacao", "nomeação", "exoneracao", "exoneração"),
        required_art_types=("decreto", "decreto-lei"),
        preferred_art_types=(("decreto", 6.0), ("decreto-lei", 3.5)),
        preferred_sections=(("DO1", 4.0),),
        organ_boosts=(("presidencia", 2.0), ("presidência", 2.0)),
        recency_scale="45d",
        recency_weight=3.5,
        pure_act_type=True,
    ),
    TopicProfile(
        id="resolucoes",
        label="Resoluções",
        query="resolucao",
        aliases=("resolucao", "resolucoes", "resolução", "resoluções"),
        required_groups=(("resolucao", "resoluções", "resolucao", "resolução"),),
        should_terms=("aprova", "altera", "regulamenta", "diretrizes", "norma"),
        exclude_terms=("concurso publico", "concurso público"),
        required_art_types=("resolucao",),
        preferred_art_types=(("resolucao", 6.0),),
        preferred_sections=(("DO1", 3.5),),
        organ_boosts=(("anvisa", 1.5), ("anpd", 1.5), ("cvm", 1.5), ("aneel", 1.5)),
        recency_scale="45d",
        recency_weight=3.2,
        pure_act_type=True,
    ),
    TopicProfile(
        id="lgpd_privacidade",
        label="LGPD e Privacidade",
        query="protecao de dados",
        aliases=(
            "protecao de dados",
            "proteção de dados",
            "dados pessoais",
            "privacidade",
            "anpd",
            "lgpd anpd",
        ),
        intent="subject_explore",
        required_groups=(("protecao de dados", "proteção de dados", "dados pessoais", "privacidade", "anpd"),),
        should_terms=("tratamento de dados", "controlador", "operador", "incidente de seguranca", "incidente de segurança"),
        preferred_art_types=(("resolucao", 4.5), ("instrucao normativa", 4.0), ("lei", 3.5)),
        preferred_sections=(("DO1", 2.5),),
        organ_boosts=(("anpd", 3.5),),
        recency_scale="120d",
        recency_weight=2.0,
    ),
    TopicProfile(
        id="banco_central",
        label="Banco Central",
        query="banco central",
        aliases=("banco central", "bacen", "pix", "selic", "circular bacen"),
        intent="subject_explore",
        required_groups=(("banco central", "bacen", "pix", "selic"),),
        should_terms=("circular", "resolucao bcb", "resolução bcb", "comunicado"),
        preferred_art_types=(("resolucao", 3.5), ("instrucao normativa", 2.5), ("aviso", 1.5)),
        organ_boosts=(("banco central", 4.0), ("bacen", 4.0)),
        recency_scale="120d",
        recency_weight=2.0,
    ),
    TopicProfile(
        id="saude_publica",
        label="Saúde Pública",
        query="saude publica",
        aliases=("saude publica", "saúde pública", "sus", "ministerio da saude", "ministério da saúde", "anvisa"),
        intent="subject_explore",
        required_groups=(("saude", "saúde", "sus", "ministerio da saude", "ministério da saúde", "anvisa"),),
        should_terms=("vigilancia sanitaria", "vigilância sanitária", "assistencia farmaceutica", "assistência farmacêutica"),
        preferred_art_types=(("portaria", 3.0), ("resolucao", 3.0), ("instrucao normativa", 2.0)),
        organ_boosts=(("ministerio da saude", 3.0), ("anvisa", 3.5)),
        recency_scale="90d",
        recency_weight=2.0,
    ),
    TopicProfile(
        id="educacao",
        label="Educação",
        query="educacao",
        aliases=("educacao", "educação", "mec", "enem", "sisu", "fies", "instituto federal"),
        intent="subject_explore",
        required_groups=(("educacao", "educação", "mec", "enem", "sisu", "fies", "instituto federal"),),
        should_terms=("universidade", "bolsa", "ensino", "campus"),
        preferred_art_types=(("edital", 2.5), ("portaria", 2.0), ("resolucao", 2.0)),
        organ_boosts=(("mec", 3.0), ("ministerio da educacao", 3.0), ("universidade", 2.0), ("instituto federal", 2.0)),
        recency_scale="90d",
        recency_weight=2.0,
    ),
)


_EXACT_ALIAS_INDEX: dict[str, TopicProfile] = {}
for _profile in TOPIC_PROFILES:
    for _alias in (_profile.query, *_profile.aliases, _profile.label):
        _EXACT_ALIAS_INDEX[_normalize_text(_alias)] = _profile


def match_topic_profile(query: str) -> TopicProfile | None:
    normalized_query = _normalize_text(query)
    if not normalized_query:
        return None

    exact = _EXACT_ALIAS_INDEX.get(normalized_query)
    if exact:
        return exact

    query_tokens = set(_tokenize(normalized_query))
    if len(query_tokens) < 2:
        return None

    best_profile: TopicProfile | None = None
    best_score = 0.0
    for profile in TOPIC_PROFILES:
        for alias in (profile.query, *profile.aliases, profile.label):
            alias_tokens = set(_tokenize(alias))
            if not alias_tokens:
                continue
            overlap = len(query_tokens & alias_tokens) / max(len(alias_tokens), len(query_tokens))
            contains = query_tokens.issubset(alias_tokens) or alias_tokens.issubset(query_tokens)
            score = overlap + (0.2 if contains else 0.0)
            if overlap >= 0.66 and score > best_score:
                best_profile = profile
                best_score = score

    return best_profile
