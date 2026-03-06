from __future__ import annotations

import json
from typing import Any

from dotenv import load_dotenv

try:
    from ..mcp.adapters import create_adapter
    from ..mcp.config import DEFAULT_ENV_PATH, load_runtime_config
except ImportError:
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "mcp"))
    from adapters import create_adapter
    from config import DEFAULT_ENV_PATH, load_runtime_config


def judge_results(
    *,
    judge_agent: str,
    case: dict[str, Any],
    backend: str,
    results: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, Any]:
    load_dotenv(DEFAULT_ENV_PATH)
    cfg = load_runtime_config()
    agent = cfg.agents[judge_agent]
    provider = cfg.providers[agent.provider]
    adapter = create_adapter(provider, agent)
    payload = {
        "case": case,
        "backend": backend,
        "top_results": results[:top_k],
        "schema": {
            "overall_score": "0..5",
            "relevant_ranks": [1, 2],
            "verdict": "PASS or FAIL",
            "rationale": "brief text",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are grading search result quality. Return JSON only. "
                "Do not judge based on backend name. Judge only the query, filters, and returned results."
            ),
        },
        {
            "role": "user",
            "content": (
                "Evaluate whether these search results satisfy the benchmark case. "
                "Return JSON with keys overall_score, relevant_ranks, verdict, rationale.\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        },
    ]
    response = adapter.complete(messages, enable_thinking=agent.enable_thinking, stream=provider.streaming)
    return _extract_json(response.content) | {
        "judge_agent": judge_agent,
        "latency_ms": response.latency_ms,
        "tokens_used": response.usage.total_tokens,
        "thinking_tokens": response.usage.thinking_tokens,
    }


def _extract_json(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    candidates = [stripped]
    if "```" in stripped:
        for part in stripped.split("```"):
            part = part.strip()
            if part.startswith("json"):
                candidates.append(part[4:].strip())
            elif part.startswith("{"):
                candidates.append(part)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(candidate[start : end + 1])
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    continue
    return {"overall_score": 0, "relevant_ranks": [], "verdict": "FAIL", "rationale": "invalid judge JSON"}
