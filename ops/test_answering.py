"""Tests for the RAG answer pipeline.

Run with:
    python ops/test_answering.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if (_REPO_ROOT / "src").is_dir():
    sys.path.insert(0, str(_REPO_ROOT))
else:
    sys.path.insert(0, "/workspace")


class TestClassifier(unittest.TestCase):
    def _classify(self, query: str):
        from src.backend.answering.classifier import classify_query

        return classify_query(query)

    def test_exact_match_portaria(self):
        r = self._classify("Portaria 1234 do MEC de 2024")
        self.assertEqual(r.query_type, "exact_match")
        self.assertGreater(r.confidence, 0.8)

    def test_aggregation_quantas(self):
        r = self._classify("quantas portarias publicou o MEC em 2025?")
        self.assertEqual(r.query_type, "aggregation")

    def test_aggregation_quantidade(self):
        r = self._classify("quantidade de licitações suspensas no DOU em março")
        self.assertEqual(r.query_type, "aggregation")

    def test_summary_resumo(self):
        r = self._classify("resuma as normas sobre teletrabalho no serviço público")
        self.assertEqual(r.query_type, "summary")

    def test_evidential_evidencias(self):
        r = self._classify("quais evidências comprovam irregularidades no contrato?")
        self.assertEqual(r.query_type, "evidential")

    def test_legal_reference_lei(self):
        r = self._classify("lei 14133 sobre licitações e contratos administrativos")
        self.assertEqual(r.query_type, "legal_reference")

    def test_accountability_responsavel(self):
        r = self._classify("quem é o responsável pela fiscalização do contrato?")
        self.assertEqual(r.query_type, "accountability")

    def test_recommendation_proposta(self):
        r = self._classify(
            "proposta de recomendação para melhoria dos controles internos"
        )
        self.assertEqual(r.query_type, "recommendation")

    def test_exploratory_fallback(self):
        r = self._classify("governo federal transparência")
        self.assertEqual(r.query_type, "exploratory")

    def test_empty_query(self):
        r = self._classify("")
        self.assertEqual(r.query_type, "exploratory")


class TestRiskAssessment(unittest.TestCase):
    def test_safe_mode_high_risk(self):
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        cls = QueryClassification(
            query_type="aggregation",
            confidence=0.9,
            facets=("hierarchical",),
        )
        risk = assess_query_risk("test", cls, corpus_stale=True)
        self.assertTrue(risk.safe_mode)
        self.assertGreaterEqual(risk.score, 0.5)

    def test_low_risk_exact_match(self):
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        cls = QueryClassification(query_type="exact_match", confidence=0.95)
        risk = assess_query_risk("test", cls, result_count=10)
        self.assertFalse(risk.safe_mode)

    def test_low_context_flag(self):
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        cls = QueryClassification(query_type="factual", confidence=0.85)
        risk = assess_query_risk("test", cls, result_count=1)
        self.assertIn("low_context", risk.flags)

    def test_corpus_stale_flag(self):
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        cls = QueryClassification(query_type="factual", confidence=0.85)
        risk = assess_query_risk("test", cls, corpus_stale=True)
        self.assertIn("corpus_stale", risk.flags)


class TestCitations(unittest.TestCase):
    def test_valid_citation_extracted(self):
        from src.backend.answering.citations import extract_and_validate_citations

        docs = [{"_id": "DOU-2024-001", "_source": {"issuing_organ": "MEC"}}]
        text = "A portaria foi publicada [DOU-2024-001] conforme regulamento."
        citations, hallucinated = extract_and_validate_citations(text, docs)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].doc_id, "DOU-2024-001")
        self.assertEqual(hallucinated, 0)

    def test_hallucinated_citation_removed(self):
        from src.backend.answering.citations import extract_and_validate_citations

        docs = [{"_id": "DOU-2024-001", "_source": {}}]
        text = "Ver [DOU-2024-001] e também [INVENTED-999]."
        citations, hallucinated = extract_and_validate_citations(text, docs)
        self.assertEqual(len(citations), 1)
        self.assertEqual(hallucinated, 1)

    def test_no_citations(self):
        from src.backend.answering.citations import extract_and_validate_citations

        docs = [{"_id": "DOU-2024-001", "_source": {}}]
        text = "Texto sem citações."
        citations, hallucinated = extract_and_validate_citations(text, docs)
        self.assertEqual(len(citations), 0)
        self.assertEqual(hallucinated, 0)

    def test_duplicate_citations_deduped(self):
        from src.backend.answering.citations import extract_and_validate_citations

        docs = [{"_id": "DOU-2024-001", "_source": {}}]
        text = "Ver [DOU-2024-001] e também [DOU-2024-001] novamente."
        citations, hallucinated = extract_and_validate_citations(text, docs)
        self.assertEqual(len(citations), 1)


class TestAggregation(unittest.TestCase):
    def test_dedup_identical_titles(self):
        from src.backend.answering.aggregation import deduplicate_docs

        docs = [
            {"_source": {"title": "Portaria 100 do MEC"}},
            {"_source": {"title": "Portaria 100 do MEC"}},
            {"_source": {"title": "Portaria 200 do MEC"}},
        ]
        result = deduplicate_docs(docs)
        self.assertEqual(len(result), 2)

    def test_group_by_organ(self):
        from src.backend.answering.aggregation import group_by_organ

        docs = [
            {"_source": {"issuing_organ": "MEC", "title": "A"}},
            {"_source": {"issuing_organ": "MEC", "title": "B"}},
            {"_source": {"issuing_organ": "MS", "title": "C"}},
        ]
        groups = group_by_organ(docs)
        self.assertEqual(len(groups["MEC"]), 2)
        self.assertEqual(len(groups["MS"]), 1)

    def test_aggregation_summary_structure(self):
        from src.backend.answering.aggregation import build_aggregation_summary

        docs = [
            {"_source": {"issuing_organ": "MEC", "art_type": "Portaria", "title": "A"}},
            {"_source": {"issuing_organ": "MS", "art_type": "Portaria", "title": "B"}},
        ]
        summary = build_aggregation_summary(docs, "quantas portarias?")
        self.assertIn("total_retrieved", summary)
        self.assertIn("by_organ", summary)
        self.assertIn("by_type", summary)
        self.assertIn("note", summary)


class TestPrompts(unittest.TestCase):
    def test_all_query_types_have_template(self):
        from src.backend.answering.classifier import QUERY_TYPES
        from src.backend.answering.prompts import _TASK_TEMPLATES

        for qt in QUERY_TYPES:
            self.assertIn(qt, _TASK_TEMPLATES, f"Missing template for {qt}")

    def test_safe_mode_suffix_added(self):
        from src.backend.answering.prompts import SAFE_MODE_SUFFIX, build_user_prompt

        prompt = build_user_prompt("test query", "evidence", "factual", safe_mode=True)
        self.assertIn(SAFE_MODE_SUFFIX.strip()[:20], prompt)

    def test_query_and_evidence_in_prompt(self):
        from src.backend.answering.prompts import build_user_prompt

        prompt = build_user_prompt("minha consulta", "minha evidência", "factual")
        self.assertIn("minha consulta", prompt)
        self.assertIn("minha evidência", prompt)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=".", pattern="test_answering.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(
        unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    )
    sys.exit(0 if result.wasSuccessful() else 1)
