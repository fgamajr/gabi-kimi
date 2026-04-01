from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.backend.search.intent import QueryIntent


class TestQueryClassification:
    def test_immutability(self) -> None:
        from src.backend.answering.classifier import QueryClassification

        c = QueryClassification(query_type="exact_match", confidence=0.95)
        with pytest.raises(AttributeError):
            c.query_type = "exploratory"

    def test_default_values(self) -> None:
        from src.backend.answering.classifier import QueryClassification

        c = QueryClassification(query_type="exact_match", confidence=0.95)
        assert c.source == "rule"
        assert c.used_llm_fallback is False
        assert c.facets == ()
        assert c.gabi_intent is None


class TestRiskAssessment:
    def test_immutability(self) -> None:
        from src.backend.answering.classifier import RiskAssessment

        r = RiskAssessment(flags=("low_context",), score=0.2, safe_mode=False)
        with pytest.raises(AttributeError):
            r.score = 0.5

    def test_safe_mode_true_when_threshold_met(self) -> None:
        from src.backend.answering.classifier import RiskAssessment

        r = RiskAssessment(
            flags=("low_context", "multi_evidence_required"), score=0.5, safe_mode=True
        )
        assert r.safe_mode is True

    def test_safe_mode_false_when_below_threshold(self) -> None:
        from src.backend.answering.classifier import RiskAssessment

        r = RiskAssessment(flags=("low_context",), score=0.3, safe_mode=False)
        assert r.safe_mode is False


