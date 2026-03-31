#!/usr/bin/env python3
"""
gen_converge_mcp.py — Build X-Dev-Converge-Agents header from .env and patch .mcp.json.

Reads provider credentials and model lists from .env, encodes the agent catalog as a
base64url header, and updates the dev-converge entry in .mcp.json.

Supported env vars (all optional; a provider is skipped if API_KEY or API_MODELS is unset):

    OPENAI_API_KEY=sk-proj-...
    OPENAI_API_MODELS=gpt-5.4                        # semicolon-separated
    OPENAI_BASE_URL=https://api.openai.com/v1        # optional override

    ANTHROPIC_API_KEY=sk-ant-...
    ANTHROPIC_API_MODELS=claude-sonnet-4-6

    GEMINI_API_KEY=AIza...
    GEMINI_API_MODELS=gemini-2.0-flash               # semicolon-separated
    GEMINI_BASE_URL=                                 # optional override

    DASHSCOPE_API_KEY=sk-sp-...
    DASHSCOPE_API_MODELS=kimi-k2.5;qwen3-max-2026-01-23   # semicolon-separated
    DASHSCOPE_BASE_URL=https://coding-intl.dashscope.aliyuncs.com/v1

    DEV_CONVERGE_DEFAULT_SYNTHESIZER=kimi-k2.5       # optional; auto-picks first kimi
    DEV_CONVERGE_API_TOKENS=label:token,...          # Bearer token for the service
    DEV_CONVERGE_SITE_URL=https://converge.gabidou.top

Usage:
    python gen_converge_mcp.py           # dry-run: print catalog and header
    python gen_converge_mcp.py --apply   # also update .mcp.json in place
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _split_models(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(";") if m.strip()]


def build_catalog(env: dict[str, str]) -> tuple[list[dict], str]:
    """Return (agents, default_synthesizer)."""
    agents: list[dict] = []

    # OpenAI (direct — uses max_completion_tokens)
    if env.get("OPENAI_API_KEY") and env.get("OPENAI_API_MODELS"):
        base = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        for model in _split_models(env["OPENAI_API_MODELS"]):
            agents.append(
                {
                    "name": model,
                    "provider": "openai",
                    "model": model,
                    "api_key": env["OPENAI_API_KEY"],
                    "base_url": base,
                }
            )

    # Anthropic (direct)
    if env.get("ANTHROPIC_API_KEY") and env.get("ANTHROPIC_API_MODELS"):
        for model in _split_models(env["ANTHROPIC_API_MODELS"]):
            agents.append(
                {
                    "name": model,
                    "provider": "anthropic",
                    "model": model,
                    "api_key": env["ANTHROPIC_API_KEY"],
                    "base_url": "",
                }
            )

    # Gemini
    if env.get("GEMINI_API_KEY") and env.get("GEMINI_API_MODELS"):
        base = env.get("GEMINI_BASE_URL", "")
        for model in _split_models(env["GEMINI_API_MODELS"]):
            agents.append(
                {
                    "name": model,
                    "provider": "gemini_compatible",
                    "model": model,
                    "api_key": env["GEMINI_API_KEY"],
                    "base_url": base,
                }
            )

    # DashScope (openai_compatible endpoint — covers Kimi, Qwen, GLM, MiniMax-via-DashScope)
    if env.get("DASHSCOPE_API_KEY") and env.get("DASHSCOPE_API_MODELS"):
        base = env.get(
            "DASHSCOPE_BASE_URL", "https://coding-intl.dashscope.aliyuncs.com/v1"
        )
        for model in _split_models(env["DASHSCOPE_API_MODELS"]):
            agents.append(
                {
                    "name": model,
                    "provider": "openai_compatible",
                    "model": model,
                    "api_key": env["DASHSCOPE_API_KEY"],
                    "base_url": base,
                }
            )

    # Default synthesizer: explicit > first kimi model > first agent
    default_synth = env.get("DEV_CONVERGE_DEFAULT_SYNTHESIZER", "")
    if not default_synth:
        for a in agents:
            if "kimi" in a["name"].lower():
                default_synth = a["name"]
                break
    if not default_synth and agents:
        default_synth = agents[0]["name"]

    return agents, default_synth


def encode_header(agents: list[dict], default_synthesizer: str) -> str:
    payload: dict = {"agents": agents}
    if default_synthesizer:
        payload["default_synthesizer"] = default_synthesizer
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _first_token(raw: str) -> str:
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        return part.split(":", 1)[-1].strip() if ":" in part else part
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="Update .mcp.json in place"
    )
    parser.add_argument(
        "--header-only",
        action="store_true",
        help="Print just the raw header value (for IDE copy-paste)",
    )
    parser.add_argument(
        "--env", default=".env", help="Path to .env file (default: .env)"
    )
    args = parser.parse_args()

    env_path = ROOT / args.env
    if not env_path.exists():
        print(f"ERROR: {env_path} not found", file=sys.stderr)
        return 1

    env = _load_env(env_path)
    agents, default_synth = build_catalog(env)

    if not agents:
        print(
            "ERROR: no agents found.\n"
            "Set at least one pair of API_KEY + API_MODELS vars in .env:\n"
            "  OPENAI_API_KEY + OPENAI_API_MODELS\n"
            "  ANTHROPIC_API_KEY + ANTHROPIC_API_MODELS\n"
            "  GEMINI_API_KEY + GEMINI_API_MODELS\n"
            "  DASHSCOPE_API_KEY + DASHSCOPE_API_MODELS",
            file=sys.stderr,
        )
        return 1

    header = encode_header(agents, default_synth)
    token = _first_token(env.get("DEV_CONVERGE_API_TOKENS", ""))
    site_url = env.get("DEV_CONVERGE_SITE_URL", "https://converge.gabidou.top").rstrip(
        "/"
    )
    sse_url = f"{site_url}/mcp/sse"

    if args.header_only:
        print(header)
        return 0

    print(f"Agents ({len(agents)}):")
    for a in agents:
        print(f"  {a['name']:<30}  {a['provider']}  {a['model']}")
    print(f"\nDefault synthesizer : {default_synth}")
    print(f"SSE URL             : {sse_url}")
    print("X-Dev-Converge-Agents (full):")
    print(f"  {header}")
    if token:
        print(f"\nBearer token        : {token[:8]}...")
    else:
        print("WARNING: DEV_CONVERGE_API_TOKENS not set — Authorization header omitted")

    if args.apply:
        mcp_path = ROOT / ".mcp.json"
        mcp: dict = {}
        if mcp_path.exists():
            mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        mcp.setdefault("mcpServers", {})

        entry: dict = {"url": sse_url, "headers": {"X-Dev-Converge-Agents": header}}
        if token:
            entry["headers"]["Authorization"] = f"Bearer {token}"

        mcp["mcpServers"]["dev-converge"] = entry
        mcp_path.write_text(
            json.dumps(mcp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\nUpdated {mcp_path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
