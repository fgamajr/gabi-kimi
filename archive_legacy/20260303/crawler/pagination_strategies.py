"""Pagination strategy implementations for the DSL engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from crawler.dsl_schema import PaginationConfig


class RuntimeAdapter(Protocol):
    def extract(self, selector: str, attribute: str = "href") -> list[str]: ...

    def click(self, selector: str) -> bool: ...

    def scroll(self) -> bool: ...


@dataclass(slots=True)
class PaginationOutcome:
    discovered_urls: list[str] = field(default_factory=list)
    advanced: bool = False
    attempts: int = 0


class PaginationStrategy(Protocol):
    def advance(self, runtime: RuntimeAdapter, config: PaginationConfig) -> PaginationOutcome: ...


class ClickNextStrategy:
    def advance(self, runtime: RuntimeAdapter, config: PaginationConfig) -> PaginationOutcome:
        ok = runtime.click(config.selector or "")
        return PaginationOutcome(discovered_urls=[], advanced=ok, attempts=1)


class NumberedStrategy:
    def advance(self, runtime: RuntimeAdapter, config: PaginationConfig) -> PaginationOutcome:
        links = runtime.extract(config.selector or "", attribute=config.extract_attribute or "href")
        return PaginationOutcome(discovered_urls=links, advanced=bool(links), attempts=1)


class DiscoverLinksStrategy:
    def advance(self, runtime: RuntimeAdapter, config: PaginationConfig) -> PaginationOutcome:
        links = runtime.extract(config.selector or "", attribute=config.extract_attribute or "href")
        if config.follow_if:
            links = [url for url in links if config.follow_if in url]
        if config.deduplicate:
            seen: set[str] = set()
            deduped: list[str] = []
            for link in links:
                if link in seen:
                    continue
                seen.add(link)
                deduped.append(link)
            links = deduped
        return PaginationOutcome(discovered_urls=links, advanced=bool(links), attempts=1)


class ScrollStrategy:
    def advance(self, runtime: RuntimeAdapter, config: PaginationConfig) -> PaginationOutcome:
        max_scrolls = max(1, int(config.max_scrolls or 1))
        advances = 0
        for _ in range(max_scrolls):
            if runtime.scroll():
                advances += 1
            else:
                break
        return PaginationOutcome(discovered_urls=[], advanced=advances > 0, attempts=max_scrolls)


def resolve_strategy(strategy_name: str) -> PaginationStrategy:
    mapping: dict[str, PaginationStrategy] = {
        "click_next": ClickNextStrategy(),
        "numbered": NumberedStrategy(),
        "discover_links": DiscoverLinksStrategy(),
        "scroll": ScrollStrategy(),
    }
    strategy = mapping.get(strategy_name)
    if strategy is None:
        raise ValueError(f"unsupported pagination strategy: {strategy_name}")
    return strategy
