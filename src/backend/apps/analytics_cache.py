from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.backend.apps.db_pool import acquire

_ROOT_DIR = Path(__file__).resolve().parents[3]
ANALYTICS_CACHE_SCHEMA_SQL = _ROOT_DIR / "src" / "backend" / "dbsync" / "analytics_cache_schema.sql"

_ANALYTICS_MATVIEWS = (
    "dou.analytics_overview_cache",
    "dou.analytics_section_monthly_cache",
    "dou.analytics_art_type_totals_cache",
    "dou.analytics_art_type_monthly_cache",
    "dou.analytics_top_organs_cache",
    "dou.analytics_section_totals_cache",
    "dou.analytics_latest_documents_cache",
)


def _stale_threshold_hours() -> int:
    raw = os.getenv("GABI_ANALYTICS_CACHE_STALE_HOURS", "6").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 6


async def ensure_analytics_cache_schema() -> None:
    sql = ANALYTICS_CACHE_SCHEMA_SQL.read_text(encoding="utf-8")
    async with acquire() as conn:
        for statement in [p.strip() for p in sql.split(";") if p.strip()]:
            await conn.execute(statement)


async def _write_refresh_state(
    *,
    status: str,
    source: str,
    last_refreshed_at: datetime | None,
    last_duration_ms: int | None,
    last_error: str | None,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO admin.analytics_cache_state
                (id, last_refreshed_at, last_duration_ms, last_refresh_source, last_status, last_error, updated_at)
            VALUES
                (true, $1, $2, $3, $4, $5, now())
            ON CONFLICT (id) DO UPDATE
            SET last_refreshed_at = EXCLUDED.last_refreshed_at,
                last_duration_ms = EXCLUDED.last_duration_ms,
                last_refresh_source = EXCLUDED.last_refresh_source,
                last_status = EXCLUDED.last_status,
                last_error = EXCLUDED.last_error,
                updated_at = now()
            """,
            last_refreshed_at,
            last_duration_ms,
            source,
            status,
            last_error,
        )


async def refresh_analytics_cache(*, source: str = "manual") -> dict[str, Any]:
    started_monotonic = time.monotonic()
    started_at = datetime.now(timezone.utc)
    try:
        async with acquire() as conn:
            for view_name in _ANALYTICS_MATVIEWS:
                await conn.execute(f"REFRESH MATERIALIZED VIEW {view_name}")
    except Exception as exc:
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        await _write_refresh_state(
            status="failed",
            source=source,
            last_refreshed_at=None,
            last_duration_ms=duration_ms,
            last_error=str(exc),
        )
        raise
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((time.monotonic() - started_monotonic) * 1000)
    await _write_refresh_state(
        status="ok",
        source=source,
        last_refreshed_at=finished_at,
        last_duration_ms=duration_ms,
        last_error=None,
    )
    return {
        "ok": True,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": duration_ms,
        "source": source,
    }


async def get_analytics_cache_status() -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                last_refreshed_at,
                last_duration_ms,
                last_refresh_source,
                last_status,
                last_error,
                updated_at
            FROM admin.analytics_cache_state
            WHERE id = true
            """
        )

    if not row:
        return {
            "last_refreshed_at": None,
            "last_duration_ms": None,
            "last_refresh_source": None,
            "last_status": "unknown",
            "last_error": None,
            "updated_at": None,
            "is_stale": True,
            "stale_after_hours": _stale_threshold_hours(),
        }
    threshold_hours = _stale_threshold_hours()
    last_refreshed_at = row["last_refreshed_at"]
    is_stale = True
    if last_refreshed_at is not None:
        elapsed_seconds = (datetime.now(timezone.utc) - last_refreshed_at).total_seconds()
        is_stale = elapsed_seconds >= threshold_hours * 3600
    return {
        "last_refreshed_at": last_refreshed_at.isoformat() if last_refreshed_at else None,
        "last_duration_ms": int(row["last_duration_ms"]) if row["last_duration_ms"] is not None else None,
        "last_refresh_source": row["last_refresh_source"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "is_stale": is_stale,
        "stale_after_hours": threshold_hours,
    }


async def load_analytics_payload() -> dict[str, Any]:
    async with acquire() as conn:
        overview_row = await conn.fetchrow("SELECT * FROM dou.analytics_overview_cache LIMIT 1")
        overview_row = dict(overview_row) if overview_row else {}

        monthly_rows = list(
            reversed(
                await conn.fetch(
                    """
                    SELECT month, do1, do2, do3, extra, total
                    FROM dou.analytics_section_monthly_cache
                    ORDER BY month DESC
                    LIMIT 18
                    """
                )
            )
        )
        section_monthly = [
            {
                "month": row["month"].isoformat() if row["month"] else None,
                "do1": int(row["do1"] or 0),
                "do2": int(row["do2"] or 0),
                "do3": int(row["do3"] or 0),
                "extra": int(row["extra"] or 0),
                "total": int(row["total"] or 0),
            }
            for row in monthly_rows
        ]

        top_type_rows = await conn.fetch(
            """
            SELECT art_type, cnt
            FROM dou.analytics_art_type_totals_cache
            ORDER BY cnt DESC, art_type ASC
            LIMIT 5
            """
        )
        top_types = [str(row["art_type"]) for row in top_type_rows]

        type_points_by_month: dict[str, dict[str, int]] = {}
        if top_types:
            art_type_monthly_rows = await conn.fetch(
                """
                SELECT month, art_type, cnt
                FROM dou.analytics_art_type_monthly_cache
                WHERE art_type = ANY($1::text[])
                ORDER BY month ASC
                """,
                top_types,
            )
            for row in art_type_monthly_rows:
                month_key = row["month"].isoformat() if row["month"] else ""
                bucket = type_points_by_month.setdefault(month_key, {})
                bucket[str(row["art_type"])] = int(row["cnt"] or 0)

        top_types_monthly = {
            "months": [item["month"] for item in section_monthly],
            "series": [
                {
                    "key": str(row["art_type"]),
                    "label": str(row["art_type"]).replace("-", " ").title(),
                    "total": int(row["cnt"] or 0),
                    "points": [
                        type_points_by_month.get(str(item["month"]), {}).get(str(row["art_type"]), 0)
                        for item in section_monthly
                    ],
                }
                for row in top_type_rows
            ],
        }

        top_organ_rows = await conn.fetch(
            """
            SELECT issuing_organ, cnt
            FROM dou.analytics_top_organs_cache
            ORDER BY cnt DESC, issuing_organ ASC
            LIMIT 8
            """
        )
        top_organs = [
            {"organ": str(row["issuing_organ"]), "count": int(row["cnt"] or 0)}
            for row in top_organ_rows
        ]

        section_total_rows = await conn.fetch(
            """
            SELECT section, cnt
            FROM dou.analytics_section_totals_cache
            ORDER BY cnt DESC, section ASC
            """
        )
        section_totals = [
            {"section": str(row["section"] or ""), "count": int(row["cnt"] or 0)}
            for row in section_total_rows
        ]

        latest_rows = await conn.fetch(
            """
            SELECT id, identifica, ementa, issuing_organ, art_type, publication_date, section, page_number
            FROM dou.analytics_latest_documents_cache
            ORDER BY publication_date DESC, page_sort DESC, id DESC
            LIMIT 4
            """
        )
        latest_documents = [
            {
                "id": str(row["id"]),
                "title": str(row["identifica"] or row["ementa"] or "Sem título"),
                "snippet": str(row["ementa"] or "").strip() or None,
                "issuing_organ": str(row["issuing_organ"] or "").strip() or None,
                "art_type": str(row["art_type"] or "").strip() or None,
                "pub_date": row["publication_date"].isoformat() if row["publication_date"] else None,
                "section": str(row["section"] or ""),
                "page": str(row["page_number"]) if row["page_number"] is not None else None,
            }
            for row in latest_rows
        ]

    return {
        "overview": {
            "total_documents": int(overview_row.get("total_documents") or 0),
            "total_organs": int(overview_row.get("total_organs") or 0),
            "total_types": int(overview_row.get("total_types") or 0),
            "date_min": overview_row.get("date_min").isoformat() if overview_row.get("date_min") else None,
            "date_max": overview_row.get("date_max").isoformat() if overview_row.get("date_max") else None,
            "tracked_months": len(section_monthly),
        },
        "section_totals": section_totals,
        "section_monthly": section_monthly,
        "top_types_monthly": top_types_monthly,
        "top_organs": top_organs,
        "latest_documents": latest_documents,
    }
