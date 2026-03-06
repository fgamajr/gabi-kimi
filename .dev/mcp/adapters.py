from __future__ import annotations

import json
import time
from typing import Any

import httpx

try:
    from .config import resolve_agent_api_key
    from .models import AgentConfig, ProviderConfig, ProviderResponse, UsageStats
except ImportError:
    from config import resolve_agent_api_key
    from models import AgentConfig, ProviderConfig, ProviderResponse, UsageStats

try:
    from anthropic import Anthropic
except ModuleNotFoundError:
    Anthropic = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None  # type: ignore[assignment]


def create_adapter(provider: ProviderConfig, agent: AgentConfig) -> "BaseAdapter":
    if provider.sdk == "anthropic":
        return AnthropicAdapter(provider, agent)
    return DashScopeAdapter(provider, agent)


class BaseAdapter:
    def __init__(self, provider: ProviderConfig, agent: AgentConfig) -> None:
        self.provider = provider
        self.agent = agent
        self.resolved_key_env, self.api_key = resolve_agent_api_key(agent, provider)
        if not self.api_key:
            raise RuntimeError(f"Missing API key for {provider.key_env}")

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool,
        stream: bool,
    ) -> ProviderResponse:
        raise NotImplementedError


class DashScopeAdapter(BaseAdapter):
    def __init__(self, provider: ProviderConfig, agent: AgentConfig) -> None:
        super().__init__(provider, agent)
        self._sdk_client = None
        if OpenAI is not None:
            self._sdk_client = OpenAI(api_key=self.api_key, base_url=self.provider.base_url)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool,
        stream: bool,
    ) -> ProviderResponse:
        started = time.perf_counter()
        if self._sdk_client is not None:
            response = self._complete_via_sdk(messages, enable_thinking=enable_thinking, stream=stream)
        else:
            response = self._complete_via_http(messages, enable_thinking=enable_thinking, stream=stream)
        response.latency_ms = int((time.perf_counter() - started) * 1000)
        _apply_pricing(self.agent, response.usage)
        return response

    def _complete_via_sdk(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool,
        stream: bool,
    ) -> ProviderResponse:
        kwargs: dict[str, Any] = {
            "model": self.agent.model,
            "messages": messages,
            "stream": stream,
        }
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        if enable_thinking:
            kwargs["extra_body"] = {"enable_thinking": True}
        if self.agent.max_response:
            kwargs["max_tokens"] = self.agent.max_response
        completion = self._sdk_client.chat.completions.create(**kwargs)
        if not stream:
            msg = completion.choices[0].message
            usage = _usage_from_mapping(getattr(completion, "usage", None))
            reasoning = getattr(msg, "reasoning_content", "") or ""
            content = getattr(msg, "content", "") or ""
            if not usage.thinking_tokens and reasoning:
                usage.thinking_tokens = _estimate_token_count(reasoning)
            return ProviderResponse(content=content, reasoning=reasoning, usage=usage, raw={"sdk": True})

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = UsageStats()
        for chunk in completion:
            if getattr(chunk, "usage", None):
                usage = _usage_from_mapping(chunk.usage)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_parts.append(reasoning)
            content = getattr(delta, "content", None)
            if content:
                content_parts.append(content)
        if not usage.thinking_tokens and reasoning_parts:
            usage.thinking_tokens = _estimate_token_count("".join(reasoning_parts))
        return ProviderResponse(
            content="".join(content_parts),
            reasoning="".join(reasoning_parts),
            usage=usage,
            raw={"sdk": True, "stream": True},
        )

    def _complete_via_http(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool,
        stream: bool,
    ) -> ProviderResponse:
        url = self.provider.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.agent.model,
            "messages": messages,
            "stream": stream,
        }
        if self.agent.max_response:
            payload["max_tokens"] = self.agent.max_response
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if enable_thinking:
            payload["enable_thinking"] = True
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=120) as client:
            if not stream:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                message = ((data.get("choices") or [{}])[0]).get("message") or {}
                usage = _usage_from_mapping(data.get("usage"))
                reasoning = str(message.get("reasoning_content") or "")
                content = str(message.get("content") or "")
                if not usage.thinking_tokens and reasoning:
                    usage.thinking_tokens = _estimate_token_count(reasoning)
                return ProviderResponse(content=content, reasoning=reasoning, usage=usage, raw=data)

            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            usage = UsageStats()
            with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    chunk = json.loads(data_str)
                    if chunk.get("usage"):
                        usage = _usage_from_mapping(chunk.get("usage"))
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        reasoning_parts.append(str(reasoning))
                    content = delta.get("content")
                    if content:
                        content_parts.append(str(content))
            if not usage.thinking_tokens and reasoning_parts:
                usage.thinking_tokens = _estimate_token_count("".join(reasoning_parts))
            return ProviderResponse(
                content="".join(content_parts),
                reasoning="".join(reasoning_parts),
                usage=usage,
                raw={"http": True, "stream": True},
            )


