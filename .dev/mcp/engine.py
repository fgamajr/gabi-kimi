from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

try:
    from .adapters import create_adapter
    from .config import config_summary, load_runtime_config
    from .diffing import unified_diff
    from .logger import RunLogger
    from .models import DiffItem, ReviewItem, ReviewResult, RoundResult, RunResult, SuggestionItem
    from .prompts import build_orchestrator_messages, build_review_messages
    from .selection import select_agents
except ImportError:
    from adapters import create_adapter
    from config import config_summary, load_runtime_config
    from diffing import unified_diff
    from logger import RunLogger
    from models import DiffItem, ReviewItem, ReviewResult, RoundResult, RunResult, SuggestionItem
    from prompts import build_orchestrator_messages, build_review_messages
    from selection import select_agents


class ConvergenceEngine:
    def __init__(self, config_path: str | None = None) -> None:
        self.config = load_runtime_config(config_path)

    def run(
        self,
        *,
        user_prompt: str,
        initial_artifact: str,
        artifact_kind: str = "code",
        conversation_history: list[dict[str, Any]] | None = None,
        orchestrator: str | None = None,
        reviewers: list[str] | None = None,
        max_rounds: int | None = None,
        run_label: str | None = None,
    ) -> RunResult:
        selection = select_agents(
            user_prompt,
            self.config,
            preferred_reviewers=reviewers,
            orchestrator=orchestrator,
        )
        rounds_limit = max_rounds or self.config.defaults.max_rounds
        logger = RunLogger(self.config.defaults.log_dir, run_label=run_label)
        logger.log_run_start(
            {
                "run_id": logger.run_id,
                "task": user_prompt,
                "artifact_kind": artifact_kind,
                "selected_agents": selection.to_dict(),
                "config": config_summary(self.config),
            }
        )

        current = initial_artifact
        rounds: list[RoundResult] = []
        last_unresolved: list[dict[str, Any]] = []

        for round_number in range(1, rounds_limit + 1):
            review_results = self._dispatch_reviews(
                round_number=round_number,
                selection=selection,
                user_prompt=user_prompt,
                artifact=current,
                conversation_history=conversation_history,
            )
            unanimous = all(review.verdict == "APPROVE" for review in review_results)
            if unanimous:
                revised = current
                orchestrator_response = None
            else:
                orchestrator_response = self._orchestrate(
                    round_number=round_number,
                    selection=selection,
                    user_prompt=user_prompt,
                    artifact_kind=artifact_kind,
                    artifact=current,
                    reviews=review_results,
                    conversation_history=conversation_history,
                )
                revised = orchestrator_response.content.strip("\n")
                if not revised:
                    revised = current

            diff_text = unified_diff(current, revised)
            zero_diff = revised == current
            converged = zero_diff and unanimous

            round_result = RoundResult(
                round_number=round_number,
                artifact_before=current,
                artifact_after=revised,
                reviews=review_results,
                diff_text=diff_text,
                zero_diff=zero_diff,
                unanimous_approve=unanimous,
                converged=converged,
                orchestrator_response=orchestrator_response,
            )
            logger.log_round(round_result)
            rounds.append(round_result)
            last_unresolved = _collect_unresolved(review_results)
            current = revised

            if converged:
                break

        result = RunResult(
            run_id=logger.run_id,
            selected_agents=selection,
            initial_artifact=initial_artifact,
            final_artifact=current,
            converged=bool(rounds and rounds[-1].converged),
            max_rounds_reached=bool(rounds and not rounds[-1].converged and len(rounds) >= rounds_limit),
            rounds=rounds,
            unresolved_objections=last_unresolved,
            run_dir=str(logger.run_dir),
        )
        logger.log_final(result.to_dict())
        return result

    def _dispatch_reviews(
        self,
        *,
        round_number: int,
        selection,
        user_prompt: str,
        artifact: str,
        conversation_history: list[dict[str, Any]] | None,
    ) -> list[ReviewResult]:
        def run_one(agent_name: str) -> ReviewResult:
            agent = self.config.agents[agent_name]
            provider = self.config.providers[agent.provider]
            adapter = create_adapter(provider, agent)
            messages = build_review_messages(
                agent=agent_name,
                persona=selection.personas.get(agent_name, "general"),
                round_number=round_number,
                user_prompt=user_prompt,
                artifact=artifact,
                conversation_history=conversation_history,
            )
            response = adapter.complete(
                messages,
                enable_thinking=agent.enable_thinking,
                stream=provider.streaming,
            )
            review = _parse_review(response.content, agent_name, round_number)
            review.meta.setdefault("tokens_used", response.usage.total_tokens)
            review.meta.setdefault("latency_ms", response.latency_ms)
            review.meta.setdefault("thinking_tokens", response.usage.thinking_tokens)
            review.raw_text = response.content
            return review

        reviewers = selection.reviewers
        if self.config.defaults.parallel and len(reviewers) > 1:
            with ThreadPoolExecutor(max_workers=len(reviewers)) as executor:
                return list(executor.map(run_one, reviewers))
        return [run_one(name) for name in reviewers]

    def _orchestrate(
        self,
        *,
        round_number: int,
        selection,
        user_prompt: str,
        artifact_kind: str,
        artifact: str,
        reviews: list[ReviewResult],
        conversation_history: list[dict[str, Any]] | None,
    ):
        agent = self.config.agents[selection.orchestrator]
        provider = self.config.providers[agent.provider]
        adapter = create_adapter(provider, agent)
        messages = build_orchestrator_messages(
            user_prompt=user_prompt,
            artifact_kind=artifact_kind,
            round_number=round_number,
            artifact=artifact,
            reviews=[item.to_dict() for item in reviews],
            conversation_history=conversation_history,
        )
        return adapter.complete(messages, enable_thinking=agent.enable_thinking, stream=provider.streaming)


