"""Load and normalize source model DSL blocks from config/sources/sources_v3.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ModelLoadError(ValueError):
    pass


@dataclass(slots=True)
class FieldSpec:
    name: str
    type: str
    required: bool = False
    nullable: bool = True
    ref: dict[str, Any] | None = None
    items: dict[str, Any] | None = None
    fields: dict[str, Any] | None = None


@dataclass(slots=True)
class EntitySpec:
    source_id: str
    namespace: str
    name: str
    table: str
    fields: list[FieldSpec] = field(default_factory=list)
    unique_constraints: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)
    primary_key_field: str = "id"


@dataclass(slots=True)
class SourceModelSpec:
    source_id: str
    namespace: str
    entities: list[EntitySpec]


def load_source_models(path: str | Path) -> list[SourceModelSpec]:
    p = Path(path)
    if not p.exists():
        raise ModelLoadError(f"sources file not found: {p}")

    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    sources = data.get("sources")
    if not isinstance(sources, dict):
        raise ModelLoadError("expected top-level 'sources' mapping in sources file")

    models: list[SourceModelSpec] = []
    for source_id, source_def in sources.items():
        model = (source_def or {}).get("model")
        if not model:
            continue

        namespace = str(model.get("namespace") or source_id)
        raw_entities = model.get("entities") or {}
        if not isinstance(raw_entities, dict) or not raw_entities:
            raise ModelLoadError(f"source '{source_id}' has model but no entities")

        entities: list[EntitySpec] = []
        for entity_name, ent in raw_entities.items():
            ent = ent or {}
            table = str(ent.get("table") or entity_name)

            identity = ent.get("identity") or {}
            pk = (identity.get("primary_key") or {}).get("field") or "id"

            raw_fields = ent.get("fields") or {}
            fields: list[FieldSpec] = []
            for fname, fdef in raw_fields.items():
                fdef = fdef or {}
                required = bool(fdef.get("required", False))
                nullable = bool(fdef.get("nullable", not required))
                fields.append(
                    FieldSpec(
                        name=str(fname),
                        type=str(fdef.get("type", "string")),
                        required=required,
                        nullable=nullable,
                        ref=fdef.get("ref"),
                        items=fdef.get("items"),
                        fields=fdef.get("fields"),
                    )
                )

            constraints = ent.get("constraints") or {}
            unique_constraints = list(constraints.get("unique") or [])
            indexes = list(ent.get("indexes") or [])

            entities.append(
                EntitySpec(
                    source_id=str(source_id),
                    namespace=namespace,
                    name=str(entity_name),
                    table=table,
                    fields=fields,
                    unique_constraints=unique_constraints,
                    indexes=indexes,
                    primary_key_field=str(pk),
                )
            )

        models.append(SourceModelSpec(source_id=str(source_id), namespace=namespace, entities=entities))

    if not models:
        raise ModelLoadError("no source models found (expected sources.<id>.model blocks)")

    return models
