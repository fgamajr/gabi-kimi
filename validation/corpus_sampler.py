from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import random
from typing import Any
from urllib.parse import urljoin
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
    end_year: int = date.today().year
    sample_dates: int = 200
    max_articles: int = 200
    timeout_sec: int = 25
    seed: int = 42


class CorpusSampler:
    def __init__(self, cfg: SamplerConfig) -> None:
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.rot = create_default_rotator()

    def build(self, out_dir: Path) -> dict[str, Any]:
        out_dir.mkdir(parents=True, exist_ok=True)
        idx: list[dict[str, Any]] = []

        dates = self._random_dates()
        article_pool: list[dict[str, Any]] = []

        for d in dates:
            list_url = f"https://www.in.gov.br/leiturajornal?data={d.strftime('%d-%m-%Y')}"
            html = self._get(list_url)
            links = self._extract_article_links(list_url, html)
            for u in links:
                article_pool.append({"date": d.isoformat(), "listing_url": list_url, "article_url": u})

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

        for item in selected:
            u = item["article_url"]
            d = date.fromisoformat(item["date"])
            html = self._get(u)
            h = hashlib.sha1(u.encode("utf-8")).hexdigest()[:12]
            rel = Path(str(d.year)) / f"{d.month:02d}" / f"{d.day:02d}" / f"{h}.html"
            fp = out_dir / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(html, encoding="utf-8")
            idx.append({**item, "file": str(rel)})

        meta = {
            "config": self.cfg.__dict__,
            "dates_sampled": len(dates),
            "articles_selected": len(idx),
            "items": idx,
        }
        (out_dir / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def _random_dates(self) -> list[date]:
        start = date(self.cfg.start_year, 1, 1)
        end = date(self.cfg.end_year, 12, 31)
        days = (end - start).days
        picks = set()
        while len(picks) < self.cfg.sample_dates and len(picks) < days + 1:
            picks.add(start + timedelta(days=self.rng.randint(0, days)))
        return sorted(picks)

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

    def _get(self, url: str) -> str:
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
