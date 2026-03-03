"""Load and validate crawl DSL YAML."""

from __future__ import annotations

from typing import Any

import yaml

from crawler.dsl_schema import CrawlSpec, crawl_spec_from_dict


class DslLoadError(ValueError):
    pass


def load_crawl_spec(path: str) -> CrawlSpec:
    with open(path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    spec = crawl_spec_from_dict(data)
    _validate(spec)
    return spec


def _validate(spec: CrawlSpec) -> None:
    errors: list[str] = []

    if not spec.entry_url:
        errors.append("crawl.entry is required")
    if spec.runtime.mode != "mock":
        errors.append("crawl.runtime.mode must be 'mock' for this engine")
    if not spec.steps:
        errors.append("crawl.steps must be non-empty")

    for idx, step in enumerate(spec.steps):
        if step.kind == "wait" and (not step.wait or not step.wait.selector):
            errors.append(f"steps[{idx}].wait.selector is required")
        if step.kind == "extract":
            if not step.extract or not step.extract.name or not step.extract.selector:
                errors.append(f"steps[{idx}].extract requires name and selector")
        if step.kind == "follow" and (not step.follow or not step.follow.from_name):
            errors.append(f"steps[{idx}].follow.from is required")

    if spec.termination.max_pages < 1:
        errors.append("crawl.termination.max_pages must be >= 1")

    if errors:
        raise DslLoadError("; ".join(errors))
