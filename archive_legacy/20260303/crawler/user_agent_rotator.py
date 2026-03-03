"""User-Agent rotation primitives for crawler requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List


DEFAULT_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/125.0.0.0 Safari/537.36",
]


@dataclass(slots=True)
class UserAgentRotator:
    """Deterministic round-robin user-agent rotator."""

    user_agents: List[str]
    _idx: int = field(default=0, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        cleaned = [ua.strip() for ua in self.user_agents if ua and ua.strip()]
        if not cleaned:
            raise ValueError("User agent list cannot be empty.")
        self.user_agents = cleaned

    def next(self) -> str:
        with self._lock:
            ua = self.user_agents[self._idx]
            self._idx = (self._idx + 1) % len(self.user_agents)
            return ua

    def next_headers(self) -> Dict[str, str]:
        return {"User-Agent": self.next()}


def create_default_rotator() -> UserAgentRotator:
    return UserAgentRotator(user_agents=list(DEFAULT_USER_AGENTS))
