from __future__ import annotations

from typing import Any


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    cases.extend(_bolsa_alimentacao_cases())
    cases.extend(_procurement_cases())
    cases.extend(_organ_type_cases())
    cases.extend(_person_phrase_cases())
    cases.extend(_legal_concept_cases())
    cases.extend(_semantic_paraphrase_cases())
    cases.extend(_broad_filter_cases())
    assert len(cases) == 100, f"expected 100 cases, got {len(cases)}"
    return cases


def _case(
    *,
    case_id: str,
    category: str,
    query: str,
    filters: dict[str, Any] | None = None,
    title_contains: list[str] | None = None,
    body_contains: list[str] | None = None,
    exact_phrase: str | None = None,
    expected_min_results: int = 1,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": case_id,
        "category": category,
        "query": query,
        "filters": filters or {},
        "relevance_hints": {
            "title_contains": title_contains or [],
            "body_contains": body_contains or [],
            "exact_phrase": exact_phrase or "",
            "expected_min_results": expected_min_results,
            "notes": notes,
        },
    }


def _bolsa_alimentacao_cases() -> list[dict[str, Any]]:
    filters = {"date_from": "2002-01-01", "date_to": "2002-12-31"}
    titles = ["BOLSA-ALIMENTAÇÃO", "BOLSA ALIMENTAÇÃO"]
    body = ["qualifica municípios", "programa bolsa-alimentação", "bolsa-alimentação"]
    queries = [
        "bolsa alimentação ministério da saúde",
        "bolsa-alimentação ministério da saúde",
        "municípios qualificados bolsa alimentação",
        "atos sobre municípios qualificados no bolsa alimentação",
        "programa bolsa alimentação saúde 2002",
        "portarias sobre bolsa alimentação em 2002",
        "qualificação de municípios bolsa alimentação",
        "municípios integrar programa bolsa alimentação",
        "portaria ministério da saúde bolsa alimentação",
        "documentos sobre bolsa-alimentação e municípios",
        "municípios qualificados para o programa bolsa alimentação",
        "atos de qualificação de municípios bolsa alimentação",
        "programa bolsa-alimentação ministério da saúde 2002",
        "bolsa alimentação municípios portaria 2002",
        "quais portarias qualificam municípios no programa bolsa alimentação",
        "qualifica municípios para integrar o programa bolsa-alimentação",
    ]
    return [
        _case(
            case_id=f"bolsa-{i:02d}",
            category="bolsa_alimentacao",
            query=query,
            filters=filters,
            title_contains=titles,
            body_contains=body,
            notes="Target should surface Ministry of Health portarias on Bolsa-Alimentacao municipal qualification.",
        )
        for i, query in enumerate(queries, start=1)
    ]


def _procurement_cases() -> list[dict[str, Any]]:
    filters = {"date_from": "2002-01-01", "date_to": "2002-12-31", "section": "do3"}
    body = ["pregão", "pregão eletrônico", "licitação", "aviso de licitação", "compra pública"]
    queries = [
        "compra pública por meio eletrônico",
        "pregão eletrônico 2002 do3",
        "avisos de licitação eletrônica",
        "contratação pública eletrônica",
        "pregão e aviso de licitação do3",
        "aquisição pública por pregão eletrônico",
        "compra governamental eletrônica",
        "licitacao por meio eletronico",
        "pregões eletrônicos e avisos de licitação",
        "procedimentos de compra pública eletrônica",
        "licitações eletrônicas em 2002",
        "processos de compra pública no do3",
        "documentos sobre pregão eletrônico",
        "compra pública eletrônica no diário oficial",
        "pregão do3 2002",
        "aviso de licitação do3 2002",
    ]
    return [
        _case(
            case_id=f"proc-{i:02d}",
            category="procurement_do3",
            query=query,
            filters=filters,
            title_contains=["PREGÃO", "AVISO DE LICITAÇÃO"],
            body_contains=body,
            notes="Target procurement-style documents in DO3; semantic retrieval should help on paraphrases.",
        )
        for i, query in enumerate(queries, start=1)
    ]


