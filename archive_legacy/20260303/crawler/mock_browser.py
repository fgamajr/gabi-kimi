"""Deterministic mock browser runtime for DSL crawl engine."""

from __future__ import annotations

from dataclasses import dataclass
import random
import time
from urllib.parse import urljoin, urlparse

from crawler.dsl_schema import MockRule, parse_duration_to_ms


@dataclass(slots=True)
class MockPage:
    url: str


class MockBrowser:
    def __init__(self, rules: list[MockRule], timeout: str = "20s", latency_ms: int = 0, seed: int = 42) -> None:
        self._rules = rules
        self._timeout_ms = parse_duration_to_ms(timeout)
        self._latency_ms = max(0, latency_ms)
        self._rng = random.Random(seed)
        self._current: MockPage | None = None

    def load(self, url: str) -> MockPage:
        self._simulate_latency()
        self._current = MockPage(url=url)
        return self._current

    def wait_for(self, selector: str) -> bool:
        self._simulate_latency()
        if not self._current:
            return False
        links = self.extract_links(selector=selector, attribute="href")
        return len(links) > 0

    def extract_links(self, selector: str, attribute: str = "href") -> list[str]:
        self._simulate_latency()
        if not self._current:
            return []

        rule = self._match_rule(self._current.url)
        if rule is None:
            return []

        sel_rule = rule.selectors.get(selector)
        if sel_rule is None:
            return []

        base = self._base_url(self._current.url)
        out: list[str] = []
        for i in range(1, max(0, sel_rule.count) + 1):
            token = self._token(self._current.url, selector, i)
            rendered = (
                sel_rule.url_template.replace("{i}", str(i))
                .replace("{n}", f"{i:02d}")
                .replace("{token}", token)
                .replace("{base}", base)
                .replace("{current}", self._current.url)
            )
            out.append(urljoin(self._current.url, rendered))
        return out

    def _match_rule(self, url: str) -> MockRule | None:
        for rule in self._rules:
            if rule.when_contains and rule.when_contains in url:
                return rule
        return None

    def _token(self, url: str, selector: str, idx: int) -> str:
        # Deterministic pseudo-random token per (url, selector, idx).
        seeded = f"{url}|{selector}|{idx}"
        h = abs(hash(seeded)) % 999999
        jitter = self._rng.randint(100, 999)
        return f"{h:06d}{jitter}"

    def _base_url(self, url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def _simulate_latency(self) -> None:
        if self._latency_ms <= 0:
            return
        # Small deterministic latency window.
        delay = self._latency_ms + self._rng.randint(0, 7)
        time.sleep(delay / 1000.0)