class TestDetectFacets:
    def test_hierarchical_secao(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("ementa da seção 3.1")
        assert "hierarchical" in facets

    def test_hierarchical_item(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("item ii do artigo 5")
        assert "hierarchical" in facets

    def test_subscope_inciso(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("inciso II do artigo 5º")
        assert "subscope" in facets

    def test_subscope_alinea(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("alínea b do inciso I")
        assert "subscope" in facets

    def test_exact_reference_quoted(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets('"Lei 13709 de 2018"')
        assert "exact_reference" in facets

    def test_exact_reference_legal_ref(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("portaria 1234/2024")
        assert "exact_reference" in facets

    def test_multiple_facets(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("seção 2.1, inciso I")
        assert "hierarchical" in facets
        assert "subscope" in facets

    def test_no_facets(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("portarias do MEC em 2025")
        assert "hierarchical" not in facets
        assert "subscope" not in facets
        assert "exact_reference" not in facets

    def test_empty_query(self) -> None:
        from src.backend.answering.classifier import _detect_facets

        facets = _detect_facets("")
        assert facets == ()


class TestGabiIntentToQueryType:
    def test_exact_name_maps_to_exact_match(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            gabi_intent_to_query_type,
        )

        result = gabi_intent_to_query_type(
            gabi_intent=QueryIntent.EXACT_NAME,
            classification=QueryClassification(
                query_type="exact_match", confidence=0.95
            ),
        )
        assert result.query_type == "exact_match"
        assert result.confidence >= 0.95

    def test_canonical_lookup_maps_to_legal_reference(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            gabi_intent_to_query_type,
        )

        result = gabi_intent_to_query_type(
            gabi_intent=QueryIntent.CANONICAL_LOOKUP,
            classification=QueryClassification(
                query_type="legal_reference", confidence=0.90
            ),
        )
        assert result.query_type == "legal_reference"
        assert result.confidence >= 0.90

    def test_person_name_maps_to_exact_match(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            gabi_intent_to_query_type,
        )

        result = gabi_intent_to_query_type(
            gabi_intent=QueryIntent.PERSON_NAME,
            classification=QueryClassification(
                query_type="exact_match", confidence=0.90
            ),
        )
        assert result.query_type == "exact_match"

    def test_trending_browse_maps_to_exploratory(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            gabi_intent_to_query_type,
        )

        result = gabi_intent_to_query_type(
            gabi_intent=QueryIntent.TRENDING_BROWSE,
            classification=QueryClassification(
                query_type="exploratory", confidence=0.80
            ),
        )
        assert result.query_type == "exploratory"
        assert result.confidence == 0.80

    def test_subject_explore_maps_to_exploratory(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            gabi_intent_to_query_type,
        )

        result = gabi_intent_to_query_type(
            gabi_intent=QueryIntent.SUBJECT_EXPLORE,
            classification=QueryClassification(
                query_type="exploratory", confidence=0.50
            ),
        )
        assert result.query_type == "exploratory"
        assert result.confidence == 0.50

    def test_gabi_intent_preserved(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            gabi_intent_to_query_type,
        )

        result = gabi_intent_to_query_type(
            gabi_intent=QueryIntent.EXACT_NAME,
            classification=QueryClassification(
                query_type="exact_match", confidence=0.95
            ),
        )
        assert result.gabi_intent == QueryIntent.EXACT_NAME


class TestRegexClassification:
    @pytest.mark.parametrize(
        "query,expected_type",
        [
            ('"Portaria 1234/2024"', "exact_match"),
            ("port. MEC 234", "exact_match"),
            ("Lei 13709", "exact_match"),
        ],
    )
    def test_exact_match_queries(self, query: str, expected_type: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == expected_type
        assert result.confidence == 0.95

    @pytest.mark.parametrize(
        "query",
        [
            "quantas portarias do MEC foram publicadas?",
            "quantas licitações abertas em 2025?",
            "qual o número total de decrees?",
            "liste todas as nomeações",
        ],
    )
    def test_aggregation_keywords(self, query: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == "aggregation"
        assert result.confidence == 0.9

    @pytest.mark.parametrize(
        "query",
        [
            "resuma as principais medidas",
            "faça um resumo da portaria",
            "síntese do decreto",
        ],
    )
    def test_summary_keywords(self, query: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == "summary"
        assert result.confidence == 0.9

    @pytest.mark.parametrize(
        "query",
        [
            "quais são as evidências?",
            "prova documental",
            "comprovação de despesa",
            "base probatória",
        ],
    )
    def test_evidential_keywords(self, query: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == "evidential"
        assert result.confidence == 0.9

    @pytest.mark.parametrize(
        "query",
        [
            "cite a legislação aplicável",
            "norma sobre licitações",
            "decreto 9000",
        ],
    )
    def test_legal_reference_keywords(self, query: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == "legal_reference"
        assert result.confidence == 0.9

    @pytest.mark.parametrize(
        "query",
        [
            "quem é o responsável?",
            "responsabilidade do gestor",
            "quem ficou responsável pela omissão",
        ],
    )
    def test_accountability_keywords(self, query: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == "accountability"
        assert result.confidence == 0.88

    @pytest.mark.parametrize(
        "query",
        [
            "qual a recomendação?",
            "proposta de solução",
            "plano de ação recomendado",
        ],
    )
    def test_recommendation_keywords(self, query: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == "recommendation"
        assert result.confidence == 0.88

    @pytest.mark.parametrize(
        "query",
        [
            "quais são os riscos?",
            "causas do problema",
            "efeitos da medida",
        ],
    )
    def test_factual_keywords(self, query: str) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification(query)
        assert result.query_type == "factual"
        assert result.confidence == 0.85

    def test_exploratory_fallback(self) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification("políticas de educação")
        assert result.query_type == "exploratory"
        assert result.confidence == 0.6

    def test_empty_query_returns_exploratory(self) -> None:
        from src.backend.answering.classifier import _regex_classification

        result = _regex_classification("")
        assert result.query_type == "exploratory"
        assert result.confidence == 0.6


class TestAssessQueryRisk:
    def test_aggregation_with_low_results(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="aggregation", confidence=0.9, facets=()
        )
        risk = assess_query_risk(
            query="quantas portarias?",
            classification=classification,
            result_count=2,
        )
        assert "multi_evidence_required" in risk.flags
        assert "aggregation_precision_risk" in risk.flags
        assert "low_context" in risk.flags
        assert risk.score > 0.5
        assert risk.safe_mode is True

    def test_exact_match_no_risk_flags(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="exact_match", confidence=0.95, facets=()
        )
        risk = assess_query_risk(
            query="portaria 1234",
            classification=classification,
            result_count=5,
            conflict=False,
            score_margin=0.15,
        )
        assert risk.score == 0.0
        assert risk.safe_mode is False

    def test_ranking_ambiguity_triggered(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="exploratory", confidence=0.6, facets=()
        )
        risk = assess_query_risk(
            query="políticas públicas",
            classification=classification,
            result_count=5,
            score_margin=0.05,
        )
        assert "ranking_ambiguity" in risk.flags

    def test_ranking_ambiguity_not_triggered_at_threshold(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="exploratory", confidence=0.6, facets=()
        )
        risk = assess_query_risk(
            query="políticas públicas",
            classification=classification,
            result_count=5,
            score_margin=0.08,
        )
        assert "ranking_ambiguity" not in risk.flags

    def test_cross_source_conflict(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="legal_reference", confidence=0.9, facets=()
        )
        risk = assess_query_risk(
            query="norma do TCU vs DOU",
            classification=classification,
            conflict=True,
        )
        assert "cross_source_conflict" in risk.flags

    def test_corpus_stale_flag(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="legal_reference", confidence=0.9, facets=()
        )
        risk = assess_query_risk(
            query="legislação atual",
            classification=classification,
            corpus_stale=True,
        )
        assert "corpus_stale" in risk.flags

    def test_hierarchical_facet_triggers_flag(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="factual", confidence=0.85, facets=("hierarchical",)
        )
        risk = assess_query_risk(
            query="seção 3.1 do documento",
            classification=classification,
        )
        assert "hierarchical_query" in risk.flags

    def test_score_capped_at_one(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="aggregation",
            confidence=0.9,
            facets=("hierarchical", "subscope"),
        )
        risk = assess_query_risk(
            query="subachado 2.1 do achado 1",
            classification=classification,
            result_count=1,
            conflict=True,
            score_margin=0.03,
            corpus_stale=True,
        )
        assert risk.score <= 1.0

    def test_safe_mode_threshold_configurable(self) -> None:
        from src.backend.answering.classifier import (
            QueryClassification,
            assess_query_risk,
        )

        classification = QueryClassification(
            query_type="exploratory", confidence=0.6, facets=()
        )
        risk = assess_query_risk(
            query="teste",
            classification=classification,
            result_count=4,
            score_margin=0.1,
        )
        assert risk.score < 0.5
        assert risk.safe_mode is False


class TestClassifyQueryIntegration:
    def test_full_pipeline_aggregation(self) -> None:
        from src.backend.answering.classifier import QueryClassification, classify_query

        result = classify_query("quantas portarias do MEC foram publicadas em 2025?")
        assert isinstance(result, QueryClassification)
        assert result.query_type == "aggregation"
        assert result.confidence == 0.9

    def test_full_pipeline_exact_match(self) -> None:
        from src.backend.answering.classifier import classify_query

        result = classify_query('"Portaria 1234/2024"')
        assert result.query_type == "exact_match"
        assert result.confidence == 0.95

    def test_full_pipeline_facets_attached(self) -> None:
        from src.backend.answering.classifier import classify_query

        result = classify_query('"Lei 13709" portaria 1234')
        assert len(result.facets) > 0

    def test_empty_query_defensive(self) -> None:
        from src.backend.answering.classifier import classify_query

        result = classify_query("")
        assert result.query_type == "exploratory"
        assert result.confidence == 0.6


class TestAdaptiveQueryClassifier:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.ledger_root = Path(self.temp_dir)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_register_feedback_invalid_correct_type(self) -> None:
        from src.backend.answering.classifier import AdaptiveQueryClassifier

        classifier = AdaptiveQueryClassifier(ledger_root=self.ledger_root)
        with pytest.raises(ValueError, match="Unsupported query type"):
            classifier.register_feedback(
                query="test query",
                predicted="exploratory",
                correct="invalid_type",
                confidence=0.5,
                source="test",
            )

    def test_register_feedback_invalid_predicted_type(self) -> None:
        from src.backend.answering.classifier import AdaptiveQueryClassifier

        classifier = AdaptiveQueryClassifier(ledger_root=self.ledger_root)
        with pytest.raises(ValueError, match="Unsupported query type"):
            classifier.register_feedback(
                query="test query",
                predicted="invalid_type",
                correct="exploratory",
                confidence=0.5,
                source="test",
            )

    def test_register_feedback_writes_to_file(self) -> None:
        from src.backend.answering.classifier import AdaptiveQueryClassifier

        classifier = AdaptiveQueryClassifier(ledger_root=self.ledger_root)
        classifier.register_feedback(
            query="test query",
            predicted="exploratory",
            correct="legal_reference",
            confidence=0.5,
            source="test",
        )

        feedback_path = self.ledger_root / "query_feedback.jsonl"
        assert feedback_path.exists()
        with open(feedback_path, encoding="utf-8") as f:
            line = f.readline()
        row = json.loads(line)
        assert row["query"] == "test query"
        assert row["predicted"] == "exploratory"
        assert row["correct"] == "legal_reference"

    def test_learn_returns_empty_when_disabled(self) -> None:
        from src.backend.answering.classifier import AdaptiveQueryClassifier

        classifier = AdaptiveQueryClassifier(
            ledger_root=self.ledger_root, enabled=False
        )
        result = classifier.learn()
        assert result == {}

    def test_patterns_returns_current_dict(self) -> None:
        from src.backend.answering.classifier import AdaptiveQueryClassifier

        classifier = AdaptiveQueryClassifier(ledger_root=self.ledger_root)
        patterns = classifier.patterns()
        assert isinstance(patterns, dict)

    def test_feedback_history(self) -> None:
        from src.backend.answering.classifier import AdaptiveQueryClassifier

        classifier = AdaptiveQueryClassifier(ledger_root=self.ledger_root)
        classifier.register_feedback(
            query="query1",
            predicted="exploratory",
            correct="legal_reference",
            confidence=0.5,
            source="test",
        )
        classifier.register_feedback(
            query="query2",
            predicted="exploratory",
            correct="aggregation",
            confidence=0.6,
            source="test",
        )

        history = classifier.feedback_history(limit=10)
        assert len(history) == 2

    def test_singleton_across_calls(self) -> None:
        from src.backend.answering.classifier import get_query_classifier

        classifier1 = get_query_classifier()
        classifier2 = get_query_classifier()
        assert classifier1 is classifier2
