from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

try:
    from .config import DEFAULT_CONFIG_PATH, ROOT_DIR, available_agents, config_summary, load_runtime_config
    from .diffing import unified_diff
    from .engine import ConvergenceEngine, _extract_json_object, _parse_review
    from .models import ProviderResponse, UsageStats
    from .selection import select_agents
except ImportError:
    from config import DEFAULT_CONFIG_PATH, ROOT_DIR, available_agents, config_summary, load_runtime_config
    from diffing import unified_diff
    from engine import ConvergenceEngine, _extract_json_object, _parse_review
    from models import ProviderResponse, UsageStats
    from selection import select_agents


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    os.environ.setdefault("DASHSCOPE_API_KEY", "test-dashscope-key")
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
    cfg = load_runtime_config(DEFAULT_CONFIG_PATH)

    assert "claude" in cfg.agents
    assert "dashscope" in cfg.providers
    assert cfg.defaults.max_rounds == 5

    summary = config_summary(cfg)
    assert "providers" in summary
    assert "agents" in summary

    selection = select_agents(
        "Use only Claude and Qwen for this security review.",
        cfg,
    )
    assert selection.reviewers == ["claude", "qwen"]
    assert selection.personas["claude"] in {"security", "general"}

    diff_text = unified_diff("a\nb\n", "a\nc\n")
    assert "--- before" in diff_text
    assert "+++ after" in diff_text

    raw = json.dumps(
        {
            "verdict": "APPROVE",
            "objections": [],
            "suggestions": [],
            "diffs": [],
            "meta": {"tokens_used": 10},
        }
    )
    review = _parse_review(raw, "kimi", 1)
    assert review.verdict == "APPROVE"
    assert review.meta["tokens_used"] == 10

    fenced = "```json\n{\"verdict\":\"REQUEST_CHANGES\",\"objections\":[],\"suggestions\":[],\"diffs\":[],\"meta\":{}}\n```"
    parsed = _extract_json_object(fenced)
    assert parsed["verdict"] == "REQUEST_CHANGES"

    missing = available_agents(cfg)
    assert isinstance(missing, list)

    engine = ConvergenceEngine(str(DEFAULT_CONFIG_PATH))

    class FakeAdapter:
        def __init__(self, name: str) -> None:
            self.name = name

        def complete(self, messages, *, enable_thinking: bool, stream: bool):
            if "Return exactly one JSON object" in messages[-1]["content"]:
                if self.name == "claude":
                    content = json.dumps(
                        {
                            "verdict": "REQUEST_CHANGES",
                            "objections": [
                                {
                                    "severity": "high",
                                    "location": "artifact:1",
                                    "description": "Need stronger naming",
                                    "suggested_fix": "rename x to total",
                                }
                            ],
                            "suggestions": [],
                            "diffs": [],
                            "meta": {},
                        }
                    )
                else:
                    content = json.dumps(
                        {
                            "verdict": "APPROVE",
                            "objections": [],
                            "suggestions": [],
                            "diffs": [],
                            "meta": {},
                        }
                    )
                return ProviderResponse(content=content, usage=UsageStats(total_tokens=12))
            return ProviderResponse(content="def total():\n    return 1\n", usage=UsageStats(total_tokens=7))

    original_factory = engine._dispatch_reviews.__globals__["create_adapter"]
    original_orchestrate_factory = engine._orchestrate.__globals__["create_adapter"]
    engine._dispatch_reviews.__globals__["create_adapter"] = lambda provider, agent: FakeAdapter(agent.name)
    engine._orchestrate.__globals__["create_adapter"] = lambda provider, agent: FakeAdapter(agent.name)
    try:
        run = engine.run(
            user_prompt="Use only Claude and Qwen for this security review.",
            initial_artifact="def x():\n    return 1\n",
            artifact_kind="code",
            max_rounds=2,
            run_label="selftest",
        )
    finally:
        engine._dispatch_reviews.__globals__["create_adapter"] = original_factory
        engine._orchestrate.__globals__["create_adapter"] = original_orchestrate_factory

    assert run.run_id
    assert run.rounds
    assert Path(run.run_dir).exists()
    assert run.final_artifact.startswith("def total")

    print("dev-mcp self-test: OK")
    print(f"config: {Path(DEFAULT_CONFIG_PATH).resolve()}")
    print(f"available_agents: {missing}")


if __name__ == "__main__":
    main()
