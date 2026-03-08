from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
import time
from typing import Any

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

try:
    from redis.asyncio import Redis
    from redis.asyncio import from_url as redis_from_url
except Exception:  # pragma: no cover - optional dependency at runtime
    Redis = None  # type: ignore[assignment]
    redis_from_url = None


SECURITY_LOGGER = logging.getLogger("gabi.security")


def log_security_event(event: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    SECURITY_LOGGER.warning(json.dumps(payload, ensure_ascii=True, sort_keys=True))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject default security headers into every response."""

    def __init__(self, app, *, csp: str):
        super().__init__(app)
        self._csp = csp

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", self._csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if _request_is_https(request):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def build_content_security_policy() -> str:
    return "; ".join(
        [
            "default-src 'self'",
            "base-uri 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "form-action 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com data:",
            "img-src 'self' data: blob: https:",
            "connect-src 'self'",
        ]
    )


@dataclass(frozen=True)
class RateRule:
    limit: int
    window_sec: int


class RateLimiter:
    """Rate limiter with optional Redis backend and in-memory fallback."""

    def __init__(self, redis_url: str | None = None, prefix: str = "gabi:ratelimit"):
        self._redis_url = (redis_url or "").strip()
        self._prefix = prefix
        self._memory: dict[str, deque[float]] = defaultdict(deque)
        self._memory_lock = asyncio.Lock()
        self._redis: Redis | None = None

    async def startup(self) -> None:
        if self._redis_url and redis_from_url is not None:
            self._redis = redis_from_url(self._redis_url, encoding="utf-8", decode_responses=True)

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def enforce(
        self,
        *,
        bucket: str,
        key: str,
        rule: RateRule,
        request: Request,
        dimension: str,
    ) -> None:
        allowed, retry_after = await self._check(bucket=bucket, key=key, rule=rule)
        if allowed:
            return
        log_security_event(
            "rate_limit_exceeded",
            bucket=bucket,
            dimension=dimension,
            key=key,
            limit=rule.limit,
            window_sec=rule.window_sec,
            ip=_request_ip(request),
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    async def _check(self, *, bucket: str, key: str, rule: RateRule) -> tuple[bool, int]:
        now = time.time()
        if self._redis is not None:
            return await self._check_redis(bucket=bucket, key=key, rule=rule, now=now)
        return await self._check_memory(bucket=bucket, key=key, rule=rule, now=now)

    async def _check_redis(self, *, bucket: str, key: str, rule: RateRule, now: float) -> tuple[bool, int]:
        assert self._redis is not None
        window = int(now // rule.window_sec)
        redis_key = f"{self._prefix}:{bucket}:{window}:{key}"
        count = await self._redis.incr(redis_key)
        if count == 1:
            await self._redis.expire(redis_key, rule.window_sec + 1)
        retry_after = max(1, int(rule.window_sec - (now % rule.window_sec)))
        return count <= rule.limit, retry_after

    async def _check_memory(self, *, bucket: str, key: str, rule: RateRule, now: float) -> tuple[bool, int]:
        memory_key = f"{bucket}:{key}"
        cutoff = now - rule.window_sec
        async with self._memory_lock:
            bucket_entries = self._memory[memory_key]
            while bucket_entries and bucket_entries[0] <= cutoff:
                bucket_entries.popleft()
            if len(bucket_entries) >= rule.limit:
                retry_after = max(1, int(rule.window_sec - (now - bucket_entries[0])))
                return False, retry_after
            bucket_entries.append(now)
        return True, rule.window_sec


def _request_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _request_is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.lower() == "https"


def attach_cookie(response: Response, *, name: str, value: str, request: Request, max_age: int) -> None:
    same_site = os.getenv("GABI_SESSION_SAMESITE", "lax").strip().lower() or "lax"
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    secure = _request_is_https(request) or same_site == "none"
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=same_site,  # type: ignore[arg-type]
        path="/",
    )


def local_dev_origins() -> list[str]:
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def hostnames_to_origins(hosts: list[str]) -> list[str]:
    origins: list[str] = []
    for host in hosts:
        normalized = host.strip()
        if not normalized or normalized == "*" or "*" in normalized:
            continue
        origins.append(f"https://{normalized}")
        if normalized in {"localhost", "127.0.0.1", "::1"}:
            origins.append(f"http://{normalized}")
    return origins