def _organ_type_cases() -> list[dict[str, Any]]:
    themes = [
        (
            "Ministério da Saúde",
            "portaria",
            "2002-01-01",
            "2002-12-31",
            [
                "portaria ministério da saúde 2002",
                "atos do ministério da saúde tipo portaria",
                "portarias emitidas pelo ministério da saúde",
                "publicações do ministério da saúde em portaria",
            ],
        ),
        (
            "Ministério da Justiça",
            "portaria",
            "2002-10-01",
            "2002-10-31",
            [
                "portarias do ministério da justiça em outubro de 2002",
                "ministério da justiça outubro 2002 portaria",
                "atos do ministério da justiça tipo portaria em outubro",
                "portaria ministério da justiça outubro 2002",
            ],
        ),
        (
            "Ministério da Fazenda",
            "ato",
            "2002-08-01",
            "2002-08-31",
            [
                "atos do ministério da fazenda agosto 2002",
                "ato ministério da fazenda agosto de 2002",
                "publicações do ministério da fazenda tipo ato",
                "atos fazenda agosto 2002",
            ],
        ),
        (
            "Ministério da Educação",
            "portaria",
            "2002-01-01",
            "2002-12-31",
            [
                "portarias do ministério da educação em 2002",
                "atos do ministério da educação portaria",
                "portaria mec 2002",
                "documentos do ministério da educação tipo portaria",
            ],
        ),
    ]
    cases: list[dict[str, Any]] = []
    index = 1
    for organ, art_type, start, end, queries in themes:
        for query in queries:
            cases.append(
                _case(
                    case_id=f"orgtype-{index:02d}",
                    category="organ_type_filters",
                    query=query,
                    filters={
                        "date_from": start,
                        "date_to": end,
                        "art_type": art_type,
                        "issuing_organ": organ,
                    },
                    body_contains=[organ.lower(), art_type.lower()],
                    notes="Hard filter case; top results should respect exact organ/type constraints.",
                )
            )
            index += 1
    return cases


def _person_phrase_cases() -> list[dict[str, Any]]:
    return [
        _case(
            case_id="person-01",
            category="person_exact_phrase",
            query='"Fernando Lima Gama"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Fernando Lima Gama",
            title_contains=["ANEXO CONCURSO PÚBLICO PARA ANALISTA DE FINANCAS E CONTROLE - AFC"],
            notes="Exact phrase should isolate the known 2002 occurrence.",
        ),
        _case(
            case_id="person-02",
            category="person_exact_phrase",
            query="Fernando Lima Gama",
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Fernando Lima Gama",
            body_contains=["Fernando Lima Gama"],
        ),
        _case(
            case_id="person-03",
            category="person_exact_phrase",
            query='"Fernando Henrique Cardoso"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Fernando Henrique Cardoso",
            body_contains=["Fernando Henrique Cardoso"],
        ),
        _case(
            case_id="person-04",
            category="person_exact_phrase",
            query="Fernando Henrique Cardoso",
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            body_contains=["Fernando Henrique Cardoso"],
        ),
        _case(
            case_id="person-05",
            category="person_exact_phrase",
            query='"Luiz Inácio Lula da Silva"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Luiz Inácio Lula da Silva",
            body_contains=["Lula", "Luiz Inácio Lula da Silva"],
        ),
        _case(
            case_id="person-06",
            category="person_exact_phrase",
            query='"José Serra"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="José Serra",
            body_contains=["José Serra"],
        ),
        _case(
            case_id="person-07",
            category="person_exact_phrase",
            query='"Roseana Sarney"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Roseana Sarney",
            body_contains=["Roseana Sarney"],
        ),
        _case(
            case_id="person-08",
            category="person_exact_phrase",
            query='"Ciro Gomes"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Ciro Gomes",
            body_contains=["Ciro Gomes"],
        ),
        _case(
            case_id="person-09",
            category="person_exact_phrase",
            query='"Geraldo Alckmin"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Geraldo Alckmin",
            body_contains=["Geraldo Alckmin"],
        ),
        _case(
            case_id="person-10",
            category="person_exact_phrase",
            query='"Anthony Garotinho"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Anthony Garotinho",
            body_contains=["Anthony Garotinho"],
        ),
        _case(
            case_id="person-11",
            category="person_exact_phrase",
            query='"Marina Silva"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="Marina Silva",
            body_contains=["Marina Silva"],
        ),
        _case(
            case_id="person-12",
            category="person_exact_phrase",
            query='"José Dirceu"',
            filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
            exact_phrase="José Dirceu",
            body_contains=["José Dirceu"],
        ),
    ]


