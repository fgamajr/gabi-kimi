from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ProviderConfig:
    name: str
    base_url: str
    key_env: str
    sdk: str
    streaming: bool = True
    thinking_param: str | None = None


@dataclass(slots=True)
class AgentConfig:
    name: str
    provider: str
    model: str
    key_env: str | None = None
    enable_thinking: bool = False
    context_window: int | None = None
    max_response: int | None = None
    personas: list[str] = field(default_factory=list)
    pricing: dict[str, float] = field(default_factory=dict)
    output_config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConvergenceConfig:
    zero_diff: bool = True
    unanimous_approve: bool = True


@dataclass(slots=True)
class DefaultsConfig:
    max_rounds: int = 5
    parallel: bool = True
    log_dir: str = ".dev/mcp/runs"
    convergence: ConvergenceConfig = field(default_factory=ConvergenceConfig)


@dataclass(slots=True)
class RuntimeConfig:
    providers: dict[str, ProviderConfig]
    agents: dict[str, AgentConfig]
    defaults: DefaultsConfig
    config_path: Path


@dataclass(slots=True)
class AgentSelection:
    orchestrator: str
    reviewers: list[str]
    personas: dict[str, str]
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    thinking_tokens: int = 0
    estimated_cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProviderResponse:
    content: str
    reasoning: str = ""
    usage: UsageStats = field(default_factory=UsageStats)
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["usage"] = self.usage.to_dict()
        return data


@dataclass(slots=True)
class ReviewItem:
    severity: str = ""
    location: str = ""
    description: str = ""
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SuggestionItem:
    type: str = ""
    location: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DiffItem:
    file: str = ""
    hunks: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReviewResult:
    agent: str
    round: int
    verdict: str
    objections: list[ReviewItem] = field(default_factory=list)
    suggestions: list[SuggestionItem] = field(default_factory=list)
    diffs: list[DiffItem] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "round": self.round,
            "verdict": self.verdict,
            "objections": [item.to_dict() for item in self.objections],
            "suggestions": [item.to_dict() for item in self.suggestions],
            "diffs": [item.to_dict() for item in self.diffs],
            "meta": self.meta,
            "raw_text": self.raw_text,
        }


@dataclass(slots=True)
class RoundResult:
    round_number: int
    artifact_before: str
    artifact_after: str
    reviews: list[ReviewResult]
    diff_text: str
    zero_diff: bool
    unanimous_approve: bool
    converged: bool
    orchestrator_response: ProviderResponse | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "diff_text": self.diff_text,
            "zero_diff": self.zero_diff,
            "unanimous_approve": self.unanimous_approve,
            "converged": self.converged,
            "reviews": [item.to_dict() for item in self.reviews],
            "orchestrator_response": (
                self.orchestrator_response.to_dict() if self.orchestrator_response else None
            ),
        }


@dataclass(slots=True)
class RunResult:
    run_id: str
    selected_agents: AgentSelection
    initial_artifact: str
    final_artifact: str
    converged: bool
    max_rounds_reached: bool
    rounds: list[RoundResult]
    unresolved_objections: list[dict[str, Any]]
    run_dir: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "selected_agents": self.selected_agents.to_dict(),
            "final_artifact": self.final_artifact,
            "converged": self.converged,
            "max_rounds_reached": self.max_rounds_reached,
            "rounds": [item.to_dict() for item in self.rounds],
            "unresolved_objections": self.unresolved_objections,
            "run_dir": self.run_dir,
        }
