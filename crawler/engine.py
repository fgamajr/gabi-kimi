"""Generic YAML-driven crawling engine (site-agnostic)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
import time
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

import yaml

from crawler.dsl_schema import CrawlPlan, LinkExtractionRule, NavigationStep, expand_entry_urls
from crawler.dsl_validator import validate_plan_or_raise
from crawler.observability import CrawlerLogger
from crawler.pagination_strategies import resolve_strategy


@dataclass(slots=True)
class Page:
    url: str
    status_code: int
    html: str
    loaded_at_ms: int


class RuntimeAdapter(Protocol):
    def load(self, url: str) -> Page: ...

    def wait_for(self, selector: str, timeout_ms: int) -> bool: ...

    def extract(self, selector: str, attribute: str = "href") -> list[str]: ...

    def click(self, selector: str) -> bool: ...

    def scroll(self) -> bool: ...

    def current_url(self) -> str: ...

    def current_html(self) -> str: ...


class _AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        data = {k: (v or "") for k, v in attrs}
        self.links.append(data)


class HttpRuntime:
    """Minimal HTTP runtime for DSL execution.

    Selector support intentionally generic but constrained:
    - "a" returns all anchor href values
    - "a.class-name" returns href for anchors where class contains class-name
    """

    def __init__(self, timeout_ms: int = 30000) -> None:
        self._timeout_sec = max(1, int(timeout_ms / 1000))
        self._last_page: Page | None = None

    def load(self, url: str) -> Page:
        req = Request(
            url=url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        started = int(time.time() * 1000)
        with urlopen(req, timeout=self._timeout_sec) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            code = int(getattr(resp, "status", 200))
            page = Page(url=url, status_code=code, html=html, loaded_at_ms=started)
            self._last_page = page
            return page

    def wait_for(self, selector: str, timeout_ms: int) -> bool:
        # HTTP runtime has no async DOM mutation; check current snapshot only.
        return bool(self.extract(selector, attribute="href"))

    def extract(self, selector: str, attribute: str = "href") -> list[str]:
        html = self.current_html()
        parser = _AnchorExtractor()
        parser.feed(html)

        selector = (selector or "").strip()
        if not selector.startswith("a"):
            return []

        class_filter: str | None = None
        if selector.startswith("a."):
            class_filter = selector[2:].strip()

        out: list[str] = []
        for anchor in parser.links:
            if class_filter:
                classes = (anchor.get("class") or "").split()
                if class_filter not in classes:
                    continue
            value = anchor.get(attribute, "")
            if value:
                out.append(value)
        return out

    def click(self, selector: str) -> bool:
        links = self.extract(selector=selector, attribute="href")
        if not links:
            return False
        next_url = links[0]
        next_url = urljoin(self.current_url(), next_url)
        self.load(next_url)
        return True

    def scroll(self) -> bool:
        return False

    def current_url(self) -> str:
        return self._last_page.url if self._last_page else ""

    def current_html(self) -> str:
        return self._last_page.html if self._last_page else ""


class HeadlessBrowserRuntime:
    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    def load(self, url: str) -> Page:
        raise NotImplementedError("headless_browser runtime is reserved for future Playwright integration")

    def wait_for(self, selector: str, timeout_ms: int) -> bool:
        raise NotImplementedError

    def extract(self, selector: str, attribute: str = "href") -> list[str]:
        raise NotImplementedError

    def click(self, selector: str) -> bool:
        raise NotImplementedError

    def scroll(self) -> bool:
        raise NotImplementedError

    def current_url(self) -> str:
        return ""

    def current_html(self) -> str:
        return ""


@dataclass(slots=True)
class CrawlState:
    run_id: str
    queue: deque[str]
    visited_urls: set[str] = field(default_factory=set)
    visited_fingerprints: set[str] = field(default_factory=set)
    pages_processed: int = 0
    links_extracted: int = 0


class DynamicCrawlerEngine:
    def __init__(self, logger: CrawlerLogger | None = None) -> None:
        self._log = logger or CrawlerLogger(svc="crawler-engine", env="dev")

    def load_plan(self, path: str) -> CrawlPlan:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return validate_plan_or_raise(data)

    def execute_plan(self, plan: CrawlPlan, env: str | None = None) -> CrawlState:
        if env:
            self._log = CrawlerLogger(svc="crawler-engine", env=env)

        run_id = self._log.generate_run_id()
        entry_urls = [self._normalize_url(u, plan) for u in expand_entry_urls(plan.entry)]
        traversal = plan.runtime.traversal.lower()
        queue: deque[str] = deque(entry_urls)

        runtime = self._build_runtime(plan)
        state = CrawlState(run_id=run_id, queue=queue)

        start_date = entry_urls[0] if entry_urls else ""
        end_date = entry_urls[-1] if entry_urls else ""
        self._log.run_started(run=run_id, years=0, start_date=start_date, end_date=end_date, mode=plan.runtime.mode)

        terminated_reason = "exhausted"

        while state.queue:
            if state.pages_processed >= plan.termination.max_pages:
                terminated_reason = "max_pages"
                break

            url = self._dequeue(state, traversal)
            if url in state.visited_urls:
                self._log.emit_event("page_skipped_duplicate", run=run_id, url=url)
                continue

            page = self._safe_load(runtime, url, run_id)
            if page is None:
                continue

            state.visited_urls.add(url)
            state.pages_processed += 1
            self._log.emit_event(
                "page_loaded",
                run=run_id,
                url=page.url,
                status_code=page.status_code,
                page_no=state.pages_processed,
            )

            if plan.termination.stop_if_duplicate_page:
                fp = hashlib.sha1(page.html.encode("utf-8", errors="ignore")).hexdigest()[:16]
                if fp in state.visited_fingerprints:
                    terminated_reason = "duplicate_page"
                    break
                state.visited_fingerprints.add(fp)

            nav_store: dict[str, list[str]] = {}
            for step in plan.navigation:
                self._execute_step(runtime, step, run_id, nav_store)

            new_links = self._extract_links(runtime, plan, run_id, page.url)
            state.links_extracted += len(new_links)

            next_urls = self._advance_pagination(runtime, plan, run_id, current_url=page.url)
            for next_url in next_urls:
                normalized = self._normalize_relative(next_url, page.url, plan)
                if normalized and normalized not in state.visited_urls:
                    state.queue.append(normalized)

            if plan.termination.stop_if_no_new_links and not new_links and not next_urls:
                terminated_reason = "no_new_links"
                break

        self._log.emit_event(
            "crawl_terminated",
            run=run_id,
            reason=terminated_reason,
            pages=state.pages_processed,
            links=state.links_extracted,
        )
        self._log.run_completed(
            run=run_id,
            duration_ms=0,
            total_targets=state.pages_processed,
            ok=state.pages_processed,
            fail=0,
            success_rate=1.0 if state.pages_processed else 0.0,
        )
        return state

    def _build_runtime(self, plan: CrawlPlan) -> RuntimeAdapter:
        if plan.runtime.mode == "http":
            return HttpRuntime(timeout_ms=plan.runtime.timeout_ms)
        if plan.runtime.mode == "headless_browser":
            return HeadlessBrowserRuntime()
        raise ValueError(f"unsupported runtime mode: {plan.runtime.mode}")

    def _safe_load(self, runtime: RuntimeAdapter, url: str, run_id: str) -> Page | None:
        try:
            return runtime.load(url)
        except Exception as ex:
            self._log.error(run=run_id, stage="request", error_type=type(ex).__name__, error_message=str(ex), day=url)
            return None

    def _execute_step(
        self,
        runtime: RuntimeAdapter,
        step: NavigationStep,
        run_id: str,
        nav_store: dict[str, list[str]],
    ) -> None:
        step_key = step.action
        if step.only_if and step.only_if.exists:
            exists = bool(runtime.extract(step.only_if.exists, attribute="href"))
            if not exists:
                return

        self._log.emit_event("step_started", run=run_id, action=step_key, selector=step.selector or "")
        try:
            if step.action == "load":
                pass
            elif step.action == "wait_for":
                runtime.wait_for(step.selector or "", timeout_ms=step.timeout_ms or 5000)
            elif step.action == "extract_links":
                links = runtime.extract(step.selector or "", attribute=step.attribute or "href")
                if step.store_as:
                    nav_store[step.store_as] = links
            elif step.action == "click":
                runtime.click(step.selector or "")
            elif step.action == "scroll":
                max_scrolls = max(1, int(step.max_scrolls or 1))
                for _ in range(max_scrolls):
                    runtime.scroll()
                    delay = int(step.wait_after_scroll_ms or 0)
                    if delay > 0:
                        time.sleep(delay / 1000.0)
            elif step.action == "sleep":
                delay = int(step.wait_after_scroll_ms or 0)
                if delay > 0:
                    time.sleep(delay / 1000.0)
        except Exception as ex:
            self._log.error(run=run_id, stage="request", error_type=type(ex).__name__, error_message=str(ex))
        finally:
            self._log.emit_event("step_completed", run=run_id, action=step_key, selector=step.selector or "")

    def _extract_links(self, runtime: RuntimeAdapter, plan: CrawlPlan, run_id: str, current_url: str) -> list[str]:
        all_links: list[str] = []
        for rule in plan.extraction.links:
            links = runtime.extract(rule.selector, attribute=rule.attribute)
            links = self._apply_link_filter(links, rule)
            for raw in links:
                resolved = self._normalize_relative(raw, current_url, plan)
                if resolved:
                    self._log.emit_event("link_extracted", run=run_id, link=resolved, rule=rule.name)
                    all_links.append(resolved)
        return all_links

    def _advance_pagination(self, runtime: RuntimeAdapter, plan: CrawlPlan, run_id: str, current_url: str) -> list[str]:
        strategy = resolve_strategy(plan.pagination.strategy)
        try:
            outcome = strategy.advance(runtime, plan.pagination)
        except Exception as ex:
            self._log.error(run=run_id, stage="request", error_type=type(ex).__name__, error_message=str(ex))
            return []

        resolved = [self._normalize_relative(u, current_url, plan) for u in outcome.discovered_urls]
        next_urls = [u for u in resolved if u]
        self._log.emit_event(
            "pagination_advance",
            run=run_id,
            strategy=plan.pagination.strategy,
            discovered=len(next_urls),
            advanced=outcome.advanced,
            attempts=outcome.attempts,
        )
        return next_urls

    def _apply_link_filter(self, links: list[str], rule: LinkExtractionRule) -> list[str]:
        if not rule.filter or not rule.filter.contains:
            return links
        return [link for link in links if rule.filter and rule.filter.contains in link]

    def _normalize_relative(self, url: str, base_url: str, plan: CrawlPlan) -> str:
        if not url:
            return ""
        resolved = urljoin(base_url, url) if plan.url_resolution.resolve_relative else url
        return self._normalize_url(resolved, plan)

    def _normalize_url(self, url: str, plan: CrawlPlan) -> str:
        if not plan.url_resolution.normalize:
            return url
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        normalized = parsed._replace(netloc=netloc, path=path)
        return urlunparse(normalized)

    def _dequeue(self, state: CrawlState, traversal: str) -> str:
        if traversal == "dfs":
            return state.queue.pop()
        return state.queue.popleft()
