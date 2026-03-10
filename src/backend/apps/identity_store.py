from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import hashlib
import secrets
from typing import Any

from fastapi import HTTPException
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
    email_verified: bool = False
    password_changed_at: float | None = None  # unix timestamp; session invalid if session_iat < this


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
                user_id,
                token_id,
                label,
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
                label,
                user_id,
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
                COALESCE(u.email_verified, false) AS email_verified,
                EXTRACT(EPOCH FROM u.password_changed_at)::double precision AS password_changed_at,
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
            GROUP BY u.id, u.display_name, u.email, u.status, u.is_service_account, u.email_verified, u.password_changed_at, t.token_id, t.token_label, t.status
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
            email_verified=bool(d.get("email_verified", False)),
            password_changed_at=float(d["password_changed_at"]) if d.get("password_changed_at") is not None else None,
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
            user_id,
            token_id,
            token_label.strip(),
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


async def upsert_user(
    *, user_id: str | None, display_name: str, email: str | None, status: str, is_service_account: bool
) -> dict[str, Any]:
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
                display_name,
                email,
                status,
                is_service_account,
                user_id,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO auth."user" (display_name, email, status, is_service_account)
                VALUES ($1, $2, $3, $4)
                RETURNING id::text AS id, display_name, email, status, is_service_account, created_at, updated_at, last_login_at
                """,
                display_name,
                email,
                status,
                is_service_account,
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
                user_id,
                clean_roles,
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


# ---------------------------------------------------------------------------
# v1.1: Email + password authentication helpers
# ---------------------------------------------------------------------------


async def create_password_user(email: str, password_hash: str, display_name: str) -> dict:
    """Insert a new password-authenticated user and assign the 'user' role."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO auth."user" (display_name, email, password_hash, login_method, email_verified, status, is_service_account)
            VALUES ($1, $2, $3, 'password', false, 'active', false)
            RETURNING id::text AS id, display_name, email
            """,
            display_name,
            email,
            password_hash,
        )
        user_id = row["id"]
        await conn.execute(
            """
            INSERT INTO auth.user_role (user_id, role_id)
            SELECT $1::uuid, r.id
            FROM auth.role r
            WHERE r.code = 'user'
            ON CONFLICT DO NOTHING
            """,
            user_id,
        )
        return dict(row)


async def find_user_by_email(email: str) -> dict | None:
    """Look up an active user by email (case-insensitive)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id::text AS id, display_name, email, password_hash, status, login_method,
                   COALESCE(email_verified, false) AS email_verified
            FROM auth."user"
            WHERE LOWER(email) = LOWER($1)
              AND status = 'active'
            """,
            email,
        )
        return dict(row) if row else None


async def log_login_attempt(email: str, ip: str, success: bool) -> None:
    """Record a login attempt for brute-force tracking."""
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auth.login_attempt (email, ip_address, success)
            VALUES ($1, $2, $3)
            """,
            email,
            ip,
            success,
        )


async def check_brute_force(email: str, ip: str) -> None:
    """Raise 429 if too many failed login attempts for email or IP in last 15 min."""
    async with acquire() as conn:
        email_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM auth.login_attempt
            WHERE email = $1
              AND NOT success
              AND attempted_at > now() - interval '15 minutes'
            """,
            email,
        )
        if email_count >= 5:
            raise HTTPException(
                status_code=429,
                detail="Muitas tentativas de login. Tente novamente em alguns minutos.",
            )
        ip_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM auth.login_attempt
            WHERE ip_address = $1
              AND NOT success
              AND attempted_at > now() - interval '15 minutes'
            """,
            ip,
        )
        if ip_count >= 20:
            raise HTTPException(
                status_code=429,
                detail="Muitas tentativas de login. Tente novamente em alguns minutos.",
            )


# ---------------------------------------------------------------------------
# A1: Email verification tokens
# ---------------------------------------------------------------------------


def _hash_verification_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def create_verification_token(user_id: str) -> str:
    """Create a new verification token for the user. Returns the raw token (for URL)."""
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_verification_token(raw)
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auth.email_verification (user_id, token_hash)
            VALUES ($1::uuid, $2)
            """,
            user_id,
            token_hash,
        )
    return raw


async def get_verification_token_status(token: str) -> str:
    """Return 'valid' | 'expired' | 'used' | 'invalid' without consuming the token."""
    token_hash = _hash_verification_token(token)
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                used_at IS NOT NULL AS used,
                expires_at > now() AS not_expired
            FROM auth.email_verification
            WHERE token_hash = $1
            """,
            token_hash,
        )
    if not row:
        return "invalid"
    if row["used"]:
        return "used"
    if not row["not_expired"]:
        return "expired"
    return "valid"


