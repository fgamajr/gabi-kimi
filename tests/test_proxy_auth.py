"""Tests for worker proxy auth guard, rate limiter, toggle, and access logging.

Phase 13 Plan 01 — FLY-03 gap closure.
"""
from __future__ import annotations

import contextlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.backend.apps.auth import AuthPrincipal

_BASE = "http://localhost"


def _fake_admin() -> AuthPrincipal:
    return AuthPrincipal(
        label="test-admin",
        token_id="test-token-id",
        source="test",
        roles=("admin",),
        user_id="test-user",
    )


def _mock_httpx_response(status: int = 200, body: bytes = b'{"ok":true}') -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = body
    resp.headers = {"content-type": "application/json"}
    return resp


def _patch_outbound_proxy():
    """Patch httpx.AsyncClient used inside proxy_worker to avoid real HTTP calls.

    Returns a context manager that patches the AsyncClient constructor in
    web_server so that the *outbound* proxy client returns a mock response,
    while the test's ASGITransport-based client is unaffected.
    """
    mock_resp = _mock_httpx_response(200)

    real_init = httpx.AsyncClient.__init__

    class _FakeOutboundClient:
        """Stand-in for the outbound httpx.AsyncClient inside proxy_worker."""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def request(self, **kwargs):
            return mock_resp

    original_class = httpx.AsyncClient

    @contextlib.contextmanager
    def _cm():
        import src.backend.apps.web_server as ws

        _orig = httpx.AsyncClient

        class _PatchedClient(httpx.AsyncClient):
            """Intercept only bare AsyncClient() (no transport=) — the proxy path."""

            def __new__(cls, *args, **kwargs):
                if "transport" in kwargs or args:
                    # Test client with ASGITransport — pass through
                    return super().__new__(cls)
                # Proxy outbound call — return fake
                return _FakeOutboundClient()

        # Monkey-patch at module level so `async with httpx.AsyncClient() as client:` hits our class
        ws_httpx = __import__("httpx")
        original_ac = ws_httpx.AsyncClient
        ws_httpx.AsyncClient = _PatchedClient
        try:
            yield mock_resp
        finally:
            ws_httpx.AsyncClient = original_ac

    return _cm()


class TestProxyAuth(unittest.IsolatedAsyncioTestCase):
    """Auth guard tests for /api/worker/* proxy route."""

    async def test_proxy_rejects_unauthenticated(self):
        """GET /api/worker/health without auth returns 401 or 403."""
        from src.backend.apps.web_server import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=_BASE) as client:
            resp = await client.get("/api/worker/health")
        self.assertIn(resp.status_code, (401, 403))

    async def test_proxy_allows_admin(self):
        """GET /api/worker/health with mocked admin principal returns 200."""
        from src.backend.apps.web_server import app
        from src.backend.apps.web_server import _require_proxy_auth

        app.dependency_overrides[_require_proxy_auth] = _fake_admin
        try:
            with _patch_outbound_proxy():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url=_BASE) as client:
                    resp = await client.get("/api/worker/health")
                self.assertEqual(resp.status_code, 200)
        finally:
            app.dependency_overrides.pop(_require_proxy_auth, None)

    @patch("src.backend.apps.web_server.log_security_event")
    async def test_rate_limit_exceeded(self, mock_log: MagicMock):
        """After 60+ requests in sliding window, returns 429 with Retry-After header."""
        from src.backend.apps.web_server import app, _WORKER_PROXY_RATE_RULE, _require_proxy_auth as _rpa
        from src.backend.apps.middleware.security import RateLimiter

        app.dependency_overrides[_rpa] = _fake_admin

        limiter = RateLimiter(redis_url=None)
        await limiter.startup()
        app.state.rate_limiter = limiter

        try:
            with _patch_outbound_proxy():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url=_BASE) as client:
                    last_resp = None
                    for _ in range(_WORKER_PROXY_RATE_RULE.limit + 1):
                        last_resp = await client.get("/api/worker/health")
                        if last_resp.status_code == 429:
                            break
                    self.assertIsNotNone(last_resp)
                    self.assertEqual(last_resp.status_code, 429)
                    self.assertIn("retry-after", last_resp.headers)
        finally:
            app.dependency_overrides.pop(_rpa, None)
            await limiter.shutdown()

    @patch("src.backend.apps.web_server.log_security_event")
    async def test_proxy_access_logged(self, mock_log: MagicMock):
        """Proxy access creates structured log record with user identity and endpoint path."""
        from src.backend.apps.web_server import app
        from src.backend.apps.web_server import _require_proxy_auth

        app.dependency_overrides[_require_proxy_auth] = _fake_admin

        try:
            with _patch_outbound_proxy():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url=_BASE) as client:
                    await client.get("/api/worker/health")

            mock_log.assert_called()
            call_args = mock_log.call_args
            self.assertEqual(call_args[0][0], "worker_proxy_access")
            self.assertEqual(call_args[1]["path"], "health")
            self.assertEqual(call_args[1]["principal"], "test-token-id")
        finally:
            app.dependency_overrides.pop(_require_proxy_auth, None)

    async def test_toggle_bypass(self):
        """When WORKER_PROXY_AUTH_ENABLED=false, unauthenticated requests are proxied."""
        import src.backend.apps.web_server as ws
        from src.backend.apps.web_server import app

        original = ws._WORKER_PROXY_AUTH_ENABLED
        try:
            ws._WORKER_PROXY_AUTH_ENABLED = False
            with _patch_outbound_proxy():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url=_BASE) as client:
                    resp = await client.get("/api/worker/health")
                self.assertEqual(resp.status_code, 200)
        finally:
            ws._WORKER_PROXY_AUTH_ENABLED = original

    async def test_healthz_includes_proxy_auth(self):
        """GET /healthz response includes proxy_auth_enabled boolean field."""
        from src.backend.apps.web_server import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=_BASE) as client:
            resp = await client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("proxy_auth_enabled", data)
        self.assertIsInstance(data["proxy_auth_enabled"], bool)


class TestTraceability(unittest.TestCase):
    def test_all_requirements_complete(self):
        """Assert every entry in REQUIREMENTS.md traceability table shows Complete."""
        import re
        from pathlib import Path

        req_path = Path(__file__).resolve().parent.parent / ".planning" / "REQUIREMENTS.md"
        if not req_path.exists():
            self.skipTest("REQUIREMENTS.md not found")
        content = req_path.read_text()
        # Find traceability table rows: | REQ-ID | Phase X | Status |
        rows = re.findall(r"\|\s*(\w+-\d+)\s*\|[^|]+\|\s*(\w+)\s*\|", content)
        self.assertTrue(len(rows) > 0, "No traceability rows found")
        for req_id, status in rows:
            self.assertEqual(status, "Complete", f"{req_id} is not Complete: {status}")