def _parse_review(raw_text: str, agent_name: str, round_number: int) -> ReviewResult:
    data = _extract_json_object(raw_text)
    objections = [
        ReviewItem(
            severity=str(item.get("severity", "")),
            location=str(item.get("location", "")),
            description=str(item.get("description", "")),
            suggested_fix=str(item.get("suggested_fix", "")),
        )
        for item in (data.get("objections") or [])
        if isinstance(item, dict)
    ]
    suggestions = [
        SuggestionItem(
            type=str(item.get("type", "")),
            location=str(item.get("location", "")),
            description=str(item.get("description", "")),
        )
        for item in (data.get("suggestions") or [])
        if isinstance(item, dict)
    ]
    diffs = [
        DiffItem(file=str(item.get("file", "")), hunks=str(item.get("hunks", "")))
        for item in (data.get("diffs") or [])
        if isinstance(item, dict)
    ]
    verdict = str(data.get("verdict", "REQUEST_CHANGES")).upper()
    if verdict not in {"APPROVE", "REQUEST_CHANGES"}:
        verdict = "REQUEST_CHANGES"
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return ReviewResult(
        agent=agent_name,
        round=round_number,
        verdict=verdict,
        objections=objections,
        suggestions=suggestions,
        diffs=diffs,
        meta=meta,
    )


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    candidates = [stripped]
    if "```" in stripped:
        parts = stripped.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                candidates.append(part[4:].strip())
            elif part.startswith("{"):
                candidates.append(part)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    continue
    return {
        "verdict": "REQUEST_CHANGES",
        "objections": [
            {
                "severity": "high",
                "location": "",
                "description": "Reviewer did not return valid JSON",
                "suggested_fix": "Return a valid JSON review object",
            }
        ],
        "suggestions": [],
        "diffs": [],
        "meta": {"parse_error": True},
    }


def _collect_unresolved(reviews: list[ReviewResult]) -> list[dict[str, Any]]:
    unresolved: list[dict[str, Any]] = []
    for review in reviews:
        if review.verdict == "APPROVE":
            continue
        for objection in review.objections:
            unresolved.append(
                {
                    "agent": review.agent,
                    "severity": objection.severity,
                    "location": objection.location,
                    "description": objection.description,
                    "suggested_fix": objection.suggested_fix,
                }
            )
    return unresolved
