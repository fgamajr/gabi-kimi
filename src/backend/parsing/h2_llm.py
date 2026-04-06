from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


def _extract_json_block(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return json.loads(content)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found in LLM output")
    return json.loads(match.group(0))


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
) -> dict[str, Any]:
    base_url = os.getenv("H2_LLM_BASE_URL", "http://qwen-embed:8900").rstrip("/")
    api_key = os.getenv("H2_LLM_API_KEY", "not-required")
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Você responde apenas JSON válido."},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=timeout_sec) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    content = data["choices"][0]["message"]["content"]
    return _extract_json_block(content)
