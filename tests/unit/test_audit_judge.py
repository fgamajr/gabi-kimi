from __future__ import annotations

from src.backend.parsing import audit_judge
from src.backend.parsing.audit_judge import (
    JUDGE_CONTRACT_VERSION,
    JUDGE_PROMPT_VERSION,
    JudgeDimension,
    PanelOpinion,
    judge_item,
    panel_healthcheck,
)


def _response(agent: str, provider: str, model: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "agent": agent,
        "provider": provider,
        "model": model,
        "latency_ms": 12.0,
        "output": __import__("json").dumps(payload, ensure_ascii=False),
    }


def _expert_payload(verdict: str = "approved") -> dict[str, object]:
    return {
        "final_verdict": verdict,
        "confidence": 0.9,
        "dimension_scores": {
            "summary_fidelity": {"score": 0.92, "rationale": "ok"},
            "topics_precision": {"score": 0.85, "rationale": "ok"},
            "status_correctness": {"score": 0.90, "rationale": "ok"},
            "entities_coverage": {"score": 0.88, "rationale": "ok"},
            "semantic_consistency": {"score": 0.91, "rationale": "ok"},
        },
        "major_issues": ["none"],
        "short_rationale": "fine",
    }


def _jury_payload(verdict: str = "approved") -> dict[str, object]:
    return {
        "final_verdict": verdict,
        "confidence": 0.9,
        "dimension_scores": {
            "summary_fidelity": {"score": 0.93, "rationale": "ok"},
            "topics_precision": {"score": 0.87, "rationale": "ok"},
            "status_correctness": {"score": 0.91, "rationale": "ok"},
            "entities_coverage": {"score": 0.89, "rationale": "ok"},
            "semantic_consistency": {"score": 0.92, "rationale": "ok"},
        },
        "blocking_issues": [],
        "summary_rationale": "looks good",
    }


def test_panel_healthcheck_requires_non_dashscope_for_official(monkeypatch) -> None:
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_ENABLED", True)
    monkeypatch.setattr(audit_judge.settings, "DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setattr(audit_judge.settings, "GEMINI_API_KEY", "")
    summary = panel_healthcheck("official_judge")
    assert not summary["ready"]
    assert "missing_non_dashscope_provider" in summary["errors"]


def test_judge_item_uses_cached_experts_and_returns_majority_verdict(monkeypatch) -> None:
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_ENABLED", True)
    monkeypatch.setattr(audit_judge.settings, "DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setattr(audit_judge.settings, "GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(audit_judge.settings, "GEMINI_API_MODELS", "gemini-2.0-flash")
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_ENABLE_GEMINI", True)
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_REQUIRE_MIN_EXPERTS", 3)
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_REQUIRE_MIN_JURORS", 2)

    cached = {
        "kimi-k2.5": PanelOpinion(
            role="expert",
            agent_name="kimi-k2.5",
            provider="cached",
            model_id="kimi-k2.5",
            final_verdict="approved",
            dimensions={key: JudgeDimension(score=0.9, rationale="cached") for key in audit_judge.JUDGE_DIMENSIONS},
            confidence=0.9,
            issues=(),
            rationale="cached",
            latency_ms=0.0,
            raw_response={"cached": True},
        )
    }

    calls: list[list[str]] = []

    async def _fake_panel_agents(specs, prompt_builder):
        calls.append([spec.model for spec in specs])
        if len(specs) >= 4:
            return [
                _response(spec.model, spec.provider, spec.model, _expert_payload())
                for spec in specs
            ]
        return [
            _response(spec.model, spec.provider, spec.model, _jury_payload("approved"))
            for spec in specs
        ]

    monkeypatch.setattr(audit_judge, "_call_panel_agents", _fake_panel_agents)

    verdict = judge_item(
        source_type="dou_documents",
        parsed_row={"raw_id": "1", "summary_short": "abc"},
        semantic_row={"raw_id": "1", "semantic_summary_short": "abc"},
        raw_row={"id": "1", "texto": "conteúdo"},
        judge_mode="shadow_judge",
        cached_expert_opinions=cached,
    )

    assert verdict.status == "judged"
    assert verdict.final_verdict == "approved"
    assert verdict.prompt_version == JUDGE_PROMPT_VERSION
    assert verdict.judge_method == "panel_jury"
    assert JUDGE_CONTRACT_VERSION == "audit_panel_jury_v1"
    assert "kimi-k2.5" not in calls[0]
    assert "gemini-2.0-flash" in calls[0]
    assert calls[1]


def test_judge_item_returns_pending_when_jury_quorum_fails(monkeypatch) -> None:
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_ENABLED", True)
    monkeypatch.setattr(audit_judge.settings, "DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setattr(audit_judge.settings, "GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(audit_judge.settings, "GEMINI_API_MODELS", "gemini-2.0-flash")
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_ENABLE_GEMINI", True)
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_REQUIRE_MIN_EXPERTS", 3)
    monkeypatch.setattr(audit_judge.settings, "AUDIT_PANEL_REQUIRE_MIN_JURORS", 2)

    async def _fake_panel_agents(specs, prompt_builder):
        if len(specs) > 3:
            return [_response(spec.model, spec.provider, spec.model, _expert_payload()) for spec in specs]
        return [
            _response(specs[0].model, specs[0].provider, specs[0].model, _jury_payload("approved")),
            {"agent": specs[1].model, "provider": specs[1].provider, "model": specs[1].model, "output": "", "latency_ms": 0.0, "error": "timeout"},
        ]

    monkeypatch.setattr(audit_judge, "_call_panel_agents", _fake_panel_agents)

    verdict = judge_item(
        source_type="tcu_jurisprudencia_selecionada",
        parsed_row={"raw_id": "1"},
        semantic_row=None,
        raw_row={"id": "1"},
        judge_mode="shadow_judge",
    )
    assert verdict.status == "pending_judge"
    assert not verdict.quorum_ok
