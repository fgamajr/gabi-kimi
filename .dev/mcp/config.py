from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

try:
    from .models import AgentConfig, ConvergenceConfig, DefaultsConfig, ProviderConfig, RuntimeConfig
except ImportError:
    from models import AgentConfig, ConvergenceConfig, DefaultsConfig, ProviderConfig, RuntimeConfig


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path(__file__).with_name("mcp-agents.yaml")
DEFAULT_ENV_PATH = ROOT_DIR / ".env"


def load_runtime_config(config_path: str | Path | None = None) -> RuntimeConfig:
    load_dotenv(DEFAULT_ENV_PATH)
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(path.read_text()) or {}
    providers = {
        name: ProviderConfig(name=name, **data)
        for name, data in (raw.get("providers") or {}).items()
    }
    _apply_provider_env_overrides(providers)
    agents = {
        name: AgentConfig(name=name, **data)
        for name, data in (raw.get("agents") or {}).items()
    }
    defaults_raw = raw.get("defaults") or {}
    convergence = ConvergenceConfig(**(defaults_raw.get("convergence") or {}))
    defaults = DefaultsConfig(
        max_rounds=int(defaults_raw.get("max_rounds", 5)),
        parallel=bool(defaults_raw.get("parallel", True)),
        log_dir=str(defaults_raw.get("log_dir", ".dev/mcp/runs")),
        convergence=convergence,
    )
    return RuntimeConfig(providers=providers, agents=agents, defaults=defaults, config_path=path)


def _apply_provider_env_overrides(providers: dict[str, ProviderConfig]) -> None:
    dashscope = providers.get("dashscope")
    if dashscope is not None:
        override = (
            os.getenv("DASHSCOPE_BASE_URL")
            or os.getenv("ALIBABA_BASE_URL")
            or os.getenv("MODEL_STUDIO_BASE_URL")
        )
        if override:
            dashscope.base_url = override.rstrip("/")
    anthropic = providers.get("anthropic")
    if anthropic is not None:
        override = os.getenv("ANTHROPIC_BASE_URL")
        if override:
            anthropic.base_url = override.rstrip("/")


def resolve_api_key(env_name: str) -> str:
    for name in _env_aliases(env_name):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def resolve_agent_api_key(agent: AgentConfig, provider: ProviderConfig) -> tuple[str, str]:
    env_name = provider.key_env
    return env_name, resolve_api_key(env_name)


def _env_aliases(env_name: str) -> list[str]:
    aliases: dict[str, list[str]] = {
        "ALIBABA_API_KEY": [
            "ALIBABA_API_KEY",
            "DASHSCOPE_API_KEY",
            "DASHSCOPE_API_API_KEY",
        ],
        "DASHSCOPE_API_KEY": [
            "DASHSCOPE_API_KEY",
            "DASHSCOPE_API_API_KEY",
            "ALIBABA_API_KEY",
        ],
        "DASHSCOPE_API_API_KEY": [
            "DASHSCOPE_API_API_KEY",
            "DASHSCOPE_API_KEY",
            "ALIBABA_API_KEY",
        ],
        "ANTHROPIC_API_KEY": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
    }
    return aliases.get(env_name, [env_name])


def available_agents(config: RuntimeConfig) -> list[str]:
    result: list[str] = []
    for name, agent in config.agents.items():
        provider = config.providers[agent.provider]
        _, key = resolve_agent_api_key(agent, provider)
        if key:
            result.append(name)
    return sorted(result)


def config_summary(config: RuntimeConfig) -> dict[str, Any]:
    return {
        "config_path": str(config.config_path),
        "providers": {
            name: {
                "base_url": provider.base_url,
                "key_env": provider.key_env,
                "sdk": provider.sdk,
                "streaming": provider.streaming,
            }
            for name, provider in config.providers.items()
        },
        "agents": {
            name: {
                "provider": agent.provider,
                "model": agent.model,
                "key_env": agent.key_env,
                "enable_thinking": agent.enable_thinking,
                "max_response": agent.max_response,
                "personas": agent.personas,
                "output_config": agent.output_config,
            }
            for name, agent in config.agents.items()
        },
        "defaults": {
            "max_rounds": config.defaults.max_rounds,
            "parallel": config.defaults.parallel,
            "log_dir": config.defaults.log_dir,
            "convergence": {
                "zero_diff": config.defaults.convergence.zero_diff,
                "unanimous_approve": config.defaults.convergence.unanimous_approve,
            },
        },
        "available_agents": available_agents(config),
    }
