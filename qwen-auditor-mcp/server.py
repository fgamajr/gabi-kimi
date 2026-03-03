#!/usr/bin/env python3
"""MCP server wrapping Qwen (via Dashscope) as an adversarial code auditor.

Uses the Dashscope Responses API with Qwen 3 Max, thinking mode,
and built-in web_search + web_extractor tools so Qwen can look up
CVEs, library docs, and known issues during reviews.

Tools exposed:
  qwen_audit        — audit a code snippet
  qwen_audit_files  — audit multiple files (JSON input)
  qwen_review_diff  — audit a git diff
  qwen_verdict      — summarize findings as PASS/FAIL
"""
from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = os.environ.get("QWEN_MODEL", "qwen3-max")

SYSTEM_PROMPT = """\
You are a hostile code auditor. Your only job is to find bugs, security \
vulnerabilities, correctness issues, and contract violations.

Rules:
- Report ONLY actionable findings. No style comments, no redesign proposals.
- Each finding must include: severity (CRITICAL/HIGH/MEDIUM/LOW), \
  file:line (if available), one-sentence description, and a concrete fix diff.
- If you find nothing wrong, say "PASS — no findings" and stop.
- Be adversarial: assume the code is wrong until proven otherwise.
- Focus on: logic errors, off-by-one, race conditions, injection, \
  unhandled edge cases, broken invariants, resource leaks.
"""

# Responses API endpoint (different from Chat Completions)
client = OpenAI(
    api_key=os.environ.get("ALIBABA_API_KEY"),
    base_url="https://dashscope-intl.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1",
)
mcp = FastMCP("qwen-auditor")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ask(user_prompt: str) -> str:
    """Send prompt to Qwen via Dashscope Responses API."""
    resp = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        tools=[
            {"type": "web_search"},
            {"type": "web_extractor"},
        ],
        extra_body={"enable_thinking": True},
    )
    return resp.output_text


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def qwen_audit(code: str, context: str = "") -> str:
    """Audit a code snippet for bugs, security issues, and correctness.

    Args:
        code: The source code to audit.
        context: Optional context (what the code does, invariants, etc.)
    """
    prompt = f"Audit this code:\n\n```\n{code}\n```"
    if context:
        prompt += f"\n\nContext: {context}"
    return _ask(prompt)


@mcp.tool()
def qwen_audit_files(files_json: str, context: str = "") -> str:
    """Audit multiple files for bugs, security issues, and correctness.

    Args:
        files_json: JSON object mapping filename -> file content.
        context: Optional context about the codebase.
    """
    try:
        files = json.loads(files_json)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON input: {e}"

    parts = []
    for name, content in files.items():
        parts.append(f"--- {name} ---\n{content}")

    prompt = "Audit these files:\n\n" + "\n\n".join(parts)
    if context:
        prompt += f"\n\nContext: {context}"
    return _ask(prompt)


@mcp.tool()
def qwen_review_diff(diff: str, context: str = "") -> str:
    """Audit a git diff for introduced bugs, security issues, and regressions.

    Args:
        diff: The git diff output to review.
        context: Optional context about what the change is supposed to do.
    """
    prompt = f"Review this git diff for introduced bugs and issues:\n\n```diff\n{diff}\n```"
    if context:
        prompt += f"\n\nContext: {context}"
    return _ask(prompt)


@mcp.tool()
def qwen_verdict(findings: str) -> str:
    """Summarize audit findings as PASS or FAIL with a one-paragraph summary.

    Args:
        findings: The raw audit findings from qwen_audit or qwen_review_diff.
    """
    prompt = (
        "Summarize these code audit findings. "
        "Output exactly one line: PASS or FAIL, followed by a one-paragraph summary.\n\n"
        f"Findings:\n{findings}"
    )
    return _ask(prompt)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
