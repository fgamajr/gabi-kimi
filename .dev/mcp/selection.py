from __future__ import annotations

import re

try:
    from .config import available_agents
    from .models import AgentSelection, RuntimeConfig
except ImportError:
    from config import available_agents
    from models import AgentSelection, RuntimeConfig


PERSONA_KEYWORDS = {
    "security": "security",
    "vuln": "security",
    "threat": "security",
    "performance": "performance",
    "optimize": "performance",
    "latency": "performance",
    "architecture": "architecture",
    "design": "architecture",
    "scalability": "architecture",
}

AGENT_ALIASES = {
    "claude": "claude",
    "anthropic": "claude",
    "kimi": "kimi",
    "moonshot": "kimi",
    "qwen": "qwen",
    "zai": "zai",
    "glm": "zai",
}

ORCHESTRATOR_PRIORITY = ["claude", "qwen", "kimi", "zai"]


def select_agents(
    prompt: str,
    config: RuntimeConfig,
    preferred_reviewers: list[str] | None = None,
    orchestrator: str | None = None,
) -> AgentSelection:
    available = available_agents(config)
    if not available:
        raise RuntimeError("No configured agents have API keys available")

    lower = prompt.lower()
    rationale: list[str] = []

    explicit = _parse_explicit_agents(lower, available)
    if preferred_reviewers:
        reviewers = [name for name in preferred_reviewers if name in available]
        rationale.append("reviewers overridden by caller")
    elif explicit:
        reviewers = explicit
        rationale.append("reviewers selected from explicit prompt constraint")
    else:
        reviewers = list(available)
        rationale.append("defaulted to all available agents")

    persona = _select_persona(lower)
    personas: dict[str, str] = {}
    for name in reviewers:
        agent = config.agents[name]
        personas[name] = persona if persona in agent.personas else "general"
    rationale.append(f"persona heuristic resolved to '{persona}'")

    if orchestrator and orchestrator in available:
        chosen_orchestrator = orchestrator
        rationale.append("orchestrator overridden by caller")
    else:
        chosen_orchestrator = _pick_orchestrator(available)
        rationale.append(f"default orchestrator selected as '{chosen_orchestrator}'")

    return AgentSelection(
        orchestrator=chosen_orchestrator,
        reviewers=reviewers,
        personas=personas,
        rationale=rationale,
    )


def _parse_explicit_agents(prompt: str, available: list[str]) -> list[str]:
    if "use only" not in prompt and "only " not in prompt:
        return []
    found: list[str] = []
    for alias, canonical in AGENT_ALIASES.items():
        if canonical in available and re.search(rf"\b{re.escape(alias)}\b", prompt):
            if canonical not in found:
                found.append(canonical)
    return found


def _select_persona(prompt: str) -> str:
    for keyword, persona in PERSONA_KEYWORDS.items():
        if keyword in prompt:
            return persona
    return "general"


def _pick_orchestrator(available: list[str]) -> str:
    for name in ORCHESTRATOR_PRIORITY:
        if name in available:
            return name
    return available[0]
