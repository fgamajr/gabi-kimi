from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import random
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from crawler.user_agent_rotator import create_default_rotator


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        data = {k: (v or "") for k, v in attrs}
        href = data.get("href")
        if href:
            self.links.append(href)


@dataclass(slots=True)
class SamplerConfig:
    start_year: int = 2010
    end_year: int | None = None
    sample_dates: int = 200
    max_articles: int = 200
    timeout_sec: int = 25
    seed: int = 42
    delay_sec: float = 1.5
    max_retries: int = 2
    min_embedded_links: int = 150
    max_partial_retries: int = 3

    def resolved_end_year(self) -> int:
        return self.end_year if self.end_year is not None else date.today().year


class CorpusSampler:
    _PARAMS_SCRIPT_IDS = (
        "params",
        "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params",
    )
    _SECTIONS = ("do1", "do2", "do3", "doe", "do1e", "do2e", "do3e", "do1a")
    _COMPLETENESS_GUARD_SECTIONS = ("do1", "do2", "do3")
    _PAGINATION_QUERY_KEYS = ("page", "p", "currentPage", "delta", "start", "offset")
    _PAGINATION_GUARD_MSG = (
        "DOU leiturajornal pagination crawl is forbidden: this endpoint uses SPA client pagination "
        "over an already complete embedded jsonArray dataset. Use script#params payload as full issue data."
    )

    def __init__(self, cfg: SamplerConfig) -> None:
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.rot = create_default_rotator()
        self._request_count = 0
        self._capture_seq: int = 0
        self.errors: list[dict[str, Any]] = []
        self.empty_dates: list[str] = []
        self.unstable_days: list[dict[str, Any]] = []
        self.listings: list[dict[str, Any]] = []

    def build(self, out_dir: Path) -> dict[str, Any]:
        out_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = out_dir / "_checkpoint.json"

        # Resume from checkpoint if exists
        completed_urls: set[str] = set()
        idx: list[dict[str, Any]] = []
        if checkpoint_path.exists():
            cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            idx = cp.get("items", [])
            completed_urls = {item["article_url"] for item in idx}
            self.errors = cp.get("errors", [])
            self.empty_dates = cp.get("empty_dates", [])
            self.unstable_days = cp.get("unstable_days", [])
            self.listings = cp.get("listings", [])
            self._capture_seq = cp.get("capture_sequence", 0)
            self._log(f"Resuming from checkpoint: {len(idx)} articles, {len(self.listings)} listings already captured")

        dates = self._random_dates()
        article_pool: list[dict[str, Any]] = []
        saved_listing_keys: set[str] = {
            (ls["date"], ls["section"]) for ls in self.listings
        } if self.listings else set()

        for i, d in enumerate(dates, start=1):
            discovered, unstable, listing_captures = self._discover_articles_by_date(d)
            if unstable is not None:
                self.unstable_days.append(unstable)
                self._log(f"unstable_day date={d.isoformat()} reason={unstable.get('reason')}")
                continue

            # Save listing HTML to disk
            for lc in listing_captures:
                lc_key = (lc["date"], lc["section"])
                if lc_key in saved_listing_keys:
                    continue
                ld = date.fromisoformat(lc["date"])
                listing_rel = Path(str(ld.year)) / f"{ld.month:02d}" / f"{ld.day:02d}" / f"_listing_{lc['section']}.listing"
                listing_fp = out_dir / listing_rel
                listing_fp.parent.mkdir(parents=True, exist_ok=True)
                listing_fp.write_text(lc["listing_html"], encoding="utf-8")
                self._capture_seq += 1
                self.listings.append({
                    "date": lc["date"],
                    "section": lc["section"],
                    "listing_url": lc["listing_url"],
                    "file": str(listing_rel),
                    "sha256": lc["sha256"],
                    "article_count": lc["article_count"],
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "capture_sequence": self._capture_seq,
                })
                saved_listing_keys.add(lc_key)

            if not discovered:
                self.empty_dates.append(d.isoformat())
            article_pool.extend(discovered)
            if i % 10 == 0:
                self._log(f"Listing progress: {i}/{len(dates)} dates scanned, {len(article_pool)} links found")

        seen = set()
        unique_pool = []
        for item in article_pool:
            u = item["article_url"]
            if u in seen:
                continue
            seen.add(u)
            unique_pool.append(item)

        self.rng.shuffle(unique_pool)
        selected = unique_pool[: self.cfg.max_articles]

        self._log(f"Downloading {len(selected)} articles ({len(completed_urls)} already cached)")

        for i, item in enumerate(selected, start=1):
            u = item["article_url"]
            d = date.fromisoformat(item["date"])
            h = hashlib.sha1(u.encode("utf-8")).hexdigest()[:12]
            rel = Path(str(d.year)) / f"{d.month:02d}" / f"{d.day:02d}" / f"{h}.html"
            fp = out_dir / rel

            # Skip already downloaded
            if u in completed_urls and fp.exists():
                continue

            html = self._get(u)
            if html is None:
                self.errors.append({"phase": "article", "url": u, "date": item["date"]})
                continue
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(html, encoding="utf-8")
            article_sha256 = hashlib.sha256(html.encode("utf-8")).hexdigest()
            self._capture_seq += 1
            idx.append({
                **item,
                "file": str(rel),
                "sha256": article_sha256,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "capture_sequence": self._capture_seq,
            })

            if i % 10 == 0:
                self._log(f"Download progress: {i}/{len(selected)} articles")
                self._save_checkpoint(checkpoint_path, dates, idx)

        self._log(f"Done: {len(idx)} articles, {len(self.listings)} listings, {len(self.empty_dates)} empty dates, {len(self.errors)} errors")

        meta = {
            "config": {**asdict(self.cfg), "end_year": self.cfg.resolved_end_year()},
            "dates_sampled": len(dates),
            "articles_selected": len(idx),
            "empty_dates": self.empty_dates,
            "errors": self.errors,
            "unstable_days": self.unstable_days,
            "items": idx,
            "listings": self.listings,
        }
        (out_dir / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "unstable_days.json").write_text(
            json.dumps({"unstable_days": self.unstable_days}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Clean up checkpoint on success
        if checkpoint_path.exists():
            checkpoint_path.unlink()
        return meta

    def _save_checkpoint(self, path: Path, dates: list[date], idx: list[dict[str, Any]]) -> None:
        cp = {
            "dates_sampled": len(dates),
            "items": idx,
            "listings": self.listings,
            "capture_sequence": self._capture_seq,
            "errors": self.errors,
            "empty_dates": self.empty_dates,
            "unstable_days": self.unstable_days,
        }
        path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")

    def _random_dates(self) -> list[date]:
        end_year = self.cfg.resolved_end_year()
        start = date(self.cfg.start_year, 1, 1)
        end = date(end_year, 12, 31)
        days = (end - start).days
        picks: set[date] = set()
        while len(picks) < self.cfg.sample_dates and len(picks) < days + 1:
            picks.add(start + timedelta(days=self.rng.randint(0, days)))
        return sorted(picks)

    def _discover_articles_by_date(
        self, d: date
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
        base_url = f"https://www.in.gov.br/leiturajornal?data={d.strftime('%d-%m-%Y')}"
        seen: set[str] = set()
        discovered: list[dict[str, Any]] = []
        listing_captures: list[dict[str, Any]] = []

        for secao in self._SECTIONS:
            list_url = base_url if secao == "do1" else f"{base_url}&secao={secao}"
            html, partial_final = self._get_listing_html_with_completeness_guard(d, secao, list_url)
            if partial_final:
                return [], {
                    "date": d.isoformat(),
                    "reason": "embedded_partial",
                    "section": secao,
                    "url": list_url,
                }, []
            if html is None:
                self.errors.append({"phase": "listing", "url": list_url, "date": d.isoformat(), "section": secao})
                continue

            self._assert_no_listing_pagination(list_url, html)

            # SPA client pagination — dataset already complete.
            links, has_embedded_dataset = self._extract_article_links_from_embedded_json(html)
            if has_embedded_dataset:
                self._log(f"discovery_mode=embedded_full date={d.isoformat()} section={secao} links={len(links)}")
            if not links:
                # Compatibility fallback for any legacy pages that expose direct anchors.
                links = self._extract_article_links(list_url, html)

            # Preserve listing metadata for freeze layer
            listing_sha256 = hashlib.sha256(html.encode("utf-8")).hexdigest()
            listing_captures.append({
                "date": d.isoformat(),
                "section": secao,
                "listing_url": list_url,
                "listing_html": html,
                "sha256": listing_sha256,
                "article_count": len(links),
            })

            for article_url in links:
                if article_url in seen:
                    continue
                seen.add(article_url)
                discovered.append(
                    {
                        "date": d.isoformat(),
                        "listing_url": list_url,
                        "article_url": article_url,
                    }
                )
        return discovered, None, listing_captures

    def _get_listing_html_with_completeness_guard(self, d: date, secao: str, list_url: str) -> tuple[str | None, bool]:
        for attempt in range(1, self.cfg.max_partial_retries + 1):
            html = self._get(list_url)
            if html is None:
                return None, False
            links, has_embedded_dataset = self._extract_article_links_from_embedded_json(html)
            needs_guard = secao in self._COMPLETENESS_GUARD_SECTIONS
            if has_embedded_dataset and needs_guard and len(links) < self.cfg.min_embedded_links:
                partial_event = {
                    "phase": "listing_partial",
                    "date": d.isoformat(),
                    "section": secao,
                    "url": list_url,
                    "links": len(links),
                    "threshold": self.cfg.min_embedded_links,
                    "attempt": attempt,
                    "final": attempt == self.cfg.max_partial_retries,
                }
                self._log(
                    "discovery_mode=embedded_partial "
                    f"date={d.isoformat()} section={secao} links={len(links)} "
                    f"threshold={self.cfg.min_embedded_links} attempt={attempt}/{self.cfg.max_partial_retries}"
                )
                self.errors.append(partial_event)
                if attempt < self.cfg.max_partial_retries:
                    time.sleep(self.cfg.delay_sec * (2 ** (attempt - 1)))
                    continue
                return None, True
            return html, False
        return None, False

    def _extract_article_links_from_embedded_json(self, html: str) -> tuple[list[str], bool]:
        links: list[str] = []
        has_embedded_dataset = False
        for script_id in self._PARAMS_SCRIPT_IDS:
            pattern = (
                rf'<script\s+id="{re.escape(script_id)}"\s+type="application/json">\s*(\{{.*?\}})\s*</script>'
            )
            match = re.search(pattern, html, flags=re.S)
            if not match:
                continue
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            has_embedded_dataset = True
            for item in payload.get("jsonArray") or []:
                if not isinstance(item, dict):
                    continue
                url_title = str(item.get("urlTitle", "")).strip()
                if not url_title:
                    continue
                url_title = url_title.lstrip("/")
                links.append(f"https://www.in.gov.br/web/dou/-/{url_title}")
        return list(dict.fromkeys(links)), has_embedded_dataset

    def _assert_no_listing_pagination(self, list_url: str, html: str) -> None:
        parsed = urlparse(list_url)
        if not parsed.path.endswith("/leiturajornal"):
            return
        if not re.search(r'<script\s+id="params"\s+type="application/json">', html, flags=re.S):
            return
        query = {k.lower() for k in parse_qs(parsed.query, keep_blank_values=True).keys()}
        for key in self._PAGINATION_QUERY_KEYS:
            if key.lower() in query:
                raise RuntimeError(self._PAGINATION_GUARD_MSG)

    def _extract_article_links(self, base_url: str, html: str) -> list[str]:
        p = _LinkParser()
        p.feed(html)
        out = []
        for href in p.links:
            if "/web/dou/-/" not in href:
                continue
            full = urljoin(base_url, href)
            if not (full.startswith("https://www.in.gov.br") or full.startswith("https://portal.in.gov.br")):
                continue
            out.append(full)
        return list(dict.fromkeys(out))

    def _get(self, url: str) -> str | None:
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                if self._request_count > 0:
                    time.sleep(self.cfg.delay_sec)
                self._request_count += 1
                req = Request(
                    url=url,
                    headers={
                        "User-Agent": self.rot.next(),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                    },
                    method="GET",
                )
                with urlopen(req, timeout=self.cfg.timeout_sec) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                self._log(f"  WARN: attempt {attempt}/{self.cfg.max_retries} failed for {url}: {exc}")
                if attempt < self.cfg.max_retries:
                    time.sleep(self.cfg.delay_sec * attempt)
        return None

    def _log(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)
