"""Fake browser crawler for DOU leiturajornal pages with rotating user agents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import random
import time
from typing import Dict, Iterable, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
import http.cookiejar

from crawler.user_agent_rotator import UserAgentRotator, create_default_rotator


@dataclass(slots=True)
class BrowseResult:
    day: str
    url: str
    user_agent: str
    status_code: int
    body_bytes: int
    elapsed_ms: int
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class FakeBrowserConfig:
    years: int = 5
    timeout_seconds: int = 30
    sleep_min_seconds: float = 0.15
    sleep_max_seconds: float = 0.6
    max_consecutive_failures: int = 30
    seed: int = 42


class DOUFakeBrowser:
    def __init__(self, rotator: UserAgentRotator | None = None, timeout_seconds: int = 30) -> None:
        self._rotator = rotator or create_default_rotator()
        self._timeout_seconds = timeout_seconds
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._cookie_jar))

    @staticmethod
    def _build_url(target_day: date) -> str:
        qs = urlencode({"data": target_day.strftime("%d-%m-%Y")})
        return f"https://www.in.gov.br/leiturajornal?{qs}"

    def _build_headers(self, user_agent: str, referer: str | None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def browse_day(self, target_day: date, referer: str | None = None) -> BrowseResult:
        user_agent = self._rotator.next()
        url = self._build_url(target_day)
        headers = self._build_headers(user_agent=user_agent, referer=referer)
        request = Request(url=url, headers=headers, method="GET")

        t0 = time.monotonic()
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = response.read()
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                code = int(getattr(response, "status", 200))
                return BrowseResult(
                    day=target_day.isoformat(),
                    url=url,
                    user_agent=user_agent,
                    status_code=code,
                    body_bytes=len(body),
                    elapsed_ms=elapsed_ms,
                    ok=200 <= code < 400,
                )
        except HTTPError as ex:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return BrowseResult(
                day=target_day.isoformat(),
                url=url,
                user_agent=user_agent,
                status_code=int(ex.code),
                body_bytes=0,
                elapsed_ms=elapsed_ms,
                ok=False,
                error=f"HTTPError: {ex.reason}",
            )
        except URLError as ex:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return BrowseResult(
                day=target_day.isoformat(),
                url=url,
                user_agent=user_agent,
                status_code=0,
                body_bytes=0,
                elapsed_ms=elapsed_ms,
                ok=False,
                error=f"URLError: {ex.reason}",
            )
        except Exception as ex:  # pragma: no cover - operational fallback
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return BrowseResult(
                day=target_day.isoformat(),
                url=url,
                user_agent=user_agent,
                status_code=0,
                body_bytes=0,
                elapsed_ms=elapsed_ms,
                ok=False,
                error=f"Exception: {ex}",
            )


def iter_last_days(years: int) -> Iterable[date]:
    if years < 1:
        raise ValueError("years must be >= 1")
    end = date.today()
    start = end - timedelta(days=years * 365)
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def run_fake_browse(config: FakeBrowserConfig) -> Tuple[List[BrowseResult], Dict[str, int | float]]:
    random.seed(config.seed)
    browser = DOUFakeBrowser(timeout_seconds=config.timeout_seconds)

    results: List[BrowseResult] = []
    consecutive_failures = 0
    referer: str | None = None

    for idx, target_day in enumerate(iter_last_days(config.years), start=1):
        result = browser.browse_day(target_day=target_day, referer=referer)
        results.append(result)

        if result.ok:
            consecutive_failures = 0
            referer = result.url
        else:
            consecutive_failures += 1

        if idx % 50 == 0 or not result.ok:
            label = "OK" if result.ok else "FAIL"
            print(
                f"[{idx}] {label} {result.day} status={result.status_code} "
                f"bytes={result.body_bytes} ua='{result.user_agent[:45]}...' ms={result.elapsed_ms}"
            )

        if consecutive_failures >= config.max_consecutive_failures:
            print(
                f"Stopping early after {consecutive_failures} consecutive failures. "
                "This usually indicates temporary blocking."
            )
            break

        sleep_s = random.uniform(config.sleep_min_seconds, config.sleep_max_seconds)
        time.sleep(sleep_s)

    total = len(results)
    ok = sum(1 for r in results if r.ok)
    failures = total - ok
    status_403 = sum(1 for r in results if r.status_code == 403)
    summary: Dict[str, int | float] = {
        "total_requests": total,
        "ok_requests": ok,
        "failed_requests": failures,
        "http_403": status_403,
        "success_rate": round((ok / total) * 100, 2) if total else 0.0,
        "avg_elapsed_ms": int(sum(r.elapsed_ms for r in results) / total) if total else 0,
        "avg_body_bytes": int(sum(r.body_bytes for r in results) / total) if total else 0,
    }
    return results, summary


def write_report(path: str, results: List[BrowseResult], summary: Dict[str, int | float]) -> None:
    payload = {
        "summary": summary,
        "results": [r.__dict__ for r in results],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
