from __future__ import annotations

import asyncio
from contextvars import ContextVar
import logging
from typing import Any

from dotenv import load_dotenv

from src.dev_converge.config import settings
from src.dev_converge.executor import (
    _coerce_int,
    complete_once as executor_complete_once,
    get_defaults as executor_get_defaults,
    jury_panel as executor_jury_panel,
    ping_models as executor_ping_models,
    run_panel as executor_run_panel,
    swarm_panel as executor_swarm_panel,
    triangular_panel as executor_triangular_panel,
)
from src.dev_converge.jobs import create_job, get_job, serialize_job
from src.dev_converge.providers import (
    AgentSpec,
    decode_catalog,
    get_default_synthesizer,
    resolve_agents,
)

logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.sse import TransportSecuritySettings
except ModuleNotFoundError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment]
    TransportSecuritySettings = None  # type: ignore[assignment]

load_dotenv()

_token_label: ContextVar[str] = ContextVar(
    "dev_converge_token_label", default="anonymous"
)
_request_catalog: ContextVar[list[AgentSpec]] = ContextVar(
    "dev_converge_catalog", default=[]
)
_default_synthesizer: ContextVar[str] = ContextVar("dev_converge_synth", default="")


def current_token_label() -> str:
    return _token_label.get()


def current_catalog() -> list[AgentSpec]:
    return _request_catalog.get()


def _build_transport_security() -> TransportSecuritySettings | None:
    if TransportSecuritySettings is None:
        return None
    from urllib.parse import urlparse

    allowed_hosts = [
        "127.0.0.1:*",
        "localhost:*",
        "[::1]:*",
        "127.0.0.1",
        "localhost",
        "::1",
    ]
    hostname = urlparse(settings.DEV_CONVERGE_SITE_URL).hostname
    if hostname and hostname not in allowed_hosts:
        allowed_hosts.append(hostname)
    for host in settings.allowed_hosts:
        if host not in allowed_hosts:
            allowed_hosts.append(host)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
    )


async def get_defaults() -> dict[str, Any]:
    """Return service capabilities and the available agent names in the current request catalog.
    Always call this first to discover which agent names can be used in complete_once,
    ping_models, run_panel, and other tools."""
    result = await executor_get_defaults()
    catalog = current_catalog()
    result["catalog_agents"] = [a.name for a in catalog]
    result["default_synthesizer"] = _default_synthesizer.get()
    return result


async def ping_models(
    task: str = "Say 'ready' and name your model.",
    agent_names: str = "",
    context: str = "",
    max_tokens: int | str | None = 120,
    temperature: float | str | None = 0.0,
    thinking: str = "low",
) -> dict[str, Any]:
    """Health-check all agents in the catalog in parallel.
    agent_names: leave EMPTY ("") to ping every agent. Pass a comma-separated list of
    names from get_defaults.catalog_agents to ping a subset. Never pass the string "all"."""
    return await executor_ping_models(
        task=task,
        agent_names=agent_names,
        context=context,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking=thinking,
        catalog=current_catalog(),
    )


def _compute_timeout(num_agents: int, rounds: int = 1, per_agent_sec: int = 60) -> int:
    timeout = per_agent_sec * max(1, num_agents) * max(1, rounds)
    return max(60, min(600, timeout))


async def _wrap_timeout(coro, timeout_sec: int, tool_name: str):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"{tool_name} timed out after {timeout_sec}s. "
            f"Use start_{tool_name} + poll_job for jobs that exceed the sync timeout."
        ) from None


async def complete_once(
    task: str,
    context: str = "",
    agent_name: str = "",
    system_prompt: str = "You are a concise expert assistant.",
    max_tokens: int | str | None = 1200,
    temperature: float | str | None = 0.2,
    thinking: str = "medium",
) -> dict[str, Any]:
    """Run a task on a single agent. agent_name must be one of the names listed in
    get_defaults.catalog_agents (e.g. 'kimi-k2.5', 'claude-sonnet-4-6', 'gpt-5.4').
    Required when the catalog has more than one agent; omit only when there is exactly one."""
    return await _wrap_timeout(
        executor_complete_once(
            task=task,
            context=context,
            agent_name=agent_name,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking=thinking,
            catalog=current_catalog(),
        ),
        settings.DEV_CONVERGE_SYNC_TIMEOUT_SEC,
        "complete_once",
    )