def _legal_concept_cases() -> list[dict[str, Any]]:
    themes = [
        ("naturalização", ["naturalização", "naturalizacao"], ["naturalização"]),
        ("utilidade pública federal", ["utilidade pública federal", "utilidade publica federal"], ["utilidade pública"]),
        ("anvisa e medicamentos", ["ANVISA", "medicamentos"], ["ANVISA", "medicamento"]),
        ("decretos presidenciais delegação posse", ["decreto", "presidencial", "delegação", "posse"], ["decreto"]),
    ]
    query_sets = [
        "atos sobre naturalização publicados em 2002",
        "documentos sobre naturalização em 2002",
        "publicações sobre naturalização",
        "atos sobre utilidade pública federal em 2002",
        "publicações sobre utilidade pública federal",
        "anvisa medicamentos 2002",
        "publicações sobre anvisa e medicamentos",
        "decretos presidenciais de agosto de 2002 sobre delegação ou posse presidencial",
        "delegação presidencial agosto 2002",
        "posse presidencial decreto 2002",
        "atos federais sobre utilidade pública",
        "documentos sobre naturalizacao",
    ]
    cases: list[dict[str, Any]] = []
    for i, query in enumerate(query_sets, start=1):
        if "natural" in query:
            title, body = themes[0][1], themes[0][2]
        elif "utilidade" in query:
            title, body = themes[1][1], themes[1][2]
        elif "anvisa" in query.lower() or "medic" in query.lower():
            title, body = themes[2][1], themes[2][2]
        else:
            title, body = themes[3][1], themes[3][2]
        cases.append(
            _case(
                case_id=f"concept-{i:02d}",
                category="legal_concepts",
                query=query,
                filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
                title_contains=title,
                body_contains=body,
            )
        )
    return cases


def _semantic_paraphrase_cases() -> list[dict[str, Any]]:
    queries = [
        "quais atos qualificam municípios no programa bolsa alimentação",
        "quais documentos tratam de compra pública por meio eletrônico",
        "atos sobre municípios habilitados para bolsa alimentação",
        "documentos de aquisição pública eletrônica",
        "quais publicações falam de pregão eletrônico",
        "atos de qualificação municipal em programa alimentar",
        "publicações sobre contratação pública digital",
        "portarias que habilitam municípios para programa alimentar",
        "compra governamental feita por pregão eletrônico",
        "atos referentes a licitação eletrônica",
        "quais textos tratam de anvisa e medicamentos",
        "quais documentos falam de utilidade pública federal",
        "textos sobre naturalização em 2002",
        "atos relacionados a posse presidencial",
        "portarias do ministério da saúde sobre bolsa alimentação",
        "documentos de compra pública no do3",
    ]
    cases: list[dict[str, Any]] = []
    for i, query in enumerate(queries, start=1):
        body = []
        if "aliment" in query or "municíp" in query or "municip" in query:
            body = ["bolsa-alimentação", "qualifica municípios"]
        elif "compra" in query or "pregão" in query or "licit" in query:
            body = ["pregão", "licitação", "compra pública"]
        elif "anvisa" in query or "medic" in query:
            body = ["ANVISA", "medicamento"]
        elif "utilidade" in query:
            body = ["utilidade pública"]
        elif "natural" in query:
            body = ["naturalização"]
        else:
            body = ["decreto", "posse", "delegação"]
        cases.append(
            _case(
                case_id=f"sem-{i:02d}",
                category="semantic_paraphrase",
                query=query,
                filters={"date_from": "2002-01-01", "date_to": "2002-12-31"},
                body_contains=body,
                notes="Paraphrase-heavy semantic recall case.",
            )
        )
    return cases


def _broad_filter_cases() -> list[dict[str, Any]]:
    queries = [
        ("licitação", {"date_from": "2002-01-01", "date_to": "2002-12-31"}, ["licitação", "aviso", "pregão"]),
        ("aviso licitação", {"date_from": "2002-01-01", "date_to": "2002-12-31", "section": "do3"}, ["aviso", "licitação"]),
        ("pregão", {"date_from": "2002-01-01", "date_to": "2002-12-31", "section": "do3"}, ["pregão"]),
        ("portaria saúde", {"date_from": "2002-01-01", "date_to": "2002-12-31", "art_type": "portaria"}, ["portaria", "saúde"]),
    ]
    cases: list[dict[str, Any]] = []
    for i, (query, filters, body) in enumerate(queries, start=1):
        for variant in range(1, 3 + 1):
            cases.append(
                _case(
                    case_id=f"broad-{i:02d}-{variant}",
                    category="broad_filter",
                    query=query if variant == 1 else f"{query} 2002" if variant == 2 else f"{query} diário oficial",
                    filters=filters,
                    body_contains=body,
                    notes="Broad filter sanity case; checks stable retrieval under common operator queries.",
                )
            )
    return cases
