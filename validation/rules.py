from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml


class RulesError(ValueError):
    pass


@dataclass(slots=True)
class LoadedRules:
    source_id: str
    extract: dict[str, Any]
    heuristics: dict[str, Any]
    required_fields: dict[str, dict[str, bool]]


def load_rules(path: str | Path, source_id: str = "dou") -> LoadedRules:
    p = Path(path)
    if not p.exists():
        raise RulesError(f"rules file not found: {p}")

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    if "sources" in data:
        src = (data.get("sources") or {}).get(source_id)
        if not src:
            raise RulesError(f"source '{source_id}' not found in rules file")
        extract = src.get("extract") or {}
        heur = src.get("heuristics") or {}
        model = src.get("model") or {}
    else:
        extract = data.get("extract") or {}
        heur = data.get("heuristics") or {}
        model = data.get("model") or {}

    if not extract:
        raise RulesError("extract block missing")

    required = _required_fields(model)
    return LoadedRules(source_id=source_id, extract=extract, heuristics=heur, required_fields=required)


def _required_fields(model: dict[str, Any]) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    entities = (model.get("entities") or {}) if isinstance(model, dict) else {}
    for entity_name, entity in entities.items():
        fields = (entity or {}).get("fields") or {}
        out[entity_name] = {}
        for fname, fdef in fields.items():
            out[entity_name][str(fname)] = bool((fdef or {}).get("required", False))
    return out


def parse_contains_selector(selector: str) -> tuple[str, str | None]:
    m = re.search(r":contains\('([^']+)'\)", selector)
    if not m:
        return selector, None
    base = selector[: m.start()] + selector[m.end() :]
    return base.strip() or "*", m.group(1)


def parse_attr_selector(selector: str) -> tuple[str, str | None]:
    m = re.search(r"::attr\(([^)]+)\)$", selector)
    if not m:
        return selector, None
    return selector[: m.start()].strip(), m.group(1).strip()
