"""PostgreSQL catalog introspection for schema sync."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg


@dataclass(slots=True)
class ExistingColumn:
    name: str
    pg_type: str
    nullable: bool


@dataclass(slots=True)
class ExistingFK:
    name: str
    column: str
    ref_schema: str
    ref_table: str
    ref_column: str


@dataclass(slots=True)
class ExistingIndex:
    name: str
    columns: list[str]
    unique: bool


@dataclass(slots=True)
class ExistingTable:
    schema: str
    name: str
    columns: dict[str, ExistingColumn] = field(default_factory=dict)
    primary_key: str | None = None
    fks: dict[str, ExistingFK] = field(default_factory=dict)
    indexes: dict[str, ExistingIndex] = field(default_factory=dict)
    uniques: dict[str, ExistingIndex] = field(default_factory=dict)


@dataclass(slots=True)
class ExistingDatabaseState:
    schemas: set[str] = field(default_factory=set)
    tables: dict[tuple[str, str], ExistingTable] = field(default_factory=dict)


def introspect_database(dsn: str) -> ExistingDatabaseState:
    state = ExistingDatabaseState()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT nspname
                FROM pg_namespace
                WHERE nspname NOT IN ('pg_catalog', 'information_schema')
                  AND nspname NOT LIKE 'pg_toast%'
                  AND nspname NOT LIKE 'pg_temp_%'
                """
            )
            for (schema,) in cur.fetchall():
                state.schemas.add(schema)

            cur.execute(
                """
                SELECT n.nspname, c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r'
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
                  AND n.nspname NOT LIKE 'pg_temp_%'
                """
            )
            for schema, table in cur.fetchall():
                state.tables[(schema, table)] = ExistingTable(schema=schema, name=table)

            cur.execute(
                """
                SELECT table_schema, table_name, column_name, udt_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                """
            )
            for schema, table, col, udt_name, is_nullable in cur.fetchall():
                t = state.tables.get((schema, table))
                if not t:
                    continue
                t.columns[col] = ExistingColumn(
                    name=col,
                    pg_type=_normalize_pg_type(str(udt_name)),
                    nullable=(is_nullable == 'YES'),
                )

            cur.execute(
                """
                SELECT
                    n.nspname,
                    c.relname,
                    con.conname,
                    con.contype,
                    pg_get_constraintdef(con.oid)
                FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                """
            )
            for schema, table, conname, contype, definition in cur.fetchall():
                t = state.tables.get((schema, table))
                if not t:
                    continue

                if contype == 'p':
                    pk_col = _extract_first_column_from_def(definition)
                    t.primary_key = pk_col
                elif contype == 'u':
                    cols = _extract_columns_from_def(definition)
                    t.uniques[conname] = ExistingIndex(name=conname, columns=cols, unique=True)
                elif contype == 'f':
                    lcol = _extract_first_column_from_def(definition)
                    ref_schema, ref_table, ref_col = _extract_fk_target(definition)
                    t.fks[conname] = ExistingFK(
                        name=conname,
                        column=lcol,
                        ref_schema=ref_schema,
                        ref_table=ref_table,
                        ref_column=ref_col,
                    )

            cur.execute(
                """
                SELECT
                    schemaname,
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                """
            )
            for schema, table, idx_name, idx_def in cur.fetchall():
                t = state.tables.get((schema, table))
                if not t:
                    continue
                cols = _extract_columns_from_indexdef(idx_def)
                unique = ' UNIQUE INDEX ' in idx_def
                info = ExistingIndex(name=idx_name, columns=cols, unique=unique)
                if unique:
                    t.uniques[idx_name] = info
                else:
                    t.indexes[idx_name] = info

    return state


def _normalize_pg_type(udt_name: str) -> str:
    mapping = {
        'int4': 'integer',
        'int8': 'bigint',
        'text': 'text',
        'varchar': 'text',
        'bool': 'boolean',
        'date': 'date',
        'timestamptz': 'timestamptz',
        'timestamp': 'timestamp',
        'jsonb': 'jsonb',
        'uuid': 'uuid',
        'numeric': 'numeric',
    }
    return mapping.get(udt_name, udt_name)


def _extract_first_column_from_def(definition: str) -> str:
    cols = _extract_columns_from_def(definition)
    return cols[0] if cols else ''


def _extract_columns_from_def(definition: str) -> list[str]:
    start = definition.find('(')
    end = definition.find(')')
    if start < 0 or end < 0 or end <= start:
        return []
    body = definition[start + 1 : end]
    return [c.strip().strip('"') for c in body.split(',') if c.strip()]


def _extract_fk_target(definition: str) -> tuple[str, str, str]:
    # Example: FOREIGN KEY (a) REFERENCES schema.table(id)
    ref_token = 'REFERENCES '
    i = definition.find(ref_token)
    if i < 0:
        return ('', '', '')
    tail = definition[i + len(ref_token) :]
    left = tail.split('(')[0].strip()
    if '.' in left:
        schema, table = left.split('.', 1)
    else:
        schema, table = 'public', left
    col = _extract_first_column_from_def(tail)
    return (schema.strip('"'), table.strip('"'), col)


def _extract_columns_from_indexdef(indexdef: str) -> list[str]:
    start = indexdef.rfind('(')
    end = indexdef.rfind(')')
    if start < 0 or end < 0 or end <= start:
        return []
    body = indexdef[start + 1 : end]
    out: list[str] = []
    for raw in body.split(','):
        token = raw.strip().strip('"')
        if not token:
            continue
        token = token.split()[0]
        out.append(token)
    return out