class AnthropicAdapter(BaseAdapter):
    def __init__(self, provider: ProviderConfig, agent: AgentConfig) -> None:
        super().__init__(provider, agent)
        self._sdk_client = Anthropic(api_key=self.api_key) if Anthropic is not None else None

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool,
        stream: bool,
    ) -> ProviderResponse:
        started = time.perf_counter()
        if self._sdk_client is not None:
            response = self._complete_via_sdk(messages, enable_thinking=enable_thinking, stream=stream)
        else:
            response = self._complete_via_http(messages, enable_thinking=enable_thinking, stream=stream)
        response.latency_ms = int((time.perf_counter() - started) * 1000)
        _apply_pricing(self.agent, response.usage)
        return response

    def _complete_via_sdk(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool,
        stream: bool,
    ) -> ProviderResponse:
        system = ""
        anthropic_messages: list[dict[str, str]] = []
        for message in messages:
            if message["role"] == "system":
                system = message["content"]
            else:
                anthropic_messages.append(message)

        kwargs: dict[str, Any] = {
            "model": self.agent.model,
            "system": system,
            "messages": anthropic_messages,
            "max_tokens": self.agent.max_response or 4096,
        }
        if self.agent.output_config:
            kwargs["output_config"] = self.agent.output_config
        if enable_thinking:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": min(self.agent.max_response or 4096, 2048),
            }

        if not stream:
            message = self._sdk_client.messages.create(**kwargs)
            usage = UsageStats(
                input_tokens=int(getattr(message.usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(message.usage, "output_tokens", 0) or 0),
                total_tokens=int(
                    (getattr(message.usage, "input_tokens", 0) or 0)
                    + (getattr(message.usage, "output_tokens", 0) or 0)
                ),
            )
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            for block in message.content:
                if getattr(block, "type", "") == "text":
                    text_parts.append(getattr(block, "text", ""))
                elif getattr(block, "type", "") == "thinking":
                    thinking_parts.append(getattr(block, "thinking", ""))
            if thinking_parts:
                usage.thinking_tokens = _estimate_token_count("".join(thinking_parts))
            return ProviderResponse(
                content="".join(text_parts),
                reasoning="".join(thinking_parts),
                usage=usage,
                raw={"sdk": True},
            )

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        usage = UsageStats()
        with self._sdk_client.messages.stream(**kwargs) as stream_obj:
            for event in stream_obj:
                event_type = getattr(event, "type", "")
                if event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", "")
                    if delta_type == "text_delta":
                        text_parts.append(getattr(delta, "text", ""))
                    elif delta_type == "thinking_delta":
                        thinking_parts.append(getattr(delta, "thinking", ""))
                elif event_type == "message_delta":
                    usage.output_tokens = int(
                        getattr(getattr(event, "usage", None), "output_tokens", usage.output_tokens) or 0
                    )
                elif event_type == "message_start":
                    message = getattr(event, "message", None)
                    message_usage = getattr(message, "usage", None)
                    usage.input_tokens = int(
                        getattr(message_usage, "input_tokens", usage.input_tokens) or 0
                    )
        usage.total_tokens = usage.input_tokens + usage.output_tokens
        if thinking_parts:
            usage.thinking_tokens = _estimate_token_count("".join(thinking_parts))
        return ProviderResponse(
            content="".join(text_parts),
            reasoning="".join(thinking_parts),
            usage=usage,
            raw={"sdk": True, "stream": True},
        )

    def _complete_via_http(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool,
        stream: bool,
    ) -> ProviderResponse:
        url = self.provider.base_url.rstrip("/") + "/messages"
        system = ""
        anthropic_messages: list[dict[str, str]] = []
        for message in messages:
            if message["role"] == "system":
                system = message["content"]
            else:
                anthropic_messages.append(message)

        payload: dict[str, Any] = {
            "model": self.agent.model,
            "system": system,
            "messages": anthropic_messages,
            "max_tokens": self.agent.max_response or 4096,
            "stream": stream,
        }
        if self.agent.output_config:
            payload["output_config"] = self.agent.output_config
        if enable_thinking:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": min(self.agent.max_response or 4096, 2048),
            }

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        with httpx.Client(timeout=120) as client:
            if not stream:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                usage = UsageStats(
                    input_tokens=int((data.get("usage") or {}).get("input_tokens", 0) or 0),
                    output_tokens=int((data.get("usage") or {}).get("output_tokens", 0) or 0),
                )
                usage.total_tokens = usage.input_tokens + usage.output_tokens
                text_parts: list[str] = []
                thinking_parts: list[str] = []
                for block in data.get("content") or []:
                    if block.get("type") == "text":
                        text_parts.append(str(block.get("text") or ""))
                    elif block.get("type") == "thinking":
                        thinking_parts.append(str(block.get("thinking") or ""))
                if thinking_parts:
                    usage.thinking_tokens = _estimate_token_count("".join(thinking_parts))
                return ProviderResponse(
                    content="".join(text_parts),
                    reasoning="".join(thinking_parts),
                    usage=usage,
                    raw=data,
                )

            text_parts: list[str] = []
            thinking_parts: list[str] = []
            usage = UsageStats()
            current_event = ""
            with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:]
                        continue
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    event = json.loads(data_str)
                    if current_event == "message_start":
                        usage.input_tokens = int(
                            (((event.get("message") or {}).get("usage") or {}).get("input_tokens", 0) or 0)
                        )
                    elif current_event == "message_delta":
                        usage.output_tokens = int(
                            ((event.get("usage") or {}).get("output_tokens", usage.output_tokens) or 0)
                        )
                    elif current_event == "content_block_delta":
                        delta = event.get("delta") or {}
                        delta_type = delta.get("type")
                        if delta_type == "text_delta":
                            text_parts.append(str(delta.get("text") or ""))
                        elif delta_type == "thinking_delta":
                            thinking_parts.append(str(delta.get("thinking") or ""))
            usage.total_tokens = usage.input_tokens + usage.output_tokens
            if thinking_parts:
                usage.thinking_tokens = _estimate_token_count("".join(thinking_parts))
            return ProviderResponse(
                content="".join(text_parts),
                reasoning="".join(thinking_parts),
                usage=usage,
                raw={"http": True, "stream": True},
            )


