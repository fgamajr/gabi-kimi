from __future__ import annotations

import asyncio
from typing import Any

from src.dev_converge.config import settings
from src.dev_converge.providers import AgentSpec, call_agent, resolve_agents


def _coerce_float(value: str | float | int | None, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _coerce_int(value: str | int | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _build_prompt(task: str, context: str = "", extras: str = "") -> str:
    parts = [f"Task:\n{task.strip()}"]
    if context.strip():
        parts.append(f"Context:\n{context.strip()}")
    if extras.strip():
        parts.append(extras.strip())
    return "\n\n".join(parts)


def _local_synthesis(title: str, outputs: list[dict[str, Any]]) -> str:
    lines = [title]
    for item in outputs:
        lines.append(
            f"- {item['agent']} ({item['provider']}): {str(item['output']).strip()[:700]}"
        )
    return "\n".join(lines)


async def _gather_agent_outputs(
    *,
    agents: list[AgentSpec],
    prompt_builder,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(settings.DEV_CONVERGE_MAX_PARALLEL_AGENTS, 1))

    async def _run(spec: AgentSpec, prompt: str) -> dict[str, Any]:
        async with semaphore:
            try:
                return await call_agent(
                    spec=spec,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                return {
                    "agent": spec.name,
                    "provider": spec.provider,
                    "model": spec.model,
                    "error": str(exc),
                    "output": "",
                }

    tasks = [_run(spec, prompt_builder(spec)) for spec in agents]
    return await asyncio.gather(*tasks)


async def get_defaults() -> dict[str, Any]:
    return {
        "service": "dev-converge",
        "version": "v1",
        "providers": [
            "openai",
            "openai_compatible",
            "anthropic",
            "anthropic_compatible",
            "gemini_compatible",
        ],
        "required_header": "X-Dev-Converge-Agents",
        "header_format": "base64url-encoded JSON: {agents: [{name, provider, model, api_key, base_url?}], default_synthesizer?}",
        "defaults": {
            "sync_timeout_sec": settings.DEV_CONVERGE_SYNC_TIMEOUT_SEC,
            "job_retention_hours": settings.DEV_CONVERGE_JOB_RETENTION_HOURS,
        },
    }


async def ping_models(
    task: str = "Say 'ready' and name your model.",
    agent_names: str = "",
    context: str = "",
    max_tokens: int | str | None = 120,
    temperature: float | str | None = 0.0,
    thinking: str = "low",
    catalog: list[AgentSpec] | None = None,
) -> dict[str, Any]:
    if catalog is None:
        catalog = []
    agents = resolve_agents(agent_names, catalog)
    prompt = _build_prompt(task, context, f"Reasoning effort hint: {thinking}")
    results = await _gather_agent_outputs(
        agents=agents,
        prompt_builder=lambda _spec: prompt,
        system_prompt="You are a concise model-health probe. Answer in one short paragraph.",
        temperature=_coerce_float(temperature, 0.0),
        max_tokens=_coerce_int(max_tokens, 120),
    )
    return {"task": task, "agents": [s.name for s in agents], "results": results}


async def complete_once(
    task: str,
    context: str = "",
    agent_name: str = "",
    system_prompt: str = "You are a concise expert assistant.",
    max_tokens: int | str | None = 1200,
    temperature: float | str | None = 0.2,
    thinking: str = "medium",
    catalog: list[AgentSpec] | None = None,
) -> dict[str, Any]:
    if catalog is None:
        catalog = []
    if not catalog:
        return {
            "error": "No agents in request catalog. Send X-Dev-Converge-Agents header."
        }
    if agent_name:
        agents = resolve_agents(agent_name, catalog)
        spec = agents[0]
    elif len(catalog) == 1:
        spec = catalog[0]
    else:
        return {
            "error": (
                "Multiple agents in catalog and no agent_name specified. "
                "Provide agent_name to select which agent to use for complete_once."
            )
        }
    prompt = _build_prompt(task, context, f"Reasoning effort hint: {thinking}")
    result = await call_agent(
        spec=spec,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    return {"task": task, "context": context, **result}


async def run_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    rounds: int | str | None = 1,
    temperature: float | str | None = 0.2,
    topology: str = "parallel",
    catalog: list[AgentSpec] | None = None,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    if catalog is None:
        catalog = []
    agents = resolve_agents(agent_names, catalog)
    prompt = _build_prompt(
        task,
        context,
        f"Panel topology: {topology}\nRounds requested: {_coerce_int(rounds, 1)}",
    )
    transcript = await _gather_agent_outputs(
        agents=agents,
        prompt_builder=lambda _spec: prompt,
        system_prompt="You are one member of an expert review panel. Provide your independent analysis.",
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    response: dict[str, Any] = {
        "job_type": "run_panel",
        "task": task,
        "agents": [s.name for s in agents],
        "summary": _local_synthesis("Panel synthesis", transcript),
        "result": _local_synthesis("Panel synthesis", transcript),
    }
    if include_transcript:
        response["transcript"] = transcript
    return response


async def swarm_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    swarm_roles: str = "",
    temperature: float | str | None = 0.2,
    catalog: list[AgentSpec] | None = None,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    if catalog is None:
        catalog = []
    agents = resolve_agents(agent_names, catalog)
    roles = [role.strip() for role in swarm_roles.split(",") if role.strip()]
    if not roles:
        roles = ["planner", "critic", "implementer"][: len(agents)]

    def _prompt(spec: AgentSpec) -> str:
        idx = [s.name for s in agents].index(spec.name) % len(roles)
        role = roles[idx]
        return _build_prompt(task, context, f"Swarm role: {role}")

    transcript = await _gather_agent_outputs(
        agents=agents,
        prompt_builder=_prompt,
        system_prompt="You are participating in a cooperative swarm. Lean into your assigned role.",
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    response: dict[str, Any] = {
        "job_type": "swarm_panel",
        "task": task,
        "agents": [s.name for s in agents],
        "roles": roles,
        "summary": _local_synthesis("Swarm synthesis", transcript),
        "result": _local_synthesis("Swarm synthesis", transcript),
    }
    if include_transcript:
        response["transcript"] = transcript
    return response


async def jury_panel(
    task: str,
    context: str = "",
    expert_agents: str = "",
    jury_agents: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    swarm_roles: str = "",
    temperature: float | str | None = 0.2,
    catalog: list[AgentSpec] | None = None,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    if catalog is None:
        catalog = []
    experts = resolve_agents(expert_agents, catalog)
    jurors = resolve_agents(jury_agents, catalog)
    if not jurors:
        jurors = experts[:2] if len(experts) >= 2 else experts
    expert_outputs = await _gather_agent_outputs(
        agents=experts,
        prompt_builder=lambda _spec: _build_prompt(task, context, "Role: expert"),
        system_prompt="You are an expert witness. Produce an independent answer.",
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    expert_summary = _local_synthesis("Expert submissions", expert_outputs)
    jury_outputs = await _gather_agent_outputs(
        agents=jurors,
        prompt_builder=lambda _spec: _build_prompt(
            task,
            context,
            f"Expert submissions:\n{expert_summary}\nJury role hints: {swarm_roles or 'review and decide'}",
        ),
        system_prompt="You are on the jury. Review the expert submissions and give a verdict.",
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    response: dict[str, Any] = {
        "job_type": "jury_panel",
        "task": task,
        "experts": [s.name for s in experts],
        "jury": [s.name for s in jurors],
        "summary": _local_synthesis("Jury synthesis", expert_outputs + jury_outputs),
        "result": _local_synthesis("Jury synthesis", expert_outputs + jury_outputs),
    }
    if include_transcript:
        response["transcript"] = {"experts": expert_outputs, "jury": jury_outputs}
    return response


async def triangular_panel(
    task: str,
    agent_names: str = "",
    context: str = "",
    include_transcript: bool = False,
    max_tokens: int | str | None = 1200,
    synthesizer: str = "",
    temperature: float | str | None = 0.2,
    catalog: list[AgentSpec] | None = None,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    if catalog is None:
        catalog = []
    agents = resolve_agents(agent_names, catalog)[:3]
    while len(agents) < 3:
        agents.append(agents[-1] if agents else catalog[0] if catalog else agents[0])

    initial = await _gather_agent_outputs(
        agents=agents,
        prompt_builder=lambda _spec: _build_prompt(
            task, context, "Phase 1: independent analysis"
        ),
        system_prompt="You are part of a triangular consensus review. Start with an independent analysis.",
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    critiques = await _gather_agent_outputs(
        agents=agents,
        prompt_builder=lambda spec: _build_prompt(
            task,
            context,
            "Phase 2: critique the other analyses.\n"
            + "\n".join(
                f"{item['agent']}: {item['output'][:500]}"
                for item in initial
                if item["agent"] != spec.name
            ),
        ),
        system_prompt="Critique the other analyses and identify gaps.",
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    revisions = await _gather_agent_outputs(
        agents=agents,
        prompt_builder=lambda spec: _build_prompt(
            task,
            context,
            "Phase 3: revise your analysis using the critique notes.\n"
            + "\n".join(
                f"{item['agent']}: {item['output'][:500]}"
                for item in critiques
                if item["agent"] != spec.name
            ),
        ),
        system_prompt="Revise your analysis after considering the critiques.",
        temperature=_coerce_float(temperature, 0.2),
        max_tokens=_coerce_int(max_tokens, 1200),
    )
    synth_name = synthesizer.strip() or (agents[0].name if agents else "")
    response: dict[str, Any] = {
        "job_type": "triangular_panel",
        "task": task,
        "agents": [s.name for s in agents],
        "synthesizer": synth_name,
        "summary": _local_synthesis("Triangular consensus", revisions),
        "result": _local_synthesis("Triangular consensus", revisions),
    }
    if include_transcript:
        response["transcript"] = {
            "initial": initial,
            "critiques": critiques,
            "revisions": revisions,
        }
    return response


async def execute_job(
    job_type: str, payload: dict[str, Any], catalog: list[AgentSpec]
) -> dict[str, Any]:
    if job_type == "run_panel":
        return await run_panel(**payload, catalog=catalog)
    if job_type == "swarm_panel":
        return await swarm_panel(**payload, catalog=catalog)
    if job_type == "jury_panel":
        return await jury_panel(**payload, catalog=catalog)
    raise ValueError(f"Unsupported async job type: {job_type}")
