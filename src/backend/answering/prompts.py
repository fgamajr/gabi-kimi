from __future__ import annotations

SYSTEM_PROMPT = """\
Você é assistente de pesquisa jurídica especializado no Diário Oficial da União (DOU) \
e acórdãos do Tribunal de Contas da União (TCU).

REGRAS ABSOLUTAS:
1. Responda APENAS com base nos documentos recuperados fornecidos abaixo.
2. Cada afirmação factual DEVE ser seguida de uma citação no formato [ID_DO_DOCUMENTO].
3. NUNCA invente citações, nomes de normas, números de portarias ou datas.
4. Se os documentos não contiverem informação suficiente para responder, diga: \
"Não encontrei documentos suficientes para responder com segurança."
5. Responda em português brasileiro.
6. Seja conciso e objetivo — auditores precisam de respostas diretas.
"""

SAFE_MODE_SUFFIX = """
MODO SEGURO ATIVADO: Esta consulta tem alto risco de imprecisão.
- Prefira incompletude a especulação.
- Indique explicitamente lacunas nas evidências.
- Não sintetize além do que os documentos afirmam diretamente.
"""

_TASK_TEMPLATES: dict[str, str] = {
    "exact_match": """\
Localize o documento específico mencionado na consulta e forneça:
- Número, tipo e data da norma
- Órgão emissor
- Ementa ou descrição principal
- Citação obrigatória: [ID_DO_DOCUMENTO]

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "aggregation": """\
Responda à consulta de contagem ou listagem com base nos documentos fornecidos.
- Forneça o total encontrado nos documentos abaixo (não extrapole para o corpus inteiro)
- Liste os itens com citação obrigatória: [ID_DO_DOCUMENTO]
- Inclua nota: "Esta contagem reflete apenas os documentos recuperados nesta busca."

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "summary": """\
Elabore uma síntese dos documentos fornecidos sobre o tema da consulta.
- Use subtítulos para organizar a síntese
- Cite cada ponto com [ID_DO_DOCUMENTO]
- Ao final, liste os principais documentos consultados

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "factual": """\
Responda à pergunta factual utilizando os documentos fornecidos.
- Resposta direta no primeiro parágrafo
- Fundamentação com citações [ID_DO_DOCUMENTO]
- Se houver informações contraditórias entre documentos, sinalize explicitamente

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "exploratory": """\
Explore o tema da consulta com base nos documentos fornecidos.
- Apresente os principais aspectos encontrados
- Cite cada ponto com [ID_DO_DOCUMENTO]
- Sugira subtemas relacionados presentes nos documentos

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "evidential": """\
Identifique e apresente as evidências documentais relevantes para a consulta.
- Liste cada evidência com localização precisa [ID_DO_DOCUMENTO]
- Indique o grau de relevância de cada documento
- Sinalize lacunas probatórias explicitamente

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "legal_reference": """\
Analise a legislação e normas relevantes encontradas nos documentos.
- Identifique a norma principal com número, data e ementa [ID_DO_DOCUMENTO]
- Liste normas relacionadas ou que a alteraram/revogaram [ID_DO_DOCUMENTO]
- Indique vigência quando disponível nos documentos

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "accountability": """\
Identifique responsabilidades institucionais e pessoais com base nos documentos.
- Nomeie órgãos e responsáveis apenas quando explicitamente mencionados nos documentos
- Cite cada atribuição com [ID_DO_DOCUMENTO]
- Não atribua responsabilidade além do que está documentado

Consulta: {query}

Documentos recuperados:
{evidence}
""",
    "recommendation": """\
Com base nos documentos fornecidos, sintetize recomendações e propostas encontradas.
- Identifique recomendações explícitas nos documentos [ID_DO_DOCUMENTO]
- Distinga recomendações normativas de sugestões interpretativas
- Prefixe sínteses interpretativas com [SÍNTESE]

Consulta: {query}

Documentos recuperados:
{evidence}
""",
}

_DEFAULT_TEMPLATE = _TASK_TEMPLATES["factual"]


def build_user_prompt(
    query: str,
    evidence_text: str,
    query_type: str,
    *,
    safe_mode: bool = False,
) -> str:
    template = _TASK_TEMPLATES.get(query_type, _DEFAULT_TEMPLATE)
    prompt = template.format(query=query, evidence=evidence_text)
    if safe_mode:
        prompt = prompt + "\n" + SAFE_MODE_SUFFIX
    return prompt