def _usage_from_mapping(raw: Any) -> UsageStats:
    if raw is None:
        return UsageStats()
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return UsageStats()
    prompt_tokens = int(raw.get("prompt_tokens", 0) or raw.get("input_tokens", 0) or 0)
    completion_tokens = int(raw.get("completion_tokens", 0) or raw.get("output_tokens", 0) or 0)
    total_tokens = int(raw.get("total_tokens", prompt_tokens + completion_tokens) or 0)
    completion_details = raw.get("completion_tokens_details") or {}
    thinking_tokens = int(
        completion_details.get("reasoning_tokens", 0)
        or completion_details.get("thinking_tokens", 0)
        or raw.get("thinking_tokens", 0)
        or 0
    )
    return UsageStats(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=total_tokens,
        thinking_tokens=thinking_tokens,
    )


def _estimate_token_count(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _apply_pricing(agent: AgentConfig, usage: UsageStats) -> None:
    if usage.estimated_cost_usd is not None:
        return
    pricing = agent.pricing or {}
    if not pricing:
        return
    input_rate = float(pricing.get("input_per_million_usd", 0.0) or 0.0)
    output_rate = float(pricing.get("output_per_million_usd", 0.0) or 0.0)
    thinking_rate = float(pricing.get("thinking_per_million_usd", output_rate) or output_rate or 0.0)
    usage.estimated_cost_usd = (
        (usage.input_tokens / 1_000_000.0) * input_rate
        + ((usage.output_tokens - usage.thinking_tokens) / 1_000_000.0) * output_rate
        + (usage.thinking_tokens / 1_000_000.0) * thinking_rate
    )
