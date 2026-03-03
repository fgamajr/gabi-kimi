#!/usr/bin/env python3
"""MCP server wrapping GLM-4.7 (via Z.AI / Zhipu) as an adversarial code auditor.

Uses the Z.AI Chat Completions API with glm-4.7.

Tools exposed:
  glm_audit        - audit a code snippet
  glm_audit_files  - audit multiple files (JSON input)
  glm_review_diff  - audit a git diff
  glm_verdict      - summarize findings as PASS/FAIL
"""
from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from openai import OpenAI

MODEL = os.environ.get("GLM_MODEL", "glm-4.7")
BASE_URL = "https://api.z.ai/api/paas/v4/"
MAX_TOKENS = int(os.environ.get("GLM_MAX_TOKENS", "16384"))

SYSTEM_PROMPT = """\
You are a hostile code auditor. Your only job is to find bugs, security \
vulnerabilities, correctness issues, and contract violations.

Rules:
- Report ONLY actionable findings. No style comments, no redesign proposals.
- Each finding must include: severity (CRITICAL/HIGH/MEDIUM/LOW), \
  file:line (if available), one-sentence description, and a concrete fix diff.
- If you find nothing wrong, say "PASS - no findings" and stop.
- Be adversarial: assume the code is wrong until proven otherwise.
- Focus on: logic errors, off-by-one, race conditions, injection, \
  unhandled edge cases, broken invariants, resource leaks.
"""

client = OpenAI(api_key=os.environ.get("ZAI_API_KEY"), base_url=BASE_URL)
mcp = FastMCP("glm-auditor")


def _extract_content(chat: Any) -> str:
    msg = chat.choices[0].message
    content = (msg.content or "").strip()
    if content:
        return content
    return "PASS - no findings"


def _ask(user_prompt: str) -> str:
    """Send prompt to GLM via Z.AI OpenAI-compatible Chat Completions API."""
    chat = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=MAX_TOKENS,
    )
    return _extract_content(chat)


@mcp.tool()
def glm_audit(code: str, context: str = "") -> str:
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
def glm_audit_files(files_json: str, context: str = "") -> str:
    """Audit multiple files for bugs, security issues, and correctness.

    Args:
        files_json: JSON object mapping filename -> file content.
        context: Optional context about the codebase.
    """
    try:
        files = json.loads(files_json)
    except json.JSONDecodeError as exc:
        return f"ERROR: Invalid JSON input: {exc}"

    parts: list[str] = []
    for name, content in files.items():
        parts.append(f"--- {name} ---\n{content}")

    prompt = "Audit these files:\n\n" + "\n\n".join(parts)
    if context:
        prompt += f"\n\nContext: {context}"
    return _ask(prompt)


@mcp.tool()
def glm_review_diff(diff: str, context: str = "") -> str:
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
def glm_verdict(findings: str) -> str:
    """Summarize audit findings as PASS or FAIL with a one-paragraph summary.

    Args:
        findings: The raw audit findings from glm_audit or glm_review_diff.
    """
    prompt = (
        "Summarize these code audit findings. "
        "Output exactly one line: PASS or FAIL, followed by a one-paragraph summary.\n\n"
        f"Findings:\n{findings}"
    )
    return _ask(prompt)


if __name__ == "__main__":
    mcp.run()