async def consume_verification_token(token: str) -> str | None:
    """Validate token, mark user as verified and token as used. Returns user_id or None if invalid/expired/used."""
    token_hash = _hash_verification_token(token)
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id
            FROM auth.email_verification
            WHERE token_hash = $1
              AND used_at IS NULL
              AND expires_at > now()
            """,
            token_hash,
        )
        if not row:
            return None
        user_id = str(row["user_id"])
        await conn.execute(
            """
            UPDATE auth."user"
            SET email_verified = true, updated_at = now()
            WHERE id = $1::uuid
            """,
            user_id,
        )
        await conn.execute(
            """
            UPDATE auth.email_verification
            SET used_at = now()
            WHERE token_hash = $1
            """,
            token_hash,
        )
        return user_id


async def invalidate_previous_tokens(user_id: str) -> None:
    """Remove all verification tokens for the user (e.g. before sending a new one)."""
    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM auth.email_verification WHERE user_id = $1::uuid",
            user_id,
        )


async def resolve_identity_for_user_id(user_id: str) -> IdentityRecord | None:
    """Resolve an IdentityRecord directly from user UUID (for password-authenticated sessions)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                u.id::text AS user_id,
                u.display_name,
                u.email,
                u.status,
                u.is_service_account,
                COALESCE(u.email_verified, false) AS email_verified,
                EXTRACT(EPOCH FROM u.password_changed_at)::double precision AS password_changed_at,
                COALESCE(array_agg(r.code ORDER BY r.code) FILTER (WHERE r.code IS NOT NULL), '{}'::text[]) AS roles
            FROM auth."user" u
            LEFT JOIN auth.user_role ur ON ur.user_id = u.id
            LEFT JOIN auth.role r ON r.id = ur.role_id
            WHERE u.id = $1::uuid
              AND u.status = 'active'
            GROUP BY u.id, u.display_name, u.email, u.status, u.is_service_account, u.email_verified, u.password_changed_at
            """,
            user_id,
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
            token_id=str(d["user_id"]),
            token_label="password",
            token_status="active",
            is_service_account=bool(d["is_service_account"]),
            email_verified=bool(d.get("email_verified", False)),
            password_changed_at=float(d["password_changed_at"]) if d.get("password_changed_at") is not None else None,
        )


# ---------------------------------------------------------------------------
# A2: Password reset tokens
# ---------------------------------------------------------------------------


def _hash_password_reset_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def create_password_reset_token(user_id: str, ip_address: str | None = None) -> str:
    """Create a password reset token for the user. Returns the raw token for the email link."""
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_password_reset_token(raw)
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auth.password_reset (user_id, token_hash, ip_address)
            VALUES ($1::uuid, $2, $3)
            """,
            user_id,
            token_hash,
            ip_address,
        )
    return raw


async def consume_password_reset_token(token: str) -> str | None:
    """If token is valid (not expired, not used), mark it used and return user_id. Else return None."""
    token_hash = _hash_password_reset_token(token)
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id
            FROM auth.password_reset
            WHERE token_hash = $1
              AND used_at IS NULL
              AND expires_at > now()
            """,
            token_hash,
        )
        if not row:
            return None
        user_id = str(row["user_id"])
        await conn.execute(
            "UPDATE auth.password_reset SET used_at = now() WHERE token_hash = $1",
            token_hash,
        )
        return user_id


async def invalidate_password_reset_tokens_for_user(user_id: str) -> None:
    """Remove all password reset tokens for the user."""
    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM auth.password_reset WHERE user_id = $1::uuid",
            user_id,
        )


async def update_user_password(user_id: str, new_password_hash: str) -> None:
    """Set user password and password_changed_at (invalidates existing sessions)."""
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE auth."user"
            SET password_hash = $2, password_changed_at = now(), updated_at = now()
            WHERE id = $1::uuid
            """,
            user_id,
            new_password_hash,
        )
