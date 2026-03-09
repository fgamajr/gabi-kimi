from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import hashlib
import secrets
from typing import Any

from src.backend.apps.db_pool import acquire


ROOT_DIR = Path(__file__).resolve().parents[3]
AUTH_SCHEMA_SQL = ROOT_DIR / "src" / "backend" / "dbsync" / "auth_schema.sql"


def _parse_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    normalized = raw.replace("\n", ",").replace(";", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


@dataclass(frozen=True)
class IdentityRecord:
    user_id: str
    display_name: str
    email: str | None
    status: str
    roles: tuple[str, ...]
    token_id: str
    token_label: str
    token_status: str
    is_service_account: bool


def token_id_for_secret(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


async def ensure_identity_schema() -> None:
    sql = AUTH_SCHEMA_SQL.read_text(encoding="utf-8")
    async with acquire() as conn:
        for statement in [part.strip() for part in sql.split(";") if part.strip()]:
            await conn.execute(statement)


async def sync_env_tokens(token_rows: list[dict[str, str]]) -> None:
    admin_labels = {value.lower() for value in _parse_csv_env("GABI_ADMIN_TOKEN_LABELS")}

    async with acquire() as conn:
        for row in token_rows:
            label = row["label"].strip()
            token_id = row["token_id"].strip()
            if not label or not token_id:
                continue
            existing = await conn.fetchrow(
                "SELECT user_id FROM auth.api_token WHERE token_id = $1",
                token_id,
            )
            if existing:
                user_id = existing["user_id"]
            else:
                existing_user = await conn.fetchrow(
                    """
                    SELECT id
                    FROM auth."user"
                    WHERE is_service_account = true
                      AND display_name = $1
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    label,
                )
                if existing_user:
                    user_id = existing_user["id"]
                else:
                    new_user = await conn.fetchrow(
                        """
                        INSERT INTO auth."user" (display_name, status, is_service_account)
                        VALUES ($1, 'active', true)
                        RETURNING id
                        """,
                        label,
                    )
                    user_id = new_user["id"]

            upserted = await conn.fetchrow(
                """
                INSERT INTO auth.api_token (user_id, token_id, token_label, status)
                VALUES ($1, $2, $3, 'active')
                ON CONFLICT (token_id) DO UPDATE
                SET user_id = EXCLUDED.user_id,
                    token_label = EXCLUDED.token_label,
                    status = 'active',
                    updated_at = now()
                RETURNING user_id
                """,
                user_id, token_id, label,
            )
            user_id = upserted["user_id"]

            await conn.execute(
                """
                UPDATE auth."user"
                SET display_name = $1,
                    is_service_account = true,
                    status = 'active',
                    updated_at = now()
                WHERE id = $2
                """,
                label, user_id,
            )

            await conn.execute(
                """
                INSERT INTO auth.user_role (user_id, role_id)
                SELECT $1, r.id
                FROM auth.role r
                WHERE r.code = 'user'
                ON CONFLICT DO NOTHING
                """,
                user_id,
            )

            if label.lower() in admin_labels or label.lower().startswith("admin"):
                await conn.execute(
                    """
                    INSERT INTO auth.user_role (user_id, role_id)
                    SELECT $1, r.id
                    FROM auth.role r
                    WHERE r.code = 'admin'
                    ON CONFLICT DO NOTHING
                    """,
                    user_id,
                )


async def resolve_identity_for_token(token_id: str) -> IdentityRecord | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                u.id::text AS user_id,
                u.display_name,
                u.email,
                u.status,
                u.is_service_account,
                t.token_id,
                t.token_label,
                t.status AS token_status,
                COALESCE(array_agg(r.code ORDER BY r.code) FILTER (WHERE r.code IS NOT NULL), '{}'::text[]) AS roles
            FROM auth.api_token t
            JOIN auth."user" u ON u.id = t.user_id
            LEFT JOIN auth.user_role ur ON ur.user_id = u.id
            LEFT JOIN auth.role r ON r.id = ur.role_id
            WHERE t.token_id = $1
              AND t.status = 'active'
              AND u.status = 'active'
            GROUP BY u.id, u.display_name, u.email, u.status, u.is_service_account, t.token_id, t.token_label, t.status
            """,
            token_id,
        )
        if not row:
            return None
        d = dict(row)
        return IdentityRecord(
            user_id=str(d["user_id"]),
            display_name=str(d["display_name"]),
            email=str(d["email"]) if d.get("email") else None,
            status=str(d["status"]),
            roles=tuple(str(item) for item in (d.get("roles") or []) if item),
            token_id=str(d["token_id"]),
            token_label=str(d["token_label"]),
            token_status=str(d["token_status"]),
            is_service_account=bool(d["is_service_account"]),
        )


async def touch_token_usage(token_id: str) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE auth.api_token
            SET last_used_at = now(),
                updated_at = now()
            WHERE token_id = $1
            """,
            token_id,
        )
        await conn.execute(
            """
            UPDATE auth."user" u
            SET last_login_at = now(),
                updated_at = now()
            FROM auth.api_token t
            WHERE t.user_id = u.id
              AND t.token_id = $1
            """,
            token_id,
        )


async def list_roles() -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text AS id, code, label, description, created_at
            FROM auth.role
            ORDER BY code
            """
        )
        return [dict(row) for row in rows]


async def issue_api_token(*, user_id: str, token_label: str) -> dict[str, Any]:
    raw_token = f"gabi_{secrets.token_urlsafe(24)}"
    token_id = token_id_for_secret(raw_token)
    async with acquire() as conn:
        check = await conn.fetchrow('SELECT 1 FROM auth."user" WHERE id = $1::uuid', user_id)
        if check is None:
            raise ValueError("user-not-found")
        row = await conn.fetchrow(
            """
            INSERT INTO auth.api_token (user_id, token_id, token_label, status)
            VALUES ($1::uuid, $2, $3, 'active')
            RETURNING token_id, token_label, status, created_at, updated_at, last_used_at
            """,
            user_id, token_id, token_label.strip(),
        )
        if not row:
            raise ValueError("token-create-failed")
        payload = dict(row)
        payload["plain_token"] = raw_token
        return payload


async def revoke_api_token(token_id: str) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE auth.api_token
            SET status = 'revoked',
                updated_at = now()
            WHERE token_id = $1
            RETURNING token_id, token_label, status, created_at, updated_at, last_used_at
            """,
            token_id,
        )
        if not row:
            raise ValueError("token-not-found")
        return dict(row)


async def list_users() -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                u.id::text AS id,
                u.display_name,
                u.email,
                u.status,
                u.is_service_account,
                u.created_at,
                u.updated_at,
                u.last_login_at,
                COALESCE(array_agg(DISTINCT r.code) FILTER (WHERE r.code IS NOT NULL), '{}'::text[]) AS roles,
                COALESCE(
                    json_agg(
                        DISTINCT jsonb_build_object(
                            'token_id', t.token_id,
                            'label', t.token_label,
                            'status', t.status,
                            'last_used_at', t.last_used_at
                        )
                    ) FILTER (WHERE t.id IS NOT NULL),
                    '[]'::json
                ) AS tokens
            FROM auth."user" u
            LEFT JOIN auth.user_role ur ON ur.user_id = u.id
            LEFT JOIN auth.role r ON r.id = ur.role_id
            LEFT JOIN auth.api_token t ON t.user_id = u.id
            GROUP BY u.id, u.display_name, u.email, u.status, u.is_service_account, u.created_at, u.updated_at, u.last_login_at
            ORDER BY u.created_at DESC, u.display_name
            """
        )
        return [dict(row) for row in rows]


