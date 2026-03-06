"""Execute safe schema sync operations against PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from src.backend.dbsync.differ import Operation


@dataclass(slots=True)
class ApplyResult:
    applied: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


class ApplyError(RuntimeError):
    pass


def apply_operations(dsn: str, operations: list[Operation]) -> ApplyResult:
    result = ApplyResult()
    if not operations:
        return result

    with psycopg.connect(dsn) as conn:
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    for op in operations:
                        if not op.sql:
                            continue
                        try:
                            cur.execute(op.sql)
                            result.applied.append(op.summary)
                        except Exception as ex:
                            result.failed.append(f"{op.summary} :: {ex}")
                            raise
        except Exception as ex:
            raise ApplyError(f"apply failed and rolled back: {ex}") from ex

    return result
