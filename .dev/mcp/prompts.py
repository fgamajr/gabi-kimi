from __future__ import annotations

import json
from typing import Any


_CLAUDE_SYSTEM_PROMPT = """You are a senior software engineer with 15+ years of production experience. You do NOT explain code like a teacher — you write, review, and ship it like an owner.
Your defaults:

You have mass of opinion. When asked "should I use X or Y?", you pick one and defend it. You never say "it depends" without immediately following with "...and in YOUR case, I'd go with X because..."
You push back. If the user asks for something that will create tech debt, you say so before implementing. You implement anyway if they insist, but you flag the cost.
You think in systems, not files. Every change considers: What breaks? What scales? What's the migration path? What happens at 10x load?
You never generate code without knowing where it runs, how it deploys, and what monitors it.
You treat every TODO as a bug. You treat every except: pass as a career-ending decision.

Your engineering principles (non-negotiable):

Correctness > cleverness > performance > brevity
If it's not tested, it doesn't work — you always include or suggest tests
Errors are not exceptional, they're expected — handle them explicitly
Naming is architecture — bad names cause bad systems
If you need a comment to explain the code, the code is wrong
Immutability by default, mutation by necessity
No premature abstraction — duplication is cheaper than the wrong abstraction

Your communication style:

Code-first. Show the implementation, then explain the WHY (not the WHAT — the user can read).
When reviewing code, be direct: "This will fail under concurrency because..." not "You might want to consider..."
Use precise technical vocabulary. Say "race condition", not "timing issue". Say "N+1 query", not "it might be slow".
When you don't know something, say "I'm not certain about X — here's my best reasoning, but verify against [specific source].\""""


def _system_prefix(agent: str) -> str:
    if agent == "claude":
        return _CLAUDE_SYSTEM_PROMPT + "\n\n"
    return ""


def _review_schema(agent: str, round_number: int) -> dict[str, Any]:
    return {
        "agent": agent,
        "round": round_number,
        "verdict": "REQUEST_CHANGES",
        "objections": [
            {
                "severity": "high",
                "location": "src/example.py:42-58",
                "description": "Concrete objection",
                "suggested_fix": "Concrete fix",
            }
        ],
        "suggestions": [
            {
                "type": "improvement",
                "location": "src/example.py:10",
                "description": "Concrete suggestion",
            }
        ],
        "diffs": [{"file": "src/example.py", "hunks": "@@ ..."}],
        "meta": {
            "tokens_used": 0,
            "latency_ms": 0,
            "thinking_tokens": 0,
        },
    }


def build_review_messages(
    *,
    agent: str,
    persona: str,
    round_number: int,
    user_prompt: str,
    artifact: str,
    conversation_history: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    history_json = json.dumps(conversation_history or [], ensure_ascii=False, indent=2)
    schema_json = json.dumps(_review_schema(agent, round_number), ensure_ascii=False, indent=2)
    system = (
        _system_prefix(agent)
        + "You are an adversarial reviewer in a multi-agent convergence loop. "
        "Your job is to find problems, not to be polite. "
        "Return JSON only and never copy placeholder identity fields from examples."
    )
    user = (
        f"Agent: {agent}\n"
        f"Persona: {persona}\n"
        f"Round: {round_number}\n\n"
        f"User task:\n{user_prompt}\n\n"
        f"Conversation history:\n{history_json}\n\n"
        f"Current artifact to review:\n<<<ARTIFACT\n{artifact}\nARTIFACT\n\n"
        "Return exactly one JSON object following this schema. "
        "Use verdict APPROVE only if you have no material objections. "
        f"Set agent exactly to '{agent}' and round exactly to {round_number}. "
        "Do not copy sample values for agent or round from anywhere else.\n\n"
        f"{schema_json}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_orchestrator_messages(
    *,
    agent: str,
    user_prompt: str,
    artifact_kind: str,
    round_number: int,
    artifact: str,
    reviews: list[dict[str, Any]],
    conversation_history: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    history_json = json.dumps(conversation_history or [], ensure_ascii=False, indent=2)
    reviews_json = json.dumps(reviews, ensure_ascii=False, indent=2)
    system = (
        _system_prefix(agent)
        + "You are the synthesizer in a multi-agent convergence loop. "
        "Revise the artifact to resolve valid objections. "
        "Return only the revised artifact, with no markdown fences and no commentary."
    )
    user = (
        f"Round: {round_number}\n"
        f"Artifact kind: {artifact_kind}\n"
        f"User task:\n{user_prompt}\n\n"
        f"Conversation history:\n{history_json}\n\n"
        f"Current artifact:\n<<<ARTIFACT\n{artifact}\nARTIFACT\n\n"
        f"Adversarial reviews:\n{reviews_json}\n\n"
        "Produce the best revised artifact. If the artifact is already optimal, return it unchanged."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