async def upsert_user(*, user_id: str | None, display_name: str, email: str | None, status: str, is_service_account: bool) -> dict[str, Any]:
    async with acquire() as conn:
        created = False
        if user_id:
            row = await conn.fetchrow(
                """
                UPDATE auth."user"
                SET display_name = $1,
                    email = $2,
                    status = $3,
                    is_service_account = $4,
                    updated_at = now()
                WHERE id = $5::uuid
                RETURNING id::text AS id, display_name, email, status, is_service_account, created_at, updated_at, last_login_at
                """,
                display_name, email, status, is_service_account, user_id,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO auth."user" (display_name, email, status, is_service_account)
                VALUES ($1, $2, $3, $4)
                RETURNING id::text AS id, display_name, email, status, is_service_account, created_at, updated_at, last_login_at
                """,
                display_name, email, status, is_service_account,
            )
            created = True
        if not row:
            raise ValueError("user-not-found")
        d = dict(row)
        if created:
            await conn.execute(
                """
                INSERT INTO auth.user_role (user_id, role_id)
                SELECT $1::uuid, r.id
                FROM auth.role r
                WHERE r.code = 'user'
                ON CONFLICT DO NOTHING
                """,
                d["id"],
            )
        return d


async def replace_user_roles(user_id: str, roles: list[str]) -> dict[str, Any]:
    async with acquire() as conn:
        await conn.execute("DELETE FROM auth.user_role WHERE user_id = $1::uuid", user_id)
        clean_roles = sorted({role.strip().lower() for role in roles if role.strip()})
        if clean_roles:
            await conn.execute(
                """
                INSERT INTO auth.user_role (user_id, role_id)
                SELECT $1::uuid, r.id
                FROM auth.role r
                WHERE r.code = ANY($2::text[])
                ON CONFLICT DO NOTHING
                """,
                user_id, clean_roles,
            )
        row = await conn.fetchrow(
            """
            SELECT
                u.id::text AS id,
                u.display_name,
                COALESCE(array_agg(r.code ORDER BY r.code) FILTER (WHERE r.code IS NOT NULL), '{}'::text[]) AS roles
            FROM auth."user" u
            LEFT JOIN auth.user_role ur ON ur.user_id = u.id
            LEFT JOIN auth.role r ON r.id = ur.role_id
            WHERE u.id = $1::uuid
            GROUP BY u.id, u.display_name
            """,
            user_id,
        )
        if not row:
            raise ValueError("user-not-found")
        return dict(row)
