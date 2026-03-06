"""Build desired relational plan from source model specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.backend.dbsync.loader import EntitySpec, FieldSpec, SourceModelSpec


TYPE_MAP = {
    "string": "text",
    "text": "text",
    "integer": "integer",
    "bigint": "bigint",
    "decimal": "numeric",
    "boolean": "boolean",
    "date": "date",
    "datetime": "timestamptz",
    "json": "jsonb",
    "uuid": "uuid",
    "enum": "text",
    "object": "jsonb",
    "ref": "uuid",
}


@dataclass(slots=True)
class DesiredColumn:
    name: str
    pg_type: str
    nullable: bool


@dataclass(slots=True)
class DesiredFK:
    name: str
    column: str
    ref_schema: str
    ref_table: str
    ref_column: str


@dataclass(slots=True)
class DesiredIndex:
    name: str
    columns: list[str]
    unique: bool = False
    method: str = "btree"


@dataclass(slots=True)
class DesiredTable:
    schema: str
    name: str
    columns: dict[str, DesiredColumn] = field(default_factory=dict)
    primary_key: str | None = None
    fks: list[DesiredFK] = field(default_factory=list)
    indexes: list[DesiredIndex] = field(default_factory=list)
    uniques: list[DesiredIndex] = field(default_factory=list)


@dataclass(slots=True)
class DesiredSchemaPlan:
    schemas: set[str] = field(default_factory=set)
    tables: dict[tuple[str, str], DesiredTable] = field(default_factory=dict)


class PlanningError(ValueError):
    pass


def build_plan(models: list[SourceModelSpec]) -> DesiredSchemaPlan:
    plan = DesiredSchemaPlan()
    entity_table_map: dict[tuple[str, str], tuple[str, str]] = {}

    for model in models:
        plan.schemas.add(model.namespace)
        for ent in model.entities:
            entity_table_map[(model.namespace, ent.name)] = (model.namespace, ent.table)

    for model in models:
        for ent in model.entities:
            _add_entity_table(plan, ent)
            _add_entity_constraints(plan, ent, entity_table_map)
            _add_array_junction_tables(plan, ent)

    return plan


def _add_entity_table(plan: DesiredSchemaPlan, ent: EntitySpec) -> None:
    key = (ent.namespace, ent.table)
    table = plan.tables.get(key)
    if table is None:
        table = DesiredTable(schema=ent.namespace, name=ent.table)
        plan.tables[key] = table

    for field in ent.fields:
        if field.type == "array":
            # Arrays are represented by junction tables, not inline columns.
            continue
        col = _field_to_column(field)
        table.columns[col.name] = col

    if ent.primary_key_field not in table.columns:
        # auto-add id if omitted
        table.columns[ent.primary_key_field] = DesiredColumn(
            name=ent.primary_key_field,
            pg_type="uuid",
            nullable=False,
        )
    table.primary_key = ent.primary_key_field


def _add_entity_constraints(
    plan: DesiredSchemaPlan,
    ent: EntitySpec,
    entity_table_map: dict[tuple[str, str], tuple[str, str]],
) -> None:
    table = plan.tables[(ent.namespace, ent.table)]

    for field in ent.fields:
        if field.type != "ref" or not field.ref:
            continue
        target_entity = str(field.ref.get("entity", ""))
        target_field = str(field.ref.get("field", "id"))
        target = entity_table_map.get((ent.namespace, target_entity))
        if not target:
            raise PlanningError(
                f"reference target not found for {ent.namespace}.{ent.table}.{field.name}: {target_entity}"
            )
        fk_name = _safe_name(f"fk_{ent.table}_{field.name}_{target[1]}_{target_field}")
        table.fks.append(
            DesiredFK(
                name=fk_name,
                column=field.name,
                ref_schema=target[0],
                ref_table=target[1],
                ref_column=target_field,
            )
        )

    for uc in ent.unique_constraints:
        fields = list(uc.get("fields") or [])
        if not fields:
            continue
        name = str(uc.get("name") or _safe_name(f"uq_{ent.table}_{'_'.join(fields)}"))
        table.uniques.append(DesiredIndex(name=name, columns=fields, unique=True, method="btree"))

    for idx in ent.indexes:
        fields = list(idx.get("fields") or [])
        if not fields:
            continue
        name = str(idx.get("name") or _safe_name(f"idx_{ent.table}_{'_'.join(fields)}"))
        method = str(idx.get("method") or "btree")
        unique = bool(idx.get("unique", False))
        table.indexes.append(DesiredIndex(name=name, columns=fields, unique=unique, method=method))


def _add_array_junction_tables(plan: DesiredSchemaPlan, ent: EntitySpec) -> None:
    for field in ent.fields:
        if field.type != "array" or not field.items:
            continue

        j_schema = ent.namespace
        j_table_name = _safe_name(f"{ent.table}__{field.name}")
        key = (j_schema, j_table_name)
        if key in plan.tables:
            continue

        item_type = str(field.items.get("type", "string"))
        j_table = DesiredTable(schema=j_schema, name=j_table_name)
        parent_fk_col = _safe_name(f"{ent.table}_id")
        j_table.columns[parent_fk_col] = DesiredColumn(name=parent_fk_col, pg_type="uuid", nullable=False)
        j_table.columns["position"] = DesiredColumn(name="position", pg_type="integer", nullable=False)

        if item_type == "object":
            nested = field.items.get("fields") or {}
            for nested_name, nested_def in nested.items():
                ntype = str((nested_def or {}).get("type", "string"))
                pg_type = TYPE_MAP.get(ntype, "text")
                required = bool((nested_def or {}).get("required", False))
                nullable = bool((nested_def or {}).get("nullable", not required))
                j_table.columns[str(nested_name)] = DesiredColumn(
                    name=str(nested_name),
                    pg_type=pg_type,
                    nullable=nullable,
                )
        else:
            pg_type = TYPE_MAP.get(item_type, "text")
            j_table.columns["value"] = DesiredColumn(name="value", pg_type=pg_type, nullable=False)

        j_table.primary_key = parent_fk_col
        j_table.fks.append(
            DesiredFK(
                name=_safe_name(f"fk_{j_table_name}_{parent_fk_col}_{ent.table}_id"),
                column=parent_fk_col,
                ref_schema=ent.namespace,
                ref_table=ent.table,
                ref_column=ent.primary_key_field,
            )
        )
        j_table.indexes.append(
            DesiredIndex(
                name=_safe_name(f"idx_{j_table_name}_{parent_fk_col}_position"),
                columns=[parent_fk_col, "position"],
                unique=False,
            )
        )

        plan.tables[key] = j_table


def _field_to_column(field: FieldSpec) -> DesiredColumn:
    base_type = TYPE_MAP.get(field.type)
    if not base_type:
        raise PlanningError(f"unsupported field type '{field.type}' for field '{field.name}'")

    return DesiredColumn(name=field.name, pg_type=base_type, nullable=field.nullable)


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name.lower())
    return cleaned[:63]
