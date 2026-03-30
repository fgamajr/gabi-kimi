from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx


@dataclass
class AgentSpec:
    name: str
    provider: str
    model: str
    api_key: str
    base_url: str


_REQUIRED_FIELDS = {"name", "provider", "model", "api_key"}
_VALID_PROVIDERS = {"openai_compatible", "anthropic_compatible", "gemini_compatible"}


def build_agent(spec: dict[str, Any]) -> AgentSpec:
    missing = _REQUIRED_FIELDS - spec.keys()
    if missing:
        raise ValueError(f"Agent spec missing required fields: {sorted(missing)}")
    provider = str(spec["provider"])
    if provider not in _VALID_PROVIDERS:
        raise ValueError(
            f"Unsupported provider '{provider}'. Must be one of: {sorted(_VALID_PROVIDERS)}"
        )
    return AgentSpec(
        name=str(spec["name"]),
        provider=provider,
        model=str(spec["model"]),
        api_key=str(spec["api_key"]),
        base_url=str(spec.get("base_url") or ""),
    )


def decode_catalog(header_value: str) -> list[AgentSpec]:
    """Decode and validate the X-Dev-Converge-Agents header value."""
    try:
        padding = 4 - len(header_value) % 4
        padded = header_value + "=" * (padding % 4)
        raw = base64.urlsafe_b64decode(padded)
        data = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"Invalid X-Dev-Converge-Agents header: {exc}") from exc

    if not isinstance(data, dict) or "agents" not in data:
        raise ValueError(
            "X-Dev-Converge-Agents must be a JSON object with an 'agents' array"
        )

    agents_raw = data["agents"]
    if not isinstance(agents_raw, list) or not agents_raw:
        raise ValueError("'agents' must be a non-empty array")

    agents: list[AgentSpec] = []
    for i, entry in enumerate(agents_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Agent entry {i} must be an object")
        try:
            agents.append(build_agent(entry))
        except ValueError as exc:
            raise ValueError(f"Agent entry {i}: {exc}") from exc

    return agents


def get_default_synthesizer(header_value: str) -> str:
    """Return the default_synthesizer name from the catalog header, or empty string."""
    try:
        padding = 4 - len(header_value) % 4
        padded = header_value + "=" * (padding % 4)
        raw = base64.urlsafe_b64decode(padded)
        data = json.loads(raw)
        return str(data.get("default_synthesizer") or "")
    except Exception:
        return ""


def resolve_agents(agent_names_str: str, catalog: list[AgentSpec]) -> list[AgentSpec]:
    """Resolve comma-separated agent names against the request catalog."""
    names = [n.strip() for n in agent_names_str.split(",") if n.strip()]
    if not names:
        return list(catalog)
    index = {spec.name: spec for spec in catalog}
    resolved: list[AgentSpec] = []
    for name in names:
        spec = index.get(name)
        if spec is None:
            raise ValueError(f"Agent '{name}' not found in request catalog")
        resolved.append(spec)
    return resolved


def redact_catalog(catalog: list[AgentSpec]) -> list[dict[str, str]]:
    """Return catalog metadata without api_keys — safe to persist."""
    return [
        {
            "name": s.name,
            "provider": s.provider,
            "model": s.model,
            "base_url": s.base_url,
        }
        for s in catalog
    ]


def _openai_message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts: list[str] = []
        for item in message:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(message, dict):
        return str(message.get("content") or message.get("text") or message)
    return str(message)


def _anthropic_text(content: Any) -> str:
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(part for part in parts if part)


def _gemini_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(str(p.get("text") or "") for p in parts if "text" in p)


async def _call_openai_compatible(
    *,
    spec: AgentSpec,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    base = spec.base_url.rstrip("/") if spec.base_url else "https://api.openai.com/v1"
    payload = {
        "model": spec.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {spec.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    message = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return _openai_message_text(message)


async def _call_anthropic_compatible(
    *,
    spec: AgentSpec,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    base = spec.base_url.rstrip("/") if spec.base_url else "https://api.anthropic.com"
    payload = {
        "model": spec.model,
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base}/v1/messages",
            headers={
                "x-api-key": spec.api_key,
                "anthropic-version": "2023-06-01",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    return _anthropic_text(data.get("content", []))


async def _call_gemini_compatible(
    *,
    spec: AgentSpec,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    base = (
        spec.base_url.rstrip("/")
        if spec.base_url
        else "https://generativelanguage.googleapis.com/v1beta"
    )
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base}/models/{spec.model}:generateContent",
            params={"key": spec.api_key},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    return _gemini_text(data)


async def call_agent(
    *,
    spec: AgentSpec,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    started = perf_counter()
    if spec.provider == "openai_compatible":
        output = await _call_openai_compatible(
            spec=spec,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif spec.provider == "anthropic_compatible":
        output = await _call_anthropic_compatible(
            spec=spec,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif spec.provider == "gemini_compatible":
        output = await _call_gemini_compatible(
            spec=spec,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        raise RuntimeError(f"Unsupported provider: {spec.provider}")

    return {
        "agent": spec.name,
        "provider": spec.provider,
        "model": spec.model,
        "output": output,
        "latency_ms": round((perf_counter() - started) * 1000, 1),
    }
