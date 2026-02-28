"""Validation for YAML crawler DSL plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crawler.dsl_schema import CrawlPlan


SUPPORTED_ACTIONS = {
    "load",
    "wait_for",
    "extract_links",
    "click",
    "scroll",
    "sleep",
}
SUPPORTED_PAGINATION = {
    "click_next",
    "numbered",
    "scroll",
    "discover_links",
}
SUPPORTED_RUNTIME_MODES = {"http", "headless_browser"}
SUPPORTED_TRAVERSAL = {"bfs", "dfs"}


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    errors: list[str]


class DslValidationError(ValueError):
    pass


def validate_plan_dict(data: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []

    if not isinstance(data, dict):
        return ValidationResult(valid=False, errors=["root must be a mapping"])

    for required in ["entry", "navigation", "pagination", "extraction"]:
        if required not in data:
            errors.append(f"missing required section: {required}")

    entry = data.get("entry", {}) or {}
    if not entry.get("template"):
        errors.append("entry.template is required")
    if entry.get("type") != "url":
        errors.append("entry.type must be 'url'")

    nav = data.get("navigation", []) or []
    if not isinstance(nav, list) or not nav:
        errors.append("navigation must be a non-empty list")
    else:
        for i, step in enumerate(nav):
            action = (step or {}).get("action")
            if action not in SUPPORTED_ACTIONS:
                errors.append(f"navigation[{i}].action unsupported: {action}")
            if action in {"wait_for", "extract_links", "click", "scroll"} and not step.get("selector"):
                if action != "scroll":
                    errors.append(f"navigation[{i}].selector required for action={action}")

    pagination = data.get("pagination", {}) or {}
    strategy = pagination.get("strategy")
    if strategy not in SUPPORTED_PAGINATION:
        errors.append(f"pagination.strategy unsupported: {strategy}")

    if strategy in {"click_next", "numbered", "discover_links"} and not pagination.get("selector"):
        errors.append(f"pagination.selector required for strategy={strategy}")

    runtime = data.get("runtime", {}) or {}
    mode = runtime.get("mode", "http")
    if mode not in SUPPORTED_RUNTIME_MODES:
        errors.append(f"runtime.mode unsupported: {mode}")

    traversal = runtime.get("traversal", "bfs")
    if traversal not in SUPPORTED_TRAVERSAL:
        errors.append(f"runtime.traversal unsupported: {traversal}")

    extraction = data.get("extraction", {}) or {}
    links = extraction.get("links", []) or []
    if not isinstance(links, list):
        errors.append("extraction.links must be a list")
    else:
        for i, rule in enumerate(links):
            if not rule.get("name"):
                errors.append(f"extraction.links[{i}].name is required")
            if not rule.get("selector"):
                errors.append(f"extraction.links[{i}].selector is required")

    return ValidationResult(valid=not errors, errors=errors)


def validate_plan_or_raise(plan_dict: dict[str, Any]) -> CrawlPlan:
    result = validate_plan_dict(plan_dict)
    if not result.valid:
        raise DslValidationError("; ".join(result.errors))
    return CrawlPlan.from_dict(plan_dict)
