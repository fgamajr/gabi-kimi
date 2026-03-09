from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import Response
from passlib.context import CryptContext

from src.backend.apps.identity_store import (
    ensure_identity_schema,
    issue_api_token,
    list_roles,
    list_users,
    replace_user_roles,
    resolve_identity_for_user_id,
    revoke_api_token,
    resolve_identity_for_token,
    sync_env_tokens,
    token_id_for_secret,
    touch_token_usage,
    upsert_user,
)
from src.backend.apps.middleware.security import (
    RateLimiter,
    RateRule,
    attach_cookie,
    log_security_event,
)


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

# ---------------------------------------------------------------------------
# Password hashing (bcrypt via passlib)
# ---------------------------------------------------------------------------
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# Pre-computed dummy hash for timing equalization on failed email lookups.
DUMMY_HASH = "$2b$12$LJ3m4ys3Lg3rJFmKBOxTkO0UpBiVNBqXkT6T8sYzXvqFqPnXsO3cO"


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (cost factor 12)."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return _pwd_context.verify(plain, hashed)


@dataclass(frozen=True)
class TokenRecord:
    label: str
    token: str
    token_id: str


@dataclass(frozen=True)
class AuthPrincipal:
    label: str
    token_id: str
    source: str
    user_id: str | None = None
    roles: tuple[str, ...] = ()
    email: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class AuthConfig:
    tokens: tuple[TokenRecord, ...]
    session_cookie_name: str
    session_ttl_sec: int
    session_secret: str


