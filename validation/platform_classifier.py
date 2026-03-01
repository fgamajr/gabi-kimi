from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shutil
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PlatformSignals:
    file: str
    response_bytes: int
    has_params_script: bool
    has_web_dou_permalink: bool
    has_article_anchors: bool
    has_iframe_viewer: bool
    has_legacy_frameset: bool
    has_pdf_links: bool
    detected_platform: str


def classify_samples(samples_dir: Path, out_dir: Path, max_examples_per_platform: int = 5) -> dict[str, Any]:
    html_files = sorted(samples_dir.rglob("*.html"))
    out_dir.mkdir(parents=True, exist_ok=True)
    examples_root = out_dir / "platform_examples"
    examples_root.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    dist: dict[str, int] = {}
    by_platform: dict[str, list[Path]] = {}

    for fp in html_files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        sig = _classify_text(fp.relative_to(samples_dir), text)
        rec = {
            "file": sig.file,
            "response_bytes": sig.response_bytes,
            "has_params_script": sig.has_params_script,
            "has_web_dou_permalink": sig.has_web_dou_permalink,
            "has_iframe_viewer": sig.has_iframe_viewer,
            "has_legacy_frameset": sig.has_legacy_frameset,
            "has_pdf_links": sig.has_pdf_links,
            "detected_platform": sig.detected_platform,
        }
        records.append(rec)
        dist[sig.detected_platform] = dist.get(sig.detected_platform, 0) + 1
        by_platform.setdefault(sig.detected_platform, []).append(fp)

    _write_examples(samples_dir, examples_root, by_platform, max_examples_per_platform)

    payload = {
        "samples_dir": str(samples_dir),
        "total_files": len(records),
        "platform_distribution": dist,
        "records": records,
    }
    (out_dir / "platform_distribution.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "platform_summary.md").write_text(_summary_markdown(payload), encoding="utf-8")
    return payload


def _write_examples(
    samples_dir: Path,
    examples_root: Path,
    by_platform: dict[str, list[Path]],
    max_examples_per_platform: int,
) -> None:
    for platform, files in by_platform.items():
        pdir = examples_root / platform
        pdir.mkdir(parents=True, exist_ok=True)
        for src in files[:max_examples_per_platform]:
            rel = src.relative_to(samples_dir)
            safe_name = str(rel).replace("/", "__")
            dst = pdir / safe_name
            shutil.copyfile(src, dst)


def _summary_markdown(payload: dict[str, Any]) -> str:
    dist: dict[str, int] = payload.get("platform_distribution", {})
    total = int(payload.get("total_files", 0))
    lines = [
        "# Platform Summary",
        "",
        f"- samples_dir: `{payload.get('samples_dir', '')}`",
        f"- total_files: {total}",
        "",
        "| platform | count | ratio |",
        "|---|---:|---:|",
    ]
    for key in sorted(dist.keys()):
        n = int(dist[key])
        ratio = (n / total) if total else 0.0
        lines.append(f"| {key} | {n} | {ratio:.3f} |")
    lines.append("")
    lines.append("Examples are available under `platform_examples/<platform>/`.")
    return "\n".join(lines) + "\n"


def _classify_text(rel_path: Path, text: str) -> PlatformSignals:
    low = text.lower()
    response_bytes = len(text.encode("utf-8", errors="ignore"))

    has_params_script = bool(
        re.search(r'<script[^>]+id=["\']params["\'][^>]+type=["\']application/json["\']', low)
    )
    has_web_dou_permalink = "/web/dou/-/" in low
    has_article_anchors = bool(re.search(r'<a[^>]+href=["\'][^"\']*/-/[^"\']*["\']', low))
    has_iframe_viewer = "<iframe" in low and ("viewer" in low or "visualizador" in low)
    has_legacy_frameset = "<frameset" in low
    has_pdf_links = ".pdf" in low and "<a " in low

    blocked = _looks_blocked(low, response_bytes)
    if blocked:
        detected = "blocked"
    elif has_params_script or has_web_dou_permalink:
        detected = "modern"
    elif has_article_anchors and not has_params_script:
        detected = "transitional"
    elif has_iframe_viewer or has_legacy_frameset or has_pdf_links:
        detected = "legacy"
    else:
        detected = "empty"

    return PlatformSignals(
        file=str(rel_path),
        response_bytes=response_bytes,
        has_params_script=has_params_script,
        has_web_dou_permalink=has_web_dou_permalink,
        has_article_anchors=has_article_anchors,
        has_iframe_viewer=has_iframe_viewer,
        has_legacy_frameset=has_legacy_frameset,
        has_pdf_links=has_pdf_links,
        detected_platform=detected,
    )


def _looks_blocked(low: str, response_bytes: int) -> bool:
    if response_bytes < 300:
        return True
    blockers = (
        "access denied",
        "forbidden",
        "captcha",
        "temporarily unavailable",
        "service unavailable",
        "error 403",
        "error 404",
        "error 500",
    )
    return any(tok in low for tok in blockers)
