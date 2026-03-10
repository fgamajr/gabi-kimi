from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
import time
from typing import Any

from fastapi import HTTPException, Request, status

from src.backend.apps.middleware.security import RateLimiter, RateRule, log_security_event

try:
    from redis.asyncio import Redis
    from redis.asyncio import from_url as redis_from_url
except Exception:  # pragma: no cover - optional dependency at runtime
    Redis = None  # type: ignore[assignment]
    redis_from_url = None


def request_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def normalize_text(value: str, *, limit: int = 4000) -> str:
    return " ".join((value or "").strip().lower().split())[:limit]


def prompt_fingerprint(message: str, history: list[dict[str, str]] | None = None) -> str:
    payload = {
        "message": normalize_text(message, limit=6000),
        "history": [
            {
                "role": normalize_text(str(item.get("role", "")), limit=32),
                "content": normalize_text(str(item.get("content", "")), limit=512),
            }
            for item in (history or [])[-6:]
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def client_fingerprint(request: Request) -> str:
    data = "|".join(
        [
            request_ip(request),
            request.headers.get("user-agent", "").strip().lower(),
            request.headers.get("accept-language", "").strip().lower(),
        ]
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RiskState:
    fingerprint: str
    score: int
    blocked_until: float | None


class ChatSecurity:
    """Redis-backed chat protections: prompt cache, risk score, and shadow rate limits."""

    def __init__(self, redis_url: str | None = None, prefix: str = "gabi:chat"):
        self._redis_url = (redis_url or "").strip()
        self._prefix = prefix
        self._redis: Redis | None = None
        self._memory_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._memory_scores: dict[str, tuple[int, float]] = {}
        self._memory_blocks: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._cache_ttl_sec = max(30, int(os.getenv("GABI_CHAT_CACHE_TTL_SEC", "300")))
        self._score_ttl_sec = max(300, int(os.getenv("GABI_CHAT_SCORE_TTL_SEC", "3600")))
        self._block_threshold = max(4, int(os.getenv("GABI_CHAT_BLOCK_THRESHOLD", "10")))
        self._block_time_sec = max(60, int(os.getenv("GABI_CHAT_BLOCK_TIME_SEC", "3600")))

    async def startup(self) -> None:
        if self._redis_url and redis_from_url is not None:
            self._redis = redis_from_url(self._redis_url, encoding="utf-8", decode_responses=True)

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def enforce(self, request: Request, *, limiter: RateLimiter | None) -> RiskState:
        risk = await self.get_risk_state(request)
        now = time.time()
        if risk.blocked_until and risk.blocked_until > now:
            log_security_event(
                "chat_risk_blocked",
                ip=request_ip(request),
                path=request.url.path,
                score=risk.score,
                blocked_until=risk.blocked_until,
                fingerprint=risk.fingerprint[:16],
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chat access temporarily blocked")

        if limiter is not None:
            rule = self._shadow_rule(risk.score)
            await limiter.enforce(
                bucket="chat_shadow",
                key=risk.fingerprint,
                rule=rule,
                request=request,
                dimension="client_fingerprint",
            )
        return risk

    async def get_cached_reply(
        self, message: str, history: list[dict[str, str]] | None = None
    ) -> dict[str, Any] | None:
        fingerprint = prompt_fingerprint(message, history)
        if self._redis is not None:
            raw = await self._redis.get(self._k("cache", fingerprint))
            if not raw:
                return None
            try:
                payload = json.loads(raw)
            except Exception:
                return None
            return payload if isinstance(payload, dict) else None

        async with self._lock:
            item = self._memory_cache.get(fingerprint)
            if not item:
                return None
            expires_at, payload = item
            if expires_at <= time.time():
                del self._memory_cache[fingerprint]
                return None
            return payload

    async def cache_reply(self, message: str, history: list[dict[str, str]] | None, payload: dict[str, Any]) -> None:
        fingerprint = prompt_fingerprint(message, history)
        safe_payload = {
            "reply": str(payload.get("reply", ""))[:20000],
            "model": str(payload.get("model", "gabi"))[:120],
            "cache": "hit",
            "sources": payload.get("sources") if isinstance(payload.get("sources"), list) else [],
        }
        if self._redis is not None:
            await self._redis.set(
                self._k("cache", fingerprint),
                json.dumps(safe_payload, ensure_ascii=False),
                ex=self._cache_ttl_sec,
            )
            return

        async with self._lock:
            self._memory_cache[fingerprint] = (time.time() + self._cache_ttl_sec, safe_payload)

    async def note_abuse_event(self, request: Request, *, event: str, weight: int) -> int:
        fingerprint = client_fingerprint(request)
        now = time.time()
        if self._redis is not None:
            score_key = self._k("score", fingerprint)
            score = await self._redis.incrby(score_key, weight)
            await self._redis.expire(score_key, self._score_ttl_sec)
            if score >= self._block_threshold:
                await self._redis.set(
                    self._k("block", fingerprint), str(now + self._block_time_sec), ex=self._block_time_sec
                )
            log_security_event(
                "chat_abuse_score_updated",
                event=event,
                weight=weight,
                score=score,
                ip=request_ip(request),
                fingerprint=fingerprint[:16],
            )
            return int(score)

        async with self._lock:
            score, expires_at = self._memory_scores.get(fingerprint, (0, now + self._score_ttl_sec))
            if expires_at <= now:
                score = 0
                expires_at = now + self._score_ttl_sec
            score += weight
            self._memory_scores[fingerprint] = (score, expires_at)
            if score >= self._block_threshold:
                self._memory_blocks[fingerprint] = now + self._block_time_sec
            log_security_event(
                "chat_abuse_score_updated",
                event=event,
                weight=weight,
                score=score,
                ip=request_ip(request),
                fingerprint=fingerprint[:16],
            )
            return score

    async def get_risk_state(self, request: Request) -> RiskState:
        fingerprint = client_fingerprint(request)
        now = time.time()
        if self._redis is not None:
            score_raw, block_raw = await asyncio.gather(
                self._redis.get(self._k("score", fingerprint)),
                self._redis.get(self._k("block", fingerprint)),
            )
            score = int(score_raw or 0)
            blocked_until = float(block_raw) if block_raw else None
            return RiskState(fingerprint=fingerprint, score=score, blocked_until=blocked_until)

        async with self._lock:
            score, expires_at = self._memory_scores.get(fingerprint, (0, now))
            if expires_at <= now:
                score = 0
                self._memory_scores.pop(fingerprint, None)
            blocked_until = self._memory_blocks.get(fingerprint)
            if blocked_until and blocked_until <= now:
                self._memory_blocks.pop(fingerprint, None)
                blocked_until = None
            return RiskState(fingerprint=fingerprint, score=score, blocked_until=blocked_until)

    def _shadow_rule(self, score: int) -> RateRule:
        if score >= 8:
            return RateRule(limit=3, window_sec=60)
        if score >= 4:
            return RateRule(limit=10, window_sec=60)
        return RateRule(limit=20, window_sec=60)

    def _k(self, kind: str, suffix: str) -> str:
        return f"{self._prefix}:{kind}:{suffix}"
