"""Unit tests for search adapter query translation and normalization.

Run:
    python3 tests/test_search_adapters.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.backend.search.adapters import ESSearchAdapter, HybridSearchAdapter, SearchConfig, create_search_adapter
from src.backend.search.adapters import _lexical_query_clause


_passed = 0
_failed = 0


def _assert(condition: bool, msg: str) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f"FAIL: {msg}", file=sys.stderr)


def test_es_search_translation_and_normalization() -> None:
    captured: dict = {}
    adapter = ESSearchAdapter(
        url="http://localhost:9200",
        index="gabi_documents_v1",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
    )

    def fake_request(method: str, path: str, payload: dict | None = None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {
            "hits": {
                "total": {"value": 2},
                "hits": [
                    {
                        "_id": "uuid-1",
                        "_score": 9.5,
                        "_source": {
                            "doc_id": "uuid-1",
                            "identifica": "PORTARIA TESTE",
                            "ementa": "Ementa",
                            "art_type": "portaria",
                            "pub_date": "2026-02-01",
                            "edition_section": "do1",
                            "body_plain": "texto completo",
                        },
                        "highlight": {"body_plain": [">>>texto<<< completo"]},
                    },
                    {
                        "_id": "uuid-2",
                        "_score": 5.0,
                        "_source": {
                            "doc_id": "uuid-2",
                            "identifica": "DECRETO TESTE",
                            "ementa": "Outra ementa",
                            "art_type": "decreto",
                            "pub_date": "2026-02-02",
                            "edition_section": "do1",
                            "body_plain": "corpo sem highlight",
                        },
                    },
                ],
            }
        }

    adapter._request = fake_request  # type: ignore[attr-defined]
    out = adapter.search(
        query="portaria saude",
        page_size=10,
        page=2,
        date_from="2026-01-01",
        date_to="2026-12-31",
        section="do1",
        art_type="portaria",
        issuing_organ="Ministério da Saúde",
    )

    _assert(captured["method"] == "POST", "uses POST")
    _assert(captured["path"] == "/gabi_documents_v1/_search", "uses index search path")
    _assert(captured["payload"]["from"] == 10, "uses from pagination")
    filters = captured["payload"]["query"]["bool"]["filter"]
    _assert(any("range" in f for f in filters), "adds date range filter")
    _assert(any("edition_section.keyword" in f.get("term", {}) for f in filters), "adds section filter")
    _assert(any("art_type.keyword" in f.get("term", {}) for f in filters), "adds art_type filter")
    _assert(any("issuing_organ.keyword" in f.get("term", {}) for f in filters), "adds issuing_organ filter")
    _assert(out["total"] == 2, "normalizes total")
    _assert(out["results"][0]["snippet"] == ">>>texto<<< completo", "uses highlight snippet")
    _assert(out["results"][1]["snippet"] == "corpo sem highlight", "falls back to body snippet")


def test_lexical_query_clause_boosts_exact_phrase_in_body() -> None:
    clause = _lexical_query_clause('"Fernando Lima Gama"')
    should = clause["bool"]["should"]

    phrase_matches = [item["match_phrase"] for item in should if "match_phrase" in item]
    body_match = next((item["body_plain"] for item in phrase_matches if "body_plain" in item), None)
    identifica_match = next((item["identifica"] for item in phrase_matches if "identifica" in item), None)

    _assert(body_match is not None, "adds exact phrase match on body_plain")
    _assert(body_match["query"] == "Fernando Lima Gama", "strips wrapping quotes for phrase matching")
    _assert(float(body_match["boost"]) >= 20.0, "gives strong boost to exact body phrase")
    _assert(identifica_match is not None, "adds exact phrase match on identifica")


def test_es_browse_mode_uses_match_all() -> None:
    captured: dict = {}
    adapter = ESSearchAdapter(
        url="http://localhost:9200",
        index="idx",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
    )

    def fake_request(method: str, path: str, payload: dict | None = None):
        captured["payload"] = payload
        return {"hits": {"total": {"value": 0}, "hits": []}}

    adapter._request = fake_request  # type: ignore[attr-defined]
    out = adapter.search(query="*", page_size=5, page=1)

    must = captured["payload"]["query"]["bool"]["must"]
    _assert(must == [{"match_all": {}}], "browse mode uses match_all")
    _assert("highlight" not in captured["payload"], "browse mode does not request highlight")
    _assert(out["results"] == [], "empty results")


def test_es_search_infers_section_and_art_type_from_query() -> None:
    captured: dict = {}
    adapter = ESSearchAdapter(
        url="http://localhost:9200",
        index="idx",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
    )

    def fake_request(method: str, path: str, payload: dict | None = None):
        captured["payload"] = payload
        return {"hits": {"total": {"value": 0}, "hits": []}}

    adapter._request = fake_request  # type: ignore[attr-defined]
    out = adapter.search(query="documentos de compra pública no do3 e pregão eletrônico", page_size=5, page=1)

    filters = captured["payload"]["query"]["bool"]["filter"]
    should = captured["payload"]["query"]["bool"]["must"][0]["bool"]["should"]
    first_query = should[0]["simple_query_string"]["query"]
    _assert(
        any(
            "edition_section.keyword" in f.get("term", {})
            and f["term"]["edition_section.keyword"] == "do3"
            for f in filters
        ),
        "infers do3 section filter from query",
    )
    _assert(
        any(
            "art_type.keyword" in f.get("term", {})
            and f["term"]["art_type.keyword"] == "pregão"
            for f in filters
        ),
        "infers art_type from query",
    )
    _assert("do3" not in first_query.lower(), "removes inline section token from lexical query text")
    _assert(out["inferred_filters"]["section"] == "do3", "reports inferred section in payload")
    _assert(out["inferred_filters"]["art_type"] == "pregão", "reports inferred art_type in payload")
    _assert(out["interpreted_query"] != out["query"], "exposes interpreted query separately from original query")


def test_es_search_infers_issuing_organ_from_query() -> None:
    captured: dict = {}
    adapter = ESSearchAdapter(
        url="http://localhost:9200",
        index="idx",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
    )

    def fake_request(method: str, path: str, payload: dict | None = None):
        captured["payload"] = payload
        return {"hits": {"total": {"value": 0}, "hits": []}}

    adapter._request = fake_request  # type: ignore[attr-defined]
    out = adapter.search(query="portarias do ministério da saúde sobre bolsa alimentação", page_size=5, page=1)

    filters = captured["payload"]["query"]["bool"]["filter"]
    _assert(
        any(
            "issuing_organ.keyword" in f.get("term", {})
            and f["term"]["issuing_organ.keyword"] == "Ministério da Saúde"
            for f in filters
        ),
        "infers issuing organ from query",
    )
    _assert(
        any(
            "art_type.keyword" in f.get("term", {})
            and f["term"]["art_type.keyword"] == "portaria"
            for f in filters
        ),
        "infers portaria art_type from query",
    )
    _assert(out["inferred_filters"]["issuing_organ"] == "Ministério da Saúde", "reports inferred issuing organ")


def test_hybrid_rrf_merge_prefers_dual_signal_docs() -> None:
    adapter = HybridSearchAdapter(
        url="http://localhost:9200",
        index="gabi_documents_v1",
        chunks_index="gabi_chunks_v1",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
        lexical_k=10,
        vector_k=10,
        num_candidates=20,
        rrf_k=60,
        rerank_provider="none",
        rerank_top_n=0,
    )

    adapter._lexical_candidates = lambda **kwargs: (  # type: ignore[method-assign]
        [
            {
                "doc_id": "doc-a",
                "bm25_rank": 1,
                "bm25_score": 12.0,
                "identifica": "Portaria A",
                "ementa": "A",
                "art_type": "portaria",
                "pub_date": "2002-01-01",
                "edition_section": "do1",
                "issuing_organ": "Ministerio A",
                "snippet": "lex a",
            },
            {
                "doc_id": "doc-b",
                "bm25_rank": 2,
                "bm25_score": 10.0,
                "identifica": "Portaria B",
                "ementa": "B",
                "art_type": "portaria",
                "pub_date": "2002-01-02",
                "edition_section": "do1",
                "issuing_organ": "Ministerio B",
                "snippet": "lex b",
            },
        ],
        2,
    )
    adapter._vector_candidates = lambda **kwargs: [  # type: ignore[method-assign]
        {
            "doc_id": "doc-b",
            "vector_rank": 1,
            "vector_score": 0.91,
            "vector_chunk_id": "chunk-b",
            "vector_snippet": "vec b",
        },
        {
            "doc_id": "doc-c",
            "vector_rank": 2,
            "vector_score": 0.82,
            "vector_chunk_id": "chunk-c",
            "vector_snippet": "vec c",
        },
    ]
    adapter._fetch_doc_sources = lambda doc_ids: {  # type: ignore[method-assign]
        "doc-c": {
            "doc_id": "doc-c",
            "identifica": "Portaria C",
            "ementa": "C",
            "art_type": "portaria",
            "pub_date": "2002-01-03",
            "edition_section": "do1",
            "issuing_organ": "Ministerio C",
            "body_plain": "body c",
        }
    }

    out = adapter.search(query="portaria teste", page_size=10, page=1)
    ids = [row["doc_id"] for row in out["results"]]

    _assert(out["backend"] == "hybrid", "hybrid adapter reports backend")
    _assert(ids[0] == "doc-b", "doc with lexical + vector signals ranks first")
    _assert(ids[1] == "doc-a", "strong lexical-only doc ranks after dual-signal doc")
    _assert(ids[2] == "doc-c", "vector-only doc is retained in merged set")


def test_hybrid_exact_phrase_query_filters_noise() -> None:
    adapter = HybridSearchAdapter(
        url="http://localhost:9200",
        index="gabi_documents_v1",
        chunks_index="gabi_chunks_v1",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
        lexical_k=10,
        vector_k=10,
        num_candidates=20,
        rrf_k=60,
        rerank_provider="none",
        rerank_top_n=0,
    )

    adapter._lexical_candidates = lambda **kwargs: (  # type: ignore[method-assign]
        [
            {
                "doc_id": "doc-hit",
                "bm25_rank": 1,
                "bm25_score": 50.0,
                "identifica": "ANEXO",
                "ementa": "",
                "art_type": "anexo",
                "pub_date": "2002-05-09",
                "edition_section": "do3",
                "issuing_organ": "Ministério da Fazenda",
                "snippet": ">>>FERNANDO LIMA GAMA<<<",
            },
            {
                "doc_id": "doc-noise",
                "bm25_rank": 2,
                "bm25_score": 10.0,
                "identifica": "ATA",
                "ementa": "",
                "art_type": "ata",
                "pub_date": "2002-01-18",
                "edition_section": "do1",
                "issuing_organ": "Outro órgão",
                "snippet": "FERNANDO ... LIMA ...",
            },
        ],
        2,
    )
    adapter._vector_candidates = lambda **kwargs: [  # type: ignore[method-assign]
        {
            "doc_id": "doc-noise",
            "vector_rank": 1,
            "vector_score": 0.9,
            "vector_chunk_id": "chunk-noise",
            "vector_snippet": "texto sem frase exata",
        }
    ]
    adapter._fetch_doc_sources = lambda doc_ids: {  # type: ignore[method-assign]
        "doc-hit": {
            "doc_id": "doc-hit",
            "identifica": "ANEXO",
            "ementa": "",
            "art_type": "anexo",
            "pub_date": "2002-05-09",
            "edition_section": "do3",
            "issuing_organ": "Ministério da Fazenda",
            "body_plain": "FERNANDO LIMA GAMA aprovado",
        },
        "doc-noise": {
            "doc_id": "doc-noise",
            "identifica": "ATA",
            "ementa": "",
            "art_type": "ata",
            "pub_date": "2002-01-18",
            "edition_section": "do1",
            "issuing_organ": "Outro órgão",
            "body_plain": "Fernando ... Lima ... Gama",
        },
    }

    out = adapter.search(query='"Fernando Lima Gama"', page_size=10, page=1)
    ids = [row["doc_id"] for row in out["results"]]

    _assert(ids == ["doc-hit"], "exact phrase query keeps only exact textual matches")
    _assert(out["total"] == 1, "exact phrase query total matches filtered results")


def test_create_search_adapter_supports_hybrid() -> None:
    cfg = SearchConfig(
        backend="hybrid",
        pg_dsn="host=localhost",
        es_url="http://localhost:9200",
        es_index="gabi_documents_v1",
        es_chunks_index="gabi_chunks_v1",
        es_username=None,
        es_password=None,
        es_verify_tls=False,
        es_timeout_sec=5,
        hybrid_lexical_k=20,
        hybrid_vector_k=20,
        hybrid_num_candidates=60,
        hybrid_rrf_k=60,
        rerank_provider="none",
        rerank_top_n=0,
    )
    adapter = create_search_adapter(cfg)
    _assert(isinstance(adapter, HybridSearchAdapter), "factory returns hybrid adapter")


def test_basic_rerank_prefers_vector_procurement_doc_over_bm25_noise() -> None:
    adapter = HybridSearchAdapter(
        url="http://localhost:9200",
        index="gabi_documents_v1",
        chunks_index="gabi_chunks_v1",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
        lexical_k=10,
        vector_k=10,
        num_candidates=20,
        rrf_k=60,
        rerank_provider="basic",
        rerank_top_n=10,
    )
    query = "quais documentos tratam de compra pública por meio eletrônico"
    bm25_noise = {
        "identifica": "EDITAL DE AUDIÊNCIA PÚBLICA OPERAÇÕES REALIZADAS POR MEIO DA INTERNET",
        "snippet": "audiência pública por meio da internet",
        "retrieval_mode": "bm25",
        "art_type": "edital",
        "issuing_organ": "Ministério da Fazenda",
    }
    vector_hit = {
        "identifica": "PREGÃO ELETRÔNICO Nº 2231/2002",
        "vector_snippet": "pregão eletrônico para aquisição pública e licitação",
        "retrieval_mode": "vector",
        "art_type": "pregão",
        "issuing_organ": "Ministério da Educação",
    }
    _assert(
        adapter._basic_rerank(query, vector_hit) > adapter._basic_rerank(query, bm25_noise),
        "semantic procurement query prefers vector procurement hit over lexical noise",
    )


def test_basic_rerank_prefers_bolsa_municipios_portaria_over_bolsa_noise() -> None:
    adapter = HybridSearchAdapter(
        url="http://localhost:9200",
        index="gabi_documents_v1",
        chunks_index="gabi_chunks_v1",
        username=None,
        password=None,
        verify_tls=False,
        timeout_sec=5,
        lexical_k=10,
        vector_k=10,
        num_candidates=20,
        rrf_k=60,
        rerank_provider="basic",
        rerank_top_n=10,
    )
    query = "atos sobre municípios habilitados para bolsa alimentação"
    bm25_noise = {
        "identifica": "EDITAL DE BOLSA ALIMENTAÇÃO E MORADIA ESTUDANTIL",
        "snippet": "programas bolsa alimentação e moradia estudantil",
        "retrieval_mode": "bm25",
        "art_type": "edital",
        "issuing_organ": "Ministério da Educação",
    }
    vector_hit = {
        "identifica": "PORTARIA Nº 166, DE 24 DE JANEIRO DE 2002",
        "vector_snippet": "qualifica municípios para integrar o programa bolsa-alimentação",
        "retrieval_mode": "vector",
        "art_type": "portaria",
        "issuing_organ": "Ministério da Saúde",
    }
    _assert(
        adapter._basic_rerank(query, vector_hit) > adapter._basic_rerank(query, bm25_noise),
        "bolsa alimentação paraphrase prefers qualifying municipalities portaria",
    )


def main() -> int:
    test_es_search_translation_and_normalization()
    test_lexical_query_clause_boosts_exact_phrase_in_body()
    test_es_browse_mode_uses_match_all()
    test_es_search_infers_section_and_art_type_from_query()
    test_es_search_infers_issuing_organ_from_query()
    test_hybrid_rrf_merge_prefers_dual_signal_docs()
    test_hybrid_exact_phrase_query_filters_noise()
    test_create_search_adapter_supports_hybrid()
    test_basic_rerank_prefers_vector_procurement_doc_over_bm25_noise()
    test_basic_rerank_prefers_bolsa_municipios_portaria_over_bolsa_noise()

    total = _passed + _failed
    print(f"\nsearch adapter tests: {total} total, {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
