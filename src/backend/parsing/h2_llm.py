from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


def _extract_json_block(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
        content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return json.loads(content)
    start = content.find("{")
    if start < 0:
        raise ValueError("no JSON object found in LLM output")
    depth = 0
    end = -1
    for i, ch in enumerate(content[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        raise ValueError("unterminated JSON object in LLM output")
    return json.loads(content[start : end + 1])


def build_h2_prompt(text: str, allowed_tags: tuple[str, ...], source_type: str) -> str:
    tags = ", ".join(allowed_tags)
    return (
        f"Você é um extrator semântico para {source_type}.\n"
        f"Tags permitidas: [{tags}].\n"
        "Retorne APENAS JSON com o formato:\n"
        "{"
        "\"tag_spans\":[{\"tag\":\"...\",\"start_char\":0,\"end_char\":10,\"confidence\":0.9}],"
        "\"summary_short\":\"...\","
        "\"summary_long\":\"...\","
        "\"summary_structured\":{},"
        "\"legal_entities\":[],"
        "\"topics\":[],"
        "\"chunk_summaries\":[]"
        "}\n"
        "Restrições: não invente tags fora da lista, não sobreponha spans.\n"
        f"Texto:\n{text[:12000]}"
    )


def call_local_llm(
    *,
    prompt: str,
    model: str = "qwen3",
    timeout_sec: float = 120.0,
    mode: str = "fast",
) -> dict[str, Any]:
    base_url = os.getenv("H2_LLM_BASE_URL", "http://llm:11434").rstrip("/")
    api_key = os.getenv("H2_LLM_API_KEY", "not-required")
    max_tokens = int(os.getenv("H2_LLM_MAX_TOKENS_DEEP", "900")) if mode == "deep" else int(
        os.getenv("H2_LLM_MAX_TOKENS", "512")
    )
    temperature = float(os.getenv("H2_LLM_TEMPERATURE", "0.0"))
    top_p = float(os.getenv("H2_LLM_TOP_P", "0.9"))
    repeat_penalty = float(os.getenv("H2_LLM_REPEAT_PENALTY", "1.1"))

    common_messages = [
        {"role": "system", "content": "Você responde apenas JSON válido."},
        {"role": "user", "content": prompt},
    ]

    openai_url = f"{base_url}/v1/chat/completions"
    openai_payload = {
        "model": model,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": common_messages,
    }

    ollama_url = f"{base_url}/api/chat"
    ollama_payload = {
        "model": model,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
            "num_predict": max_tokens,
        },
        "messages": common_messages,
    }

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=timeout_sec) as client:
        try:
            response = client.post(openai_url, json=openai_payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            provider = "openai_compat"
        except Exception:
            response = client.post(ollama_url, json=ollama_payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = (data.get("message") or {}).get("content", "")
            usage = {
                "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count"),
                "total_tokens": (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0),
            }
            provider = "ollama"
    out = _extract_json_block(content)
    out["__meta"] = {"provider": provider, "usage": usage}
    return out
