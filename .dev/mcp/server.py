from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    from .config import config_summary, load_runtime_config
    from .engine import ConvergenceEngine
except ImportError:
    from config import config_summary, load_runtime_config
    from engine import ConvergenceEngine


mcp = FastMCP(
    "Dev Multi-Agent Convergence MCP",
    instructions=(
        "Dev-only adversarial multi-agent convergence system. "
        "Use it to run review/revise loops over code or plans until zero-diff plus unanimous approval."
    ),
)


@mcp.tool(description="Show configured providers, agents, defaults, and currently available agents.")
def agent_config() -> dict[str, Any]:
    return config_summary(load_runtime_config())


@mcp.tool(description="Run the adversarial convergence loop over an artifact and return the final result.")
def converge_artifact(
    user_prompt: str,
    initial_artifact: str,
    artifact_kind: str = "code",
    orchestrator: str | None = None,
    reviewers: list[str] | None = None,
    max_rounds: int | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    run_label: str | None = None,
) -> dict[str, Any]:
    engine = ConvergenceEngine()
    result = engine.run(
        user_prompt=user_prompt,
        initial_artifact=initial_artifact,
        artifact_kind=artifact_kind,
        conversation_history=conversation_history,
        orchestrator=orchestrator,
        reviewers=reviewers,
        max_rounds=max_rounds,
        run_label=run_label,
    )
    return result.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dev-only MCP server for multi-agent convergence")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
        return
    mcp.run()


if __name__ == "__main__":
    main()