def _parse_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    normalized = raw.replace("\n", ",").replace(";", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _build_auth_config() -> AuthConfig:
    raw_tokens = _parse_csv_env("GABI_API_TOKENS")
    tokens: list[TokenRecord] = []
    for index, raw in enumerate(raw_tokens, start=1):
        label = f"token-{index}"
        token = raw
        if ":" in raw:
            maybe_label, maybe_token = raw.split(":", 1)
            if maybe_label.strip() and maybe_token.strip():
                label = maybe_label.strip()
                token = maybe_token.strip()
        token = token.strip()
        if not token:
            continue
        token_id = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        tokens.append(TokenRecord(label=label, token=token, token_id=token_id))

    session_secret = os.getenv("GABI_AUTH_SECRET", "").strip()
    if not session_secret and tokens and os.getenv("FLY_APP_NAME", "").strip():
        raise RuntimeError(
            "GABI_AUTH_SECRET must be set in production (Fly.io). "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not session_secret and tokens:
        import warnings
        warnings.warn(
            "GABI_AUTH_SECRET not set — deriving session secret from token IDs (local dev only)",
            stacklevel=2,
        )
        session_secret = hashlib.sha256(
            "|".join(record.token_id for record in tokens).encode("utf-8")
        ).hexdigest()

    ttl_raw = os.getenv("GABI_SESSION_TTL_SEC", "43200").strip()
    try:
        session_ttl_sec = max(300, int(ttl_raw))
    except ValueError:
        session_ttl_sec = 43200

    return AuthConfig(
        tokens=tuple(tokens),
        session_cookie_name=os.getenv("GABI_SESSION_COOKIE", "gabi_session").strip() or "gabi_session",
        session_ttl_sec=session_ttl_sec,
        session_secret=session_secret,
    )


def get_auth_config() -> AuthConfig:
    return _build_auth_config()


async def bootstrap_identity_store(config: AuthConfig | None = None) -> None:
    config = config or get_auth_config()
    await ensure_identity_schema()
    await sync_env_tokens(
        [{"label": record.label, "token_id": record.token_id} for record in config.tokens]
    )


async def _enrich_principal(principal: AuthPrincipal) -> AuthPrincipal:
    try:
        identity = await resolve_identity_for_token(principal.token_id)
    except Exception:
        return principal
    if identity is None:
        return principal
    try:
        await touch_token_usage(principal.token_id)
    except Exception:
        pass
    return AuthPrincipal(
        label=identity.display_name or principal.label,
        token_id=principal.token_id,
        source=principal.source,
        user_id=identity.user_id,
        roles=identity.roles,
        email=identity.email,
        status=identity.status,
    )


def request_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def request_hostname(request: Request) -> str:
    return (request.url.hostname or request.headers.get("host", "").split(":", 1)[0]).strip().lower()


def _is_local_dev_request(request: Request) -> bool:
    if os.getenv("FLY_APP_NAME", "").strip():
        return False
    host = request_hostname(request)
    if host in LOCAL_HOSTS:
        return True
    return request_ip(request) in LOCAL_HOSTS


def _deny_auth(request: Request, *, detail: str, event: str) -> None:
    log_security_event(
        event,
        ip=request_ip(request),
        host=request_hostname(request),
        path=request.url.path,
        method=request.method,
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _misconfigured_auth(request: Request) -> None:
    log_security_event(
        "auth_misconfigured",
        ip=request_ip(request),
        host=request_hostname(request),
        path=request.url.path,
        method=request.method,
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication is not configured for this environment",
    )


def _bearer_token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header:
        return None
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _find_token_record(token: str, config: AuthConfig) -> TokenRecord | None:
    for record in config.tokens:
        if hmac.compare_digest(record.token, token):
            return record
    return None


def _sign_session(config: AuthConfig, payload: str) -> str:
    return hmac.new(
        config.session_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _encode_session(config: AuthConfig, principal: AuthPrincipal) -> str:
    payload = {
        "exp": int(time.time()) + config.session_ttl_sec,
        "label": principal.label,
        "sub": principal.token_id,
    }
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = _sign_session(config, encoded_payload)
    return f"{encoded_payload}.{signature}"


def _decode_session(cookie_value: str, config: AuthConfig) -> dict[str, Any] | None:
    if not cookie_value or "." not in cookie_value or not config.session_secret:
        return None
    encoded_payload, signature = cookie_value.split(".", 1)
    expected_signature = _sign_session(config, encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        return None
    padding = "=" * ((4 - len(encoded_payload) % 4) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(f"{encoded_payload}{padding}".encode("ascii")))
    except Exception:
        return None
    if int(payload.get("exp") or 0) < int(time.time()):
        return None
    return payload


async def resolve_request_principal(
    request: Request,
    *,
    allow_session: bool = True,
    log_failures: bool = True,
) -> AuthPrincipal | None:
    config = get_auth_config()
    if not config.tokens and _is_local_dev_request(request):
        return AuthPrincipal(label="local-dev", token_id="local-dev", source="local-dev", roles=("admin", "user"))

    bearer_token = _bearer_token_from_request(request)
    if bearer_token:
        record = _find_token_record(bearer_token, config)
        if record is not None:
            return await _enrich_principal(
                AuthPrincipal(label=record.label, token_id=record.token_id, source="bearer")
            )
        db_token_id = token_id_for_secret(bearer_token)
        db_principal = await _enrich_principal(
            AuthPrincipal(label="db-token", token_id=db_token_id, source="bearer")
        )
        if db_principal.user_id is not None:
            return db_principal
        if log_failures:
            _deny_auth(request, detail="Invalid bearer token", event="auth_invalid_token")
        return None

    if allow_session:
        cookie_value = request.cookies.get(config.session_cookie_name, "")
        payload = _decode_session(cookie_value, config)
        if payload:
            token_id = str(payload.get("sub") or "")
            for record in config.tokens:
                if record.token_id == token_id:
                    return await _enrich_principal(
                        AuthPrincipal(
                            label=str(payload.get("label") or record.label),
                            token_id=record.token_id,
                            source="session",
                        )
                    )
            db_principal = await _enrich_principal(
                AuthPrincipal(
                    label=str(payload.get("label") or "session"),
                    token_id=token_id,
                    source="session",
                )
            )
            if db_principal.user_id is not None:
                return db_principal
            # Fallback: password users store user UUID as session sub,
            # not an api_token token_id -- resolve via user table directly.
            try:
                identity = await resolve_identity_for_user_id(token_id)
            except Exception:
                identity = None
            if identity is not None:
                return AuthPrincipal(
                    label=identity.display_name or str(payload.get("label") or "session"),
                    token_id=token_id,
                    source="session",
                    user_id=identity.user_id,
                    roles=identity.roles,
                    email=identity.email,
                    status=identity.status,
                )
            log_security_event(
                "auth_invalid_session_subject",
                ip=request_ip(request),
                host=request_hostname(request),
                path=request.url.path,
                method=request.method,
            )

    if log_failures:
        _deny_auth(request, detail="Authentication required", event="auth_missing")
    return None

def _rate_rule_for_path(path: str) -> tuple[str, RateRule]:
    if path == "/api/chat":
        return "chat", RateRule(limit=20, window_sec=60)
    if path.endswith("/pdf"):
        return "document_pdf", RateRule(limit=10, window_sec=60)
    if "/api/media/" in path:
        return "media", RateRule(limit=90, window_sec=60)
    if path.endswith("/graph"):
        return "document_graph", RateRule(limit=30, window_sec=60)
    return "document_read", RateRule(limit=60, window_sec=60)


async def require_protected_access(request: Request) -> AuthPrincipal:
    principal = await resolve_request_principal(request)
    assert principal is not None
    limiter = getattr(request.app.state, "rate_limiter", None)
    if isinstance(limiter, RateLimiter):
        bucket, rule = _rate_rule_for_path(request.url.path)
        await limiter.enforce(
            bucket=bucket,
            key=principal.token_id,
            rule=rule,
            request=request,
            dimension="principal",
        )
        await limiter.enforce(
            bucket=bucket,
            key=request_ip(request),
            rule=RateRule(limit=max(rule.limit * 2, 30), window_sec=rule.window_sec),
            request=request,
            dimension="ip",
        )
    request.state.auth_principal = principal
    return principal


async def require_admin_access(request: Request) -> AuthPrincipal:
    principal = await require_protected_access(request)
    if "admin" not in principal.roles:
        log_security_event(
            "admin_access_denied",
            ip=request_ip(request),
            host=request_hostname(request),
            path=request.url.path,
            method=request.method,
            principal=principal.token_id,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return principal


def create_session_response(request: Request, principal: AuthPrincipal) -> Response:
    config = get_auth_config()
    if not config.session_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session secret is not configured",
        )
    response = Response(
        content=json.dumps(
            {
                "authenticated": True,
                "principal": {
                    "label": principal.label,
                    "source": principal.source,
                    "user_id": principal.user_id,
                    "roles": list(principal.roles),
                    "email": principal.email,
                    "status": principal.status,
                },
            },
            ensure_ascii=True,
        ),
        media_type="application/json",
    )
    attach_cookie(
        response,
        name=config.session_cookie_name,
        value=_encode_session(config, principal),
        request=request,
        max_age=config.session_ttl_sec,
    )
    return response


__all__ = [
    "AuthPrincipal",
    "AuthConfig",
    "DUMMY_HASH",
    "bootstrap_identity_store",
    "clear_session_response",
    "create_session_response",
    "get_auth_config",
    "hash_password",
    "issue_api_token",
    "list_roles",
    "list_users",
    "replace_user_roles",
    "request_ip",
    "request_hostname",
    "revoke_api_token",
    "require_admin_access",
    "require_protected_access",
    "resolve_request_principal",
    "upsert_user",
    "verify_password",
]


def clear_session_response() -> Response:
    config = get_auth_config()
    same_site = os.getenv("GABI_SESSION_SAMESITE", "lax").strip().lower() or "lax"
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    response = Response(content='{"authenticated": false}', media_type="application/json")
    response.delete_cookie(
        key=config.session_cookie_name,
        path="/",
        secure=same_site == "none",
        samesite=same_site,  # type: ignore[arg-type]
    )
    return response
