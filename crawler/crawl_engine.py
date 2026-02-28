"""Generic declarative crawl engine operating in mock runtime mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from crawler.dsl_schema import CrawlSpec, ExtractStep, Step
from crawler.frontier import Frontier
from crawler.mock_browser import MockBrowser
from crawler.observability import CrawlerLogger


@dataclass(slots=True)
class CrawlRunState:
    run_id: str
    pages_processed: int = 0
    documents: list[str] = field(default_factory=list)
    documents_seen: set[str] = field(default_factory=set)


class CrawlEngine:
    def __init__(self, logger: CrawlerLogger | None = None) -> None:
        self._log = logger or CrawlerLogger(svc="mock-crawl", env="dev")

    def execute(self, spec: CrawlSpec) -> CrawlRunState:
        run_id = self._log.generate_run_id()
        browser = MockBrowser(
            rules=spec.mock_rules,
            timeout=spec.runtime.timeout,
            latency_ms=spec.runtime.latency_ms,
            seed=spec.runtime.seed,
        )
        frontier = Frontier()
        frontier.enqueue(spec.entry_url)

        state = CrawlRunState(run_id=run_id)

        self._log.emit_event(
            "crawl_started",
            run=run_id,
            entry=spec.entry_url,
            mode=spec.runtime.mode,
            max_pages=spec.termination.max_pages,
        )

        while not frontier.is_empty() and state.pages_processed < spec.termination.max_pages:
            current_url = frontier.dequeue()
            if not current_url:
                break
            if current_url in frontier.visited:
                continue

            step_context: dict[str, list[str]] = {}
            any_new_follow = False

            for step in spec.steps:
                if step.kind == "load":
                    if step.load == "entry" and state.pages_processed == 0:
                        target_url = spec.entry_url
                    else:
                        target_url = current_url
                    browser.load(target_url)
                    frontier.mark_visited(target_url)
                    current_url = target_url
                    state.pages_processed += 1
                    self._log.emit_event("page_loaded", run=run_id, url=current_url, page_no=state.pages_processed)
                    continue

                if step.kind == "wait" and step.wait:
                    ok = browser.wait_for(step.wait.selector)
                    self._log.emit_event(
                        "wait_satisfied",
                        run=run_id,
                        selector=step.wait.selector,
                        satisfied=ok,
                        url=current_url,
                    )
                    continue

                if step.kind == "extract" and step.extract:
                    links = browser.extract_links(step.extract.selector, attribute=step.extract.attribute)
                    links = self._normalize_links(links, current_url, step.extract.absolute)
                    if step.extract.deduplicate:
                        links = list(dict.fromkeys(links))
                    step_context[step.extract.name] = links

                    for link in links:
                        self._log.emit_event(
                            "link_extracted",
                            run=run_id,
                            url=current_url,
                            name=step.extract.name,
                            selector=step.extract.selector,
                            link=link,
                        )
                        if step.extract.emit == "document" and link not in state.documents_seen:
                            state.documents_seen.add(link)
                            state.documents.append(link)
                            self._log.emit_event("document_emitted", run=run_id, document_url=link)
                    continue

                if step.kind == "follow" and step.follow:
                    urls = step_context.get(step.follow.from_name, [])
                    count = frontier.enqueue_many(urls)
                    if count > 0:
                        any_new_follow = True
                    self._log.emit_event(
                        "follow_enqueued",
                        run=run_id,
                        from_name=step.follow.from_name,
                        count=count,
                    )
                    continue

            if spec.termination.stop_if_no_new and not any_new_follow and frontier.is_empty():
                self._log.emit_event("crawl_completed", run=run_id, reason="stop_if_no_new", pages=state.pages_processed, documents=len(state.documents))
                return state

        reason = "max_pages" if state.pages_processed >= spec.termination.max_pages else "exhausted"
        self._log.emit_event(
            "crawl_completed",
            run=run_id,
            reason=reason,
            pages=state.pages_processed,
            documents=len(state.documents),
        )
        return state

    def _normalize_links(self, links: list[str], base_url: str, absolute: bool) -> list[str]:
        if absolute:
            return [urljoin(base_url, link) for link in links]
        return links