async def run_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    rounds: int | str | None = 1,
    temperature: float | str | None = 0.2,
    topology: str = "parallel",
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Run a task on multiple agents in parallel and synthesize the results.
    agent_names: leave EMPTY ("") to use all agents. Pass comma-separated names from
    get_defaults.catalog_agents to use a subset. Never pass the string "all".
    Set include_transcript=true to see each agent's individual answer before the synthesis.
    timeout_sec: overrides the auto-calculated timeout (default: 60s × agents × rounds, capped at 600s)."""
    catalog = current_catalog()
    agents = resolve_agents(agent_names, catalog)
    effective_timeout = (
        timeout_sec
        if timeout_sec is not None
        else _compute_timeout(len(agents), _coerce_int(rounds, 1))
    )
    return await _wrap_timeout(
        executor_run_panel(
            task=task,
            agent_names=agent_names,
            context=context,
            include_transcript=include_transcript,
            max_tokens=max_tokens,
            rounds=rounds,
            temperature=temperature,
            topology=topology,
            catalog=catalog,
        ),
        effective_timeout,
        "run_panel",
    )


async def swarm_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    swarm_roles: str = "",
    temperature: float | str | None = 0.2,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Run a cooperative swarm: each agent is assigned a distinct role and answers in character.
    agent_names: leave EMPTY ("") to use all agents. Never pass the string "all".
    timeout_sec: overrides the auto-calculated timeout (default: 60s × agents, capped at 600s)."""
    catalog = current_catalog()
    agents = resolve_agents(agent_names, catalog)
    effective_timeout = (
        timeout_sec if timeout_sec is not None else _compute_timeout(len(agents))
    )
    return await _wrap_timeout(
        executor_swarm_panel(
            task=task,
            agent_names=agent_names,
            context=context,
            include_transcript=include_transcript,
            max_tokens=max_tokens,
            swarm_roles=swarm_roles,
            temperature=temperature,
            catalog=catalog,
        ),
        effective_timeout,
        "swarm_panel",
    )


