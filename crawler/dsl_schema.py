"""Schema objects for YAML-driven mock crawl DSL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeConfig:
    mode: str = "mock"
    wait_dom: str = "network_idle"
    timeout: str = "20s"
    seed: int = 42
    latency_ms: int = 0


@dataclass(slots=True)
class TerminationConfig:
    max_pages: int = 200
    stop_if_no_new: bool = False


@dataclass(slots=True)
class MockSelectorRule:
    count: int
    url_template: str


@dataclass(slots=True)
class MockRule:
    when_contains: str
    selectors: dict[str, MockSelectorRule] = field(default_factory=dict)


@dataclass(slots=True)
class WaitStep:
    selector: str


@dataclass(slots=True)
class ExtractStep:
    name: str
    selector: str
    attribute: str = "href"
    absolute: bool = True
    deduplicate: bool = True
    emit: str | None = None


@dataclass(slots=True)
class FollowStep:
    from_name: str


@dataclass(slots=True)
class Step:
    kind: str
    load: str | None = None
    wait: WaitStep | None = None
    extract: ExtractStep | None = None
    follow: FollowStep | None = None


@dataclass(slots=True)
class CrawlSpec:
    entry_url: str
    runtime: RuntimeConfig
    steps: list[Step]
    termination: TerminationConfig
    mock_rules: list[MockRule] = field(default_factory=list)


def parse_duration_to_ms(value: str) -> int:
    text = value.strip().lower()
    if text.endswith("ms") and text[:-2].isdigit():
        return int(text[:-2])
    if text.endswith("s") and text[:-1].isdigit():
        return int(text[:-1]) * 1000
    if text.isdigit():
        return int(text)
    return 20000


def crawl_spec_from_dict(root: dict[str, Any]) -> CrawlSpec:
    crawl = root.get("crawl", {}) or {}

    entry_url = str(crawl.get("entry", "")).strip()

    rt = crawl.get("runtime", {}) or {}
    runtime = RuntimeConfig(
        mode=str(rt.get("mode", "mock")),
        wait_dom=str(rt.get("wait_dom", "network_idle")),
        timeout=str(rt.get("timeout", "20s")),
        seed=int(rt.get("seed", 42)),
        latency_ms=int(rt.get("latency_ms", 0)),
    )

    tm = crawl.get("termination", {}) or {}
    termination = TerminationConfig(
        max_pages=int(tm.get("max_pages", 200)),
        stop_if_no_new=bool(tm.get("stop_if_no_new", False)),
    )

    steps: list[Step] = []
    for raw in crawl.get("steps", []) or []:
        if "load" in raw:
            steps.append(Step(kind="load", load=str(raw.get("load"))))
            continue
        if "wait" in raw:
            w = raw.get("wait") or {}
            steps.append(Step(kind="wait", wait=WaitStep(selector=str(w.get("selector", "")))))
            continue
        if "extract" in raw:
            ex = raw.get("extract") or {}
            steps.append(
                Step(
                    kind="extract",
                    extract=ExtractStep(
                        name=str(ex.get("name", "")),
                        selector=str(ex.get("selector", "")),
                        attribute=str(ex.get("attribute", "href")),
                        absolute=bool(ex.get("absolute", True)),
                        deduplicate=bool(ex.get("deduplicate", True)),
                        emit=ex.get("emit"),
                    ),
                )
            )
            continue
        if "follow" in raw:
            fw = raw.get("follow") or {}
            steps.append(Step(kind="follow", follow=FollowStep(from_name=str(fw.get("from", "")))))
            continue

    mock_rules: list[MockRule] = []
    for rr in crawl.get("mock_rules", []) or []:
        when = rr.get("when", {}) or {}
        selectors_raw = rr.get("selectors", {}) or {}
        selectors: dict[str, MockSelectorRule] = {}
        for sel, cfg in selectors_raw.items():
            selectors[str(sel)] = MockSelectorRule(
                count=int((cfg or {}).get("count", 0)),
                url_template=str((cfg or {}).get("url_template", "")),
            )
        mock_rules.append(MockRule(when_contains=str(when.get("contains", "")), selectors=selectors))

    return CrawlSpec(
        entry_url=entry_url,
        runtime=runtime,
        steps=steps,
        termination=termination,
        mock_rules=mock_rules,
    )
