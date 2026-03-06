"""Diff desired schema plan vs live PostgreSQL catalog state."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.backend.dbsync.introspect import ExistingDatabaseState
from src.backend.dbsync.planner import DesiredSchemaPlan


@dataclass(slots=True)
class Operation:
    kind: str
    summary: str
    sql: str | None = None


@dataclass(slots=True)
class DiffResult:
    operations: list[Operation] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.manual_actions


def diff_schema(desired: DesiredSchemaPlan, existing: ExistingDatabaseState) -> DiffResult:
    out = DiffResult()

    for schema in sorted(desired.schemas):
        if schema not in existing.schemas:
            out.operations.append(
                Operation(
                    kind='create_schema',
                    summary=f"+ create schema {schema}",
                    sql=f'CREATE SCHEMA IF NOT EXISTS "{schema}";',
                )
            )

    for key in sorted(desired.tables.keys()):
        dt = desired.tables[key]
        et = existing.tables.get(key)

        if et is None:
            out.operations.extend(_ops_create_table(dt))
            continue

        out.operations.extend(_ops_add_missing_columns(dt, et))
        out.operations.extend(_ops_add_constraints_indexes(dt, et))
        out.manual_actions.extend(_detect_dangerous_changes(dt, et))

    for ekey, et in existing.tables.items():
        if ekey not in desired.tables:
            out.manual_actions.append(
                f"MANUAL ACTION REQUIRED: table present in DB but absent in model: {et.schema}.{et.name}"
            )

    return out


def _ops_create_table(dt) -> list[Operation]:
    ops: list[Operation] = []
    col_defs = []
    for col_name in sorted(dt.columns.keys()):
        col = dt.columns[col_name]
        nullable = '' if col.nullable else ' NOT NULL'
        col_defs.append(f'"{col.name}" {col.pg_type}{nullable}')

    if dt.primary_key:
        col_defs.append(f'PRIMARY KEY ("{dt.primary_key}")')

    ddl = f'CREATE TABLE "{dt.schema}"."{dt.name}" (\n  ' + ',\n  '.join(col_defs) + '\n);'
    ops.append(Operation(kind='create_table', summary=f"+ create table {dt.schema}.{dt.name}", sql=ddl))

    for fk in dt.fks:
        ops.append(
            Operation(
                kind='add_fk',
                summary=f"+ add foreign key {fk.name} on {dt.schema}.{dt.name}",
                sql=(
                    f'ALTER TABLE "{dt.schema}"."{dt.name}" '
                    f'ADD CONSTRAINT "{fk.name}" FOREIGN KEY ("{fk.column}") '
                    f'REFERENCES "{fk.ref_schema}"."{fk.ref_table}" ("{fk.ref_column}");'
                ),
            )
        )

    for uq in dt.uniques:
        ops.append(
            Operation(
                kind='add_unique',
                summary=f"+ add unique {uq.name} on {dt.schema}.{dt.name}",
                sql=(
                    f'ALTER TABLE "{dt.schema}"."{dt.name}" '
                    f'ADD CONSTRAINT "{uq.name}" UNIQUE ({_cols(uq.columns)});'
                ),
            )
        )

    for idx in dt.indexes:
        unique = 'UNIQUE ' if idx.unique else ''
        method = idx.method or 'btree'
        ops.append(
            Operation(
                kind='create_index',
                summary=f"+ create index {idx.name} on {dt.schema}.{dt.name}",
                sql=(
                    f'CREATE {unique}INDEX "{idx.name}" ON "{dt.schema}"."{dt.name}" '
                    f'USING {method} ({_cols(idx.columns)});'
                ),
            )
        )

    return ops


def _ops_add_missing_columns(dt, et) -> list[Operation]:
    ops: list[Operation] = []
    for col_name, col in sorted(dt.columns.items()):
        if col_name in et.columns:
            continue
        nullable = '' if col.nullable else ' NOT NULL'
        ops.append(
            Operation(
                kind='add_column',
                summary=f"+ add column {dt.schema}.{dt.name}.{col_name} {col.pg_type}",
                sql=(
                    f'ALTER TABLE "{dt.schema}"."{dt.name}" '
                    f'ADD COLUMN "{col_name}" {col.pg_type}{nullable};'
                ),
            )
        )
    return ops


def _ops_add_constraints_indexes(dt, et) -> list[Operation]:
    ops: list[Operation] = []

    if dt.primary_key and not et.primary_key:
        ops.append(
            Operation(
                kind='add_pk',
                summary=f"+ add primary key on {dt.schema}.{dt.name}({dt.primary_key})",
                sql=(
                    f'ALTER TABLE "{dt.schema}"."{dt.name}" '
                    f'ADD PRIMARY KEY ("{dt.primary_key}");'
                ),
            )
        )

    existing_fk_names = set(et.fks.keys())
    for fk in dt.fks:
        if fk.name in existing_fk_names:
            continue
        ops.append(
            Operation(
                kind='add_fk',
                summary=f"+ add foreign key {fk.name} on {dt.schema}.{dt.name}",
                sql=(
                    f'ALTER TABLE "{dt.schema}"."{dt.name}" '
                    f'ADD CONSTRAINT "{fk.name}" FOREIGN KEY ("{fk.column}") '
                    f'REFERENCES "{fk.ref_schema}"."{fk.ref_table}" ("{fk.ref_column}");'
                ),
            )
        )

    existing_unique_names = set(et.uniques.keys())
    for uq in dt.uniques:
        if uq.name in existing_unique_names:
            continue
        ops.append(
            Operation(
                kind='add_unique',
                summary=f"+ add unique {uq.name} on {dt.schema}.{dt.name}",
                sql=(
                    f'ALTER TABLE "{dt.schema}"."{dt.name}" '
                    f'ADD CONSTRAINT "{uq.name}" UNIQUE ({_cols(uq.columns)});'
                ),
            )
        )

    existing_index_names = set(et.indexes.keys()) | set(et.uniques.keys())
    for idx in dt.indexes:
        if idx.name in existing_index_names:
            continue
        unique = 'UNIQUE ' if idx.unique else ''
        method = idx.method or 'btree'
        ops.append(
            Operation(
                kind='create_index',
                summary=f"+ create index {idx.name} on {dt.schema}.{dt.name}",
                sql=(
                    f'CREATE {unique}INDEX "{idx.name}" ON "{dt.schema}"."{dt.name}" '
                    f'USING {method} ({_cols(idx.columns)});'
                ),
            )
        )

    return ops


def _detect_dangerous_changes(dt, et) -> list[str]:
    issues: list[str] = []

    for e_col_name, e_col in et.columns.items():
        d_col = dt.columns.get(e_col_name)
        if d_col is None:
            issues.append(
                f"MANUAL ACTION REQUIRED: drop column detected {dt.schema}.{dt.name}.{e_col_name}"
            )
            continue

        if _normalize(d_col.pg_type) != _normalize(e_col.pg_type):
            issues.append(
                "MANUAL ACTION REQUIRED: type change detected "
                f"{dt.schema}.{dt.name}.{e_col_name} {_normalize(e_col.pg_type)} -> {_normalize(d_col.pg_type)}"
            )

        if e_col.nullable and not d_col.nullable:
            issues.append(
                "MANUAL ACTION REQUIRED: nullable -> required change detected "
                f"{dt.schema}.{dt.name}.{e_col_name}"
            )

    return issues


def _cols(cols: list[str]) -> str:
    return ', '.join(f'"{c}"' for c in cols)


def _normalize(tp: str) -> str:
    aliases = {
        'varchar': 'text',
        'character varying': 'text',
        'int4': 'integer',
        'int8': 'bigint',
    }
    return aliases.get(tp, tp)
