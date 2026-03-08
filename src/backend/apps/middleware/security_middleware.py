from __future__ import annotations

from collections.abc import Iterable
import os
import re
import time
from urllib.parse import unquote

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from src.backend.apps.chat_security import ChatSecurity, client_fingerprint
from src.backend.apps.middleware.security import build_content_security_policy, log_security_event


BLOCK_TIME_SEC = max(60, int(os.getenv("GABI_SECURITY_BLOCK_TIME_SEC", "3600")))
SCAN_THRESHOLD = max(2, int(os.getenv("GABI_SECURITY_SCAN_THRESHOLD", "6")))
SUSPICIOUS_SCANNER_FRAGMENTS = (
    "sqlmap",
    "nikto",
    "acunetix",
    "nessus",
    "nmap",
    "masscan",
    "wpscan",
    "dirbuster",
    "gobuster",
    "zgrab",
)
WAF_RULES = (
    re.compile(r"\.\./", re.IGNORECASE),
    re.compile(r"/etc/passwd", re.IGNORECASE),
    re.compile(r"union(?:\s|/\*.*?\*/)+select", re.IGNORECASE),
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"\bcmd=", re.IGNORECASE),
)
BLOCKED_IPS: dict[str, float] = {}
SCAN_SCORES: dict[str, int] = {}


def request_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def request_is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.lower() == "https"


def parse_byte_limit(raw: str | None, default: int) -> int:
    if not raw or not raw.strip():
        return default
    try:
        return max(1024, int(raw.strip()))
    except ValueError:
        return default


class AppSecurityMiddleware(BaseHTTPMiddleware):
    """Cross-cutting protections that complement route-level auth and path containment."""

    def __init__(
        self,
        app,
        *,
        csp: str | None = None,
        max_body_size: int | None = None,
        protected_prefixes: Iterable[str] | None = None,
    ):
        super().__init__(app)
        self._csp = csp or build_content_security_policy()
        self._max_body_size = max_body_size or parse_byte_limit(
            os.getenv("GABI_MAX_BODY_SIZE_BYTES"),
            2 * 1024 * 1024,
        )
        self._protected_prefixes = tuple(
            protected_prefixes or ("/api/chat", "/api/document", "/api/media")
        )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip = request_ip(request)
        raw_path = request.scope.get("raw_path", b"")
        decoded_raw_path = (
            raw_path.decode("latin-1", errors="ignore") if isinstance(raw_path, (bytes, bytearray)) else path
        )
        request.state.client_fingerprint = client_fingerprint(request)

        self._check_ip_block(ip, path, request.method)
        await self._detect_path_abuse(request, path, decoded_raw_path)
        await self._detect_scanner_ua(request, ip, path)
        await self._run_waf_rules(request, ip, path)
        await self._enforce_body_size(request, path)

        response = await call_next(request)
        self._apply_security_headers(request, response)
        return response

    def _apply_security_headers(self, request: Request, response) -> None:
        response.headers.setdefault("Content-Security-Policy", self._csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if request_is_https(request):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    async def _detect_path_abuse(self, request: Request, path: str, raw_path: str) -> None:
        decoded_path = unquote(raw_path or path).lower()
        suspicious = (
            ".." in decoded_path
            or "%2e%2e" in decoded_path
            or "%2f" in decoded_path and ".." in decoded_path
            or "\\.." in decoded_path
            or "%5c" in decoded_path and ".." in decoded_path
        )
        if not suspicious:
            return
        log_security_event(
            "path_traversal_attempt",
            ip=request_ip(request),
            method=request.method,
            path=path,
            raw_path=raw_path or path,
        )
        await self._note_abuse(request, event="path_traversal_attempt", weight=4)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid path")

    async def _detect_scanner_ua(self, request: Request, ip: str, path: str) -> None:
        user_agent = request.headers.get("user-agent", "").strip().lower()
        if not user_agent:
            if path.startswith("/api/"):
                log_security_event(
                    "missing_user_agent",
                    ip=request_ip(request),
                    path=path,
                    method=request.method,
                )
            return

        for fragment in SUSPICIOUS_SCANNER_FRAGMENTS:
            if fragment not in user_agent:
                continue
            self._block_ip(ip, reason="scanner_user_agent", path=path)
            await self._note_abuse(request, event="scanner_user_agent", weight=5)
            log_security_event(
                "scanner_user_agent_blocked",
                ip=ip,
                path=path,
                method=request.method,
                user_agent=user_agent[:180],
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    async def _run_waf_rules(self, request: Request, ip: str, path: str) -> None:
        if not path.startswith("/api/") and not path.startswith("/dist/"):
            return
        query = request.url.query
        target = unquote(f"{path}?{query}" if query else path)
        for rule in WAF_RULES:
            if not rule.search(target):
                continue
            score = SCAN_SCORES.get(ip, 0) + 1
            SCAN_SCORES[ip] = score
            log_security_event(
                "waf_triggered",
                ip=ip,
                path=path,
                method=request.method,
                rule=rule.pattern,
                score=score,
            )
            await self._note_abuse(request, event="waf_triggered", weight=3)
            if score >= SCAN_THRESHOLD:
                self._block_ip(ip, reason="waf_threshold", path=path)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Blocked by security policy")

    async def _enforce_body_size(self, request: Request, path: str) -> None:
        if request.method not in {"POST", "PUT", "PATCH"}:
            return
        if not any(path.startswith(prefix) for prefix in self._protected_prefixes):
            return

        content_length = request.headers.get("content-length", "").strip()
        if content_length:
            try:
                if int(content_length) > self._max_body_size:
                    self._reject_large_body(request, path, declared_size=int(content_length))
            except ValueError:
                log_security_event(
                    "invalid_content_length",
                    ip=request_ip(request),
                    path=path,
                    method=request.method,
                    header=content_length,
                )

        body = await request.body()
        if len(body) > self._max_body_size:
            self._reject_large_body(request, path, declared_size=len(body))

    def _reject_large_body(self, request: Request, path: str, *, declared_size: int) -> None:
        log_security_event(
            "request_body_too_large",
            ip=request_ip(request),
            path=path,
            method=request.method,
            size_bytes=declared_size,
            max_bytes=self._max_body_size,
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Request body too large",
        )

    def _check_ip_block(self, ip: str, path: str, method: str) -> None:
        expires_at = BLOCKED_IPS.get(ip)
        if not expires_at:
            return
        if time.time() >= expires_at:
            del BLOCKED_IPS[ip]
            return
        log_security_event(
            "blocked_ip_request_denied",
            ip=ip,
            path=path,
            method=method,
            expires_at=expires_at,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP temporarily blocked")

    def _block_ip(self, ip: str, *, reason: str, path: str) -> None:
        BLOCKED_IPS[ip] = time.time() + BLOCK_TIME_SEC
        log_security_event(
            "ip_blocked",
            ip=ip,
            reason=reason,
            path=path,
            block_time_sec=BLOCK_TIME_SEC,
        )

    async def _note_abuse(self, request: Request, *, event: str, weight: int) -> None:
        chat_security = getattr(request.app.state, "chat_security", None)
        if isinstance(chat_security, ChatSecurity):
            await chat_security.note_abuse_event(request, event=event, weight=weight)