async def jury_panel(
    task: str,
    context: str = "",
    expert_agents: str = "",
    jury_agents: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    swarm_roles: str = "",
    temperature: float | str | None = 0.2,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Expert witnesses answer the task; jury agents deliberate and deliver a verdict.
    expert_agents and jury_agents are comma-separated names from get_defaults.catalog_agents.
    Leave both EMPTY ("") to split the catalog automatically. Never pass "all".
    timeout_sec: overrides the auto-calculated timeout (default: 60s × agents, capped at 600s)."""
    catalog = current_catalog()
    expert_list = resolve_agents(expert_agents, catalog) if expert_agents else []
    jury_list = resolve_agents(jury_agents, catalog) if jury_agents else []
    num_agents = (
        len(expert_list) + len(jury_list)
        if (expert_agents or jury_agents)
        else len(catalog)
    )
    effective_timeout = (
        timeout_sec if timeout_sec is not None else _compute_timeout(num_agents)
    )
    effective_timeout = (
        timeout_sec if timeout_sec is not None else _compute_timeout(num_agents)
    )
    return await _wrap_timeout(
        executor_jury_panel(
            task=task,
            context=context,
            expert_agents=expert_agents,
            jury_agents=jury_agents,
            include_transcript=include_transcript,
            max_tokens=max_tokens,
            swarm_roles=swarm_roles,
            temperature=temperature,
            catalog=catalog,
        ),
        effective_timeout,
        "jury_panel",
    )


async def triangular_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    synthesizer: str = "",
    temperature: float | str | None = 0.2,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """3-phase panel: agents analyse → critique each other → revise. One agent synthesises.
    agent_names: leave EMPTY ("") to use all agents. Never pass the string "all".
    synthesizer: name of the agent that writes the final synthesis (defaults to default_synthesizer).
    timeout_sec: overrides the auto-calculated timeout (default: 60s × agents × 3 phases, capped at 600s)."""
    catalog = current_catalog()
    agents = resolve_agents(agent_names, catalog)
    effective_timeout = (
        timeout_sec
        if timeout_sec is not None
        else _compute_timeout(len(agents), rounds=3)
    )
    return await _wrap_timeout(
        executor_triangular_panel(
            task=task,
            agent_names=agent_names,
            context=context,
            include_transcript=include_transcript,
            max_tokens=max_tokens,
            synthesizer=synthesizer or _default_synthesizer.get(),
            temperature=temperature,
            catalog=catalog,
        ),
        effective_timeout,
        "triangular_panel",
    )


def _start_job(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    from src.dev_converge.providers import redact_catalog
    from src.dev_converge.worker import enqueue_job

    catalog = current_catalog()
    record = create_job(
        job_type, payload, current_token_label(), redact_catalog(catalog)
    )
    enqueue_job(record["job_id"], job_type, payload, catalog)
    return record


def start_run_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    rounds: int | str | None = 1,
    temperature: float | str | None = 0.2,
    topology: str = "parallel",
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Enqueue a run_panel job and return a job_id immediately. Use poll_job to retrieve the result.
    agent_names: leave EMPTY ("") for all agents. Never pass "all".
    timeout_sec: overrides the auto-calculated timeout (default: 60s × agents × rounds, capped at 600s)."""
    return _start_job(
        "run_panel",
        {
            "task": task,
            "agent_names": agent_names,
            "context": context,
            "include_transcript": include_transcript,
            "max_tokens": max_tokens,
            "rounds": rounds,
            "temperature": temperature,
            "topology": topology,
            "timeout_sec": timeout_sec,
        },
    )


def start_swarm_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    swarm_roles: str = "",
    temperature: float | str | None = 0.2,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Enqueue a swarm_panel job and return a job_id immediately. Use poll_job to retrieve the result.
    agent_names: leave EMPTY ("") for all agents. Never pass "all".
    timeout_sec: overrides the auto-calculated timeout (default: 60s × agents, capped at 600s)."""
    return _start_job(
        "swarm_panel",
        {
            "task": task,
            "agent_names": agent_names,
            "context": context,
            "include_transcript": include_transcript,
            "max_tokens": max_tokens,
            "swarm_roles": swarm_roles,
            "temperature": temperature,
            "timeout_sec": timeout_sec,
        },
    )


def start_jury_panel(
    task: str,
    context: str = "",
    expert_agents: str = "",
    jury_agents: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    swarm_roles: str = "",
    temperature: float | str | None = 0.2,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Enqueue a jury_panel job and return a job_id immediately. Use poll_job to retrieve the result.
    expert_agents and jury_agents: comma-separated names from get_defaults.catalog_agents, or EMPTY for auto-split.
    timeout_sec: overrides the auto-calculated timeout (default: 60s × agents, capped at 600s)."""
    return _start_job(
        "jury_panel",
        {
            "task": task,
            "context": context,
            "expert_agents": expert_agents,
            "jury_agents": jury_agents,
            "include_transcript": include_transcript,
            "max_tokens": max_tokens,
            "swarm_roles": swarm_roles,
            "temperature": temperature,
        },
    )


def poll_job(job_id: str, include_result: bool = False) -> dict[str, Any]:
    """Poll the status of an async job started by start_run_panel, start_swarm_panel, or start_jury_panel.
    Set include_result=true to retrieve the full result once status is 'succeeded'."""
    return serialize_job(get_job(job_id), include_result=include_result)


if FastMCP is not None:
    mcp = FastMCP(
        "dev-converge",
        instructions=(
            "Multi-agent consensus and synthesis service. "
            "IMPORTANT: always call get_defaults first — it returns catalog_agents, the list of valid agent names. "
            "For agent_names parameters: leave EMPTY string to use all agents; pass comma-separated names for a subset. "
            "NEVER pass the string 'all' as agent_names — it is not a valid agent name. "
            "For complete_once: agent_name must be one of the names from catalog_agents. "
            "Providers: openai (direct, max_completion_tokens), openai_compatible (DashScope, max_tokens), "
            "anthropic (direct), anthropic_compatible, gemini_compatible. "
            "Use ping_models to health-check agents, run_panel/swarm_panel/jury_panel/triangular_panel for multi-agent synthesis, "
            "start_* variants for async jobs, poll_job to retrieve results."
        ),
        transport_security=_build_transport_security(),
    )
    mcp.tool()(get_defaults)
    mcp.tool()(ping_models)
    mcp.tool()(complete_once)
    mcp.tool()(run_panel)
    mcp.tool()(swarm_panel)
    mcp.tool()(jury_panel)
    mcp.tool()(triangular_panel)
    mcp.tool()(start_run_panel)
    mcp.tool()(start_swarm_panel)
    mcp.tool()(start_jury_panel)
    mcp.tool()(poll_job)
else:  # pragma: no cover
    mcp = None


def _auth_wrapper(inner):
    from starlette.responses import JSONResponse

    class _AuthWrap:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            headers = dict(scope.get("headers", []))

            # Auth check
            label = "anonymous"
            tokens = settings.api_tokens
            if tokens:
                auth = (headers.get(b"authorization") or b"").decode()
                if not auth.startswith("Bearer "):
                    response = JSONResponse(
                        status_code=401, content={"detail": "Missing bearer token"}
                    )
                    await response(scope, receive, send)
                    return
                token = auth[7:]
                if token not in tokens:
                    response = JSONResponse(
                        status_code=401, content={"detail": "Invalid bearer token"}
                    )
                    await response(scope, receive, send)
                    return
                label = tokens[token]

            # Decode agent catalog
            agents_header = (headers.get(b"x-dev-converge-agents") or b"").decode()
            catalog: list[AgentSpec] = []
            default_synth = ""
            if agents_header:
                try:
                    catalog = decode_catalog(agents_header)
                    default_synth = get_default_synthesizer(agents_header)
                except ValueError as exc:
                    response = JSONResponse(
                        status_code=422,
                        content={"detail": f"Invalid X-Dev-Converge-Agents: {exc}"},
                    )
                    await response(scope, receive, send)
                    return

            token_state = _token_label.set(label)
            catalog_state = _request_catalog.set(catalog)
            synth_state = _default_synthesizer.set(default_synth)
            try:
                await self.app(scope, receive, send)
            finally:
                _token_label.reset(token_state)
                _request_catalog.reset(catalog_state)
                _default_synthesizer.reset(synth_state)

    return _AuthWrap(inner)


def get_mcp_sse_app():
    if mcp is None:
        return None
    app = mcp.sse_app()
    return _auth_wrapper(app)


def get_mcp_streamable_app():
    if mcp is None or not hasattr(mcp, "streamable_http_app"):
        return None
    inner_app = mcp.streamable_http_app()
    session_manager = mcp._session_manager

    class _RootAliasWrap:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            path = scope.get("path", "")
            if scope["type"] == "http" and path in {"", "/", "/mcp-http", "/mcp-http/"}:
                scope = dict(scope)
                scope["path"] = "/mcp"
                scope["raw_path"] = b"/mcp"
            await self.app(scope, receive, send)

    app = _auth_wrapper(_RootAliasWrap(inner_app))
    return app, session_manager


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Hosted dev-converge MCP server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    if mcp is None:
        raise SystemExit("mcp package is not installed")
    mcp.settings.port = args.port
    mcp.run(transport=args.transport)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
