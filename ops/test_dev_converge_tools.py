"""Comprehensive test suite for the hosted dev-converge service.

Tests are grouped into four layers:
  1. providers  — catalog decode/validate/redact, 3 provider HTTP calls (mocked)
  2. executor   — panel patterns with in-process mock agents
  3. jobs       — MongoDB interactions (mongomock or real local instance)
  4. auth/http  — ASGI auth wrapper + X-Dev-Converge-Agents header handling

Usage:
  python -m pytest ops/test_dev_converge_tools.py -v
  python ops/test_dev_converge_tools.py          # fallback runner
"""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dev_converge.providers import (  # noqa: E402
    build_agent,
    decode_catalog,
    get_default_synthesizer,
    redact_catalog,
    resolve_agents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_catalog_header(agents: list[dict], default_synthesizer: str = "") -> str:
    payload: dict[str, Any] = {"agents": agents}
    if default_synthesizer:
        payload["default_synthesizer"] = default_synthesizer
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


KIMI_AGENT = {
    "name": "kimi",
    "provider": "openai_compatible",
    "model": "kimi-k2.5",
    "api_key": "sk-kimi-test",
    "base_url": "https://dashscope.example.com/v1",
}
CLAUDE_AGENT = {
    "name": "claude",
    "provider": "anthropic_compatible",
    "model": "claude-sonnet-4-6",
    "api_key": "sk-ant-test",
    "base_url": "",
}
GEMINI_AGENT = {
    "name": "gemini",
    "provider": "gemini_compatible",
    "model": "gemini-2.0-flash",
    "api_key": "AIza-test",
    "base_url": "",
}


# ---------------------------------------------------------------------------
# 1. providers.py
# ---------------------------------------------------------------------------


class TestBuildAgent(unittest.TestCase):
    def test_valid_openai_compatible(self):
        spec = build_agent(KIMI_AGENT)
        self.assertEqual(spec.name, "kimi")
        self.assertEqual(spec.provider, "openai_compatible")
        self.assertEqual(spec.api_key, "sk-kimi-test")

    def test_valid_anthropic_compatible(self):
        spec = build_agent(CLAUDE_AGENT)
        self.assertEqual(spec.provider, "anthropic_compatible")

    def test_valid_gemini_compatible(self):
        spec = build_agent(GEMINI_AGENT)
        self.assertEqual(spec.provider, "gemini_compatible")

    def test_missing_required_field_raises(self):
        bad = {k: v for k, v in KIMI_AGENT.items() if k != "api_key"}
        with self.assertRaises(ValueError) as ctx:
            build_agent(bad)
        self.assertIn("api_key", str(ctx.exception))

    def test_unsupported_provider_raises(self):
        bad = {**KIMI_AGENT, "provider": "cohere"}
        with self.assertRaises(ValueError) as ctx:
            build_agent(bad)
        self.assertIn("cohere", str(ctx.exception))

    def test_base_url_optional(self):
        agent = {**KIMI_AGENT, "base_url": ""}
        spec = build_agent(agent)
        self.assertEqual(spec.base_url, "")


class TestDecodeCatalog(unittest.TestCase):
    def test_valid_single_agent(self):
        header = _make_catalog_header([KIMI_AGENT])
        agents = decode_catalog(header)
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].name, "kimi")

    def test_valid_multi_agent(self):
        header = _make_catalog_header([KIMI_AGENT, CLAUDE_AGENT, GEMINI_AGENT])
        agents = decode_catalog(header)
        self.assertEqual(len(agents), 3)
        names = [a.name for a in agents]
        self.assertIn("kimi", names)
        self.assertIn("claude", names)
        self.assertIn("gemini", names)

    def test_invalid_base64_raises(self):
        with self.assertRaises(ValueError):
            decode_catalog("not-valid-base64!!!")

    def test_missing_agents_key_raises(self):
        raw = base64.urlsafe_b64encode(b'{"foo": "bar"}').rstrip(b"=").decode()
        with self.assertRaises(ValueError) as ctx:
            decode_catalog(raw)
        self.assertIn("agents", str(ctx.exception))

    def test_empty_agents_array_raises(self):
        header = _make_catalog_header([])
        with self.assertRaises(ValueError):
            decode_catalog(header)

    def test_agent_entry_not_dict_raises(self):
        raw = (
            base64.urlsafe_b64encode(b'{"agents": ["not-a-dict"]}')
            .rstrip(b"=")
            .decode()
        )
        with self.assertRaises(ValueError):
            decode_catalog(raw)

    def test_padding_tolerance(self):
        # header with and without = padding should both work
        header = _make_catalog_header([KIMI_AGENT])
        padded = header + "=" * (4 - len(header) % 4)
        agents = decode_catalog(padded)
        self.assertEqual(agents[0].name, "kimi")


class TestGetDefaultSynthesizer(unittest.TestCase):
    def test_present(self):
        header = _make_catalog_header([KIMI_AGENT], default_synthesizer="kimi")
        self.assertEqual(get_default_synthesizer(header), "kimi")

    def test_absent_returns_empty(self):
        header = _make_catalog_header([KIMI_AGENT])
        self.assertEqual(get_default_synthesizer(header), "")

    def test_bad_header_returns_empty(self):
        self.assertEqual(get_default_synthesizer("garbage"), "")


class TestResolveAgents(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            build_agent(KIMI_AGENT),
            build_agent(CLAUDE_AGENT),
            build_agent(GEMINI_AGENT),
        ]

    def test_empty_string_returns_all(self):
        result = resolve_agents("", self.catalog)
        self.assertEqual(len(result), 3)

    def test_named_subset(self):
        result = resolve_agents("kimi,gemini", self.catalog)
        self.assertEqual([a.name for a in result], ["kimi", "gemini"])

    def test_unknown_name_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_agents("unknown-agent", self.catalog)
        self.assertIn("unknown-agent", str(ctx.exception))

    def test_single_name(self):
        result = resolve_agents("claude", self.catalog)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "claude")


class TestRedactCatalog(unittest.TestCase):
    def test_api_key_absent(self):
        catalog = [build_agent(KIMI_AGENT), build_agent(CLAUDE_AGENT)]
        redacted = redact_catalog(catalog)
        for entry in redacted:
            self.assertNotIn("api_key", entry)

    def test_safe_fields_present(self):
        catalog = [build_agent(KIMI_AGENT)]
        redacted = redact_catalog(catalog)
        self.assertEqual(redacted[0]["name"], "kimi")
        self.assertEqual(redacted[0]["provider"], "openai_compatible")
        self.assertEqual(redacted[0]["model"], "kimi-k2.5")
        self.assertIn("base_url", redacted[0])


# ---------------------------------------------------------------------------
# 2. provider HTTP calls (mocked httpx)
# ---------------------------------------------------------------------------


class TestProviderHTTPCalls(unittest.IsolatedAsyncioTestCase):
    def _mock_response(self, body: dict) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = body
        resp.raise_for_status = MagicMock()
        return resp

    async def test_call_openai_compatible(self):
        from src.dev_converge.providers import call_agent

        spec = build_agent(KIMI_AGENT)
        openai_response = {"choices": [{"message": {"content": "hello from kimi"}}]}
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._mock_response(openai_response))
        with patch(
            "src.dev_converge.providers.httpx.AsyncClient", return_value=mock_client
        ):
            result = await call_agent(
                spec=spec,
                prompt="hi",
                system_prompt="sys",
                temperature=0.0,
                max_tokens=50,
            )
        self.assertEqual(result["output"], "hello from kimi")
        self.assertEqual(result["agent"], "kimi")
        self.assertIn("latency_ms", result)

    async def test_call_anthropic_compatible(self):
        from src.dev_converge.providers import call_agent

        spec = build_agent(CLAUDE_AGENT)
        anthropic_response = {
            "content": [{"type": "text", "text": "hello from claude"}]
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            return_value=self._mock_response(anthropic_response)
        )
        with patch(
            "src.dev_converge.providers.httpx.AsyncClient", return_value=mock_client
        ):
            result = await call_agent(
                spec=spec,
                prompt="hi",
                system_prompt="sys",
                temperature=0.0,
                max_tokens=50,
            )
        self.assertEqual(result["output"], "hello from claude")

    async def test_call_gemini_compatible(self):
        from src.dev_converge.providers import call_agent

        spec = build_agent(GEMINI_AGENT)
        gemini_response = {
            "candidates": [{"content": {"parts": [{"text": "hello from gemini"}]}}]
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._mock_response(gemini_response))
        with patch(
            "src.dev_converge.providers.httpx.AsyncClient", return_value=mock_client
        ):
            result = await call_agent(
                spec=spec,
                prompt="hi",
                system_prompt="sys",
                temperature=0.0,
                max_tokens=50,
            )
        self.assertEqual(result["output"], "hello from gemini")


# ---------------------------------------------------------------------------
# 3. executor.py
# ---------------------------------------------------------------------------


def _mock_call_agent(output: str = "mock output"):
    """Return a coroutine mock that simulates a successful call_agent result."""

    async def _fake(*, spec, prompt, system_prompt, temperature, max_tokens):
        return {
            "agent": spec.name,
            "provider": spec.provider,
            "model": spec.model,
            "output": output,
            "latency_ms": 42.0,
        }

    return _fake


class TestExecutorGetDefaults(unittest.IsolatedAsyncioTestCase):
    async def test_required_fields(self):
        from src.dev_converge.executor import get_defaults

        result = await get_defaults()
        self.assertEqual(result["service"], "dev-converge")
        self.assertIn("required_header", result)
        self.assertIn("providers", result)
        self.assertIn("openai_compatible", result["providers"])
        self.assertIn("anthropic_compatible", result["providers"])
        self.assertIn("gemini_compatible", result["providers"])


class TestExecutorCompleteOnce(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.catalog = [build_agent(KIMI_AGENT), build_agent(CLAUDE_AGENT)]

    async def test_single_agent_in_catalog_no_name_required(self):
        from src.dev_converge.executor import complete_once

        single_catalog = [build_agent(KIMI_AGENT)]
        with patch(
            "src.dev_converge.executor.call_agent", side_effect=_mock_call_agent()
        ):
            result = await complete_once(task="test", catalog=single_catalog)
        self.assertNotIn("error", result)
        self.assertEqual(result["agent"], "kimi")

    async def test_multi_catalog_requires_agent_name(self):
        from src.dev_converge.executor import complete_once

        result = await complete_once(task="test", agent_name="", catalog=self.catalog)
        self.assertIn("error", result)
        self.assertIn("agent_name", result["error"])

    async def test_named_agent_selection(self):
        from src.dev_converge.executor import complete_once

        with patch(
            "src.dev_converge.executor.call_agent",
            side_effect=_mock_call_agent("claude response"),
        ):
            result = await complete_once(
                task="test", agent_name="claude", catalog=self.catalog
            )
        self.assertEqual(result["agent"], "claude")

    async def test_empty_catalog_returns_error(self):
        from src.dev_converge.executor import complete_once

        result = await complete_once(task="test", catalog=[])
        self.assertIn("error", result)


class TestExecutorPanels(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.catalog = [
            build_agent(KIMI_AGENT),
            build_agent(CLAUDE_AGENT),
            build_agent(GEMINI_AGENT),
        ]

    async def _run_with_mock(self, coro):
        with patch(
            "src.dev_converge.executor.call_agent", side_effect=_mock_call_agent()
        ):
            return await coro

    async def test_run_panel_returns_result(self):
        from src.dev_converge.executor import run_panel

        result = await self._run_with_mock(run_panel(task="test", catalog=self.catalog))
        self.assertIn("result", result)
        self.assertEqual(result["job_type"], "run_panel")
        self.assertEqual(len(result["agents"]), 3)

    async def test_run_panel_agent_subset(self):
        from src.dev_converge.executor import run_panel

        result = await self._run_with_mock(
            run_panel(task="test", agent_names="kimi,claude", catalog=self.catalog)
        )
        self.assertEqual(result["agents"], ["kimi", "claude"])

    async def test_swarm_panel_assigns_roles(self):
        from src.dev_converge.executor import swarm_panel

        result = await self._run_with_mock(
            swarm_panel(task="test", catalog=self.catalog)
        )
        self.assertIn("roles", result)
        self.assertEqual(len(result["roles"]), 3)

    async def test_jury_panel_returns_experts_and_jury(self):
        from src.dev_converge.executor import jury_panel

        result = await self._run_with_mock(
            jury_panel(
                task="test",
                expert_agents="kimi,claude",
                jury_agents="gemini",
                catalog=self.catalog,
            )
        )
        self.assertIn("experts", result)
        self.assertIn("jury", result)

    async def test_triangular_panel_transcript(self):
        from src.dev_converge.executor import triangular_panel

        result = await self._run_with_mock(
            triangular_panel(task="test", include_transcript=True, catalog=self.catalog)
        )
        self.assertIn("transcript", result)
        self.assertIn("initial", result["transcript"])
        self.assertIn("critiques", result["transcript"])
        self.assertIn("revisions", result["transcript"])


# ---------------------------------------------------------------------------
# 4. jobs.py — uses mongomock if available, otherwise skips Mongo tests
# ---------------------------------------------------------------------------

try:
    import mongomock  # type: ignore

    _MONGOMOCK_AVAILABLE = True
except ImportError:
    _MONGOMOCK_AVAILABLE = False


@unittest.skipUnless(_MONGOMOCK_AVAILABLE, "mongomock not installed")
class TestJobsWithMongomock(unittest.TestCase):
    def setUp(self):
        import src.dev_converge.jobs as jobs_module

        self._jobs = jobs_module
        # Patch the collection to use mongomock
        patcher = mongomock.patch(servers=(("mongo", 27017),))
        patcher.start()
        self.addCleanup(patcher.stop)
        # Reset module-level connection cache
        jobs_module._client = None
        jobs_module._collection = None

    def test_create_job_no_api_key_in_doc(self):
        redacted = [
            {
                "name": "kimi",
                "provider": "openai_compatible",
                "model": "kimi-k2.5",
                "base_url": "https://example.com",
            }
        ]
        record = self._jobs.create_job("run_panel", {"task": "test"}, "ops", redacted)
        job_id = record["job_id"]
        doc = self._jobs.collection().find_one({"job_id": job_id})
        self.assertIsNotNone(doc)
        # api_key must not appear anywhere in the stored document
        doc_str = json.dumps(doc, default=str)
        self.assertNotIn("api_key", doc_str)

    def test_create_job_agents_field_redacted(self):
        redacted = [
            {
                "name": "kimi",
                "provider": "openai_compatible",
                "model": "kimi-k2.5",
                "base_url": "",
            }
        ]
        record = self._jobs.create_job("run_panel", {"task": "t"}, "ops", redacted)
        job_id = record["job_id"]
        doc = self._jobs.collection().find_one({"job_id": job_id})
        self.assertEqual(doc["agents"][0]["name"], "kimi")
        self.assertNotIn("api_key", doc["agents"][0])

    def test_mark_running_as_failed(self):
        redacted: list = []
        r1 = self._jobs.create_job("run_panel", {}, "ops", redacted)
        r2 = self._jobs.create_job("swarm_panel", {}, "ops", redacted)
        # manually set one to running
        self._jobs.collection().update_one(
            {"job_id": r1["job_id"]}, {"$set": {"status": "running"}}
        )
        count = self._jobs.mark_running_as_failed("test_restart")
        self.assertEqual(count, 2)  # queued + running both marked failed
        for rec in [r1, r2]:
            doc = self._jobs.collection().find_one({"job_id": rec["job_id"]})
            self.assertEqual(doc["status"], "failed")
            self.assertIn("test_restart", doc["error"])

    def test_complete_job_stores_artifact(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.dev_converge.jobs.settings") as mock_settings:
                mock_settings.data_root = Path(tmpdir)
                mock_settings.DEV_CONVERGE_JOB_RETENTION_HOURS = 168
                redacted: list = []
                record = self._jobs.create_job("run_panel", {}, "ops", redacted)
                job_id = record["job_id"]
                self._jobs.complete_job(job_id, {"result": "done"})
                doc = self._jobs.collection().find_one({"job_id": job_id})
                self.assertEqual(doc["status"], "succeeded")
                artifact = doc["artifact_paths"]["result"]
                self.assertTrue(Path(artifact).exists())


# ---------------------------------------------------------------------------
# 5. auth wrapper (ASGI-level)
# ---------------------------------------------------------------------------


class TestAuthWrapper(unittest.IsolatedAsyncioTestCase):
    def _make_scope(self, headers: dict[bytes, bytes]) -> dict:
        return {
            "type": "http",
            "headers": list(headers.items()),
            "path": "/mcp/sse",
        }

    async def _call_wrapper(self, scope, wrapper):
        responses: list[dict] = []

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            responses.append(message)

        await wrapper(scope, receive, send)
        return responses

    def _build_wrapper(self, token: str = "secret"):
        from src.dev_converge.mcp_server import _auth_wrapper

        inner = AsyncMock()
        inner.side_effect = lambda scope, receive, send: send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        with patch("src.dev_converge.mcp_server.settings") as mock_settings:
            mock_settings.api_tokens = {"secret": "ops"}
            mock_settings.DEV_CONVERGE_SYNC_TIMEOUT_SEC = 90
            mock_settings.allowed_hosts = []
            mock_settings.DEV_CONVERGE_SITE_URL = "https://converge.gabidou.top"
            wrapper = _auth_wrapper(inner)
        return wrapper, inner, mock_settings

    async def test_missing_token_returns_401(self):
        from src.dev_converge.mcp_server import _auth_wrapper

        inner = AsyncMock()
        responses: list = []

        async def send(msg):
            responses.append(msg)

        with patch("src.dev_converge.mcp_server.settings") as s:
            s.api_tokens = {"secret": "ops"}
            wrapper = _auth_wrapper(inner)
            scope = self._make_scope({})
            await wrapper(scope, AsyncMock(), send)

        status = next(
            (r["status"] for r in responses if r.get("type") == "http.response.start"),
            None,
        )
        self.assertEqual(status, 401)

    async def test_invalid_token_returns_401(self):
        from src.dev_converge.mcp_server import _auth_wrapper

        responses: list = []

        async def send(msg):
            responses.append(msg)

        with patch("src.dev_converge.mcp_server.settings") as s:
            s.api_tokens = {"secret": "ops"}
            wrapper = _auth_wrapper(AsyncMock())
            scope = self._make_scope({b"authorization": b"Bearer wrong-token"})
            await wrapper(scope, AsyncMock(), send)

        status = next(
            (r["status"] for r in responses if r.get("type") == "http.response.start"),
            None,
        )
        self.assertEqual(status, 401)

    async def test_valid_token_passes_through(self):
        from src.dev_converge.mcp_server import _auth_wrapper

        responses: list = []

        async def send(msg):
            responses.append(msg)

        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        with patch("src.dev_converge.mcp_server.settings") as s:
            s.api_tokens = {"secret": "ops"}
            wrapper = _auth_wrapper(inner)
            scope = self._make_scope({b"authorization": b"Bearer secret"})
            await wrapper(scope, AsyncMock(), send)

        status = next(
            (r["status"] for r in responses if r.get("type") == "http.response.start"),
            None,
        )
        self.assertEqual(status, 200)

    async def test_malformed_agents_header_returns_422(self):
        from src.dev_converge.mcp_server import _auth_wrapper

        responses: list = []

        async def send(msg):
            responses.append(msg)

        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        with patch("src.dev_converge.mcp_server.settings") as s:
            s.api_tokens = {}
            wrapper = _auth_wrapper(inner)
            scope = self._make_scope({b"x-dev-converge-agents": b"not-valid-base64!!!"})
            await wrapper(scope, AsyncMock(), send)

        status = next(
            (r["status"] for r in responses if r.get("type") == "http.response.start"),
            None,
        )
        self.assertEqual(status, 422)

    async def test_valid_agents_header_decoded(self):
        from src.dev_converge.mcp_server import _auth_wrapper, current_catalog

        captured_catalog: list = []

        async def inner(scope, receive, send):
            captured_catalog.extend(current_catalog())
            await send({"type": "http.response.start", "status": 200, "headers": []})

        with patch("src.dev_converge.mcp_server.settings") as s:
            s.api_tokens = {}
            wrapper = _auth_wrapper(inner)
            header = _make_catalog_header([KIMI_AGENT])
            scope = self._make_scope({b"x-dev-converge-agents": header.encode()})
            await wrapper(scope, AsyncMock(), AsyncMock())

        self.assertEqual(len(captured_catalog), 1)
        self.assertEqual(captured_catalog[0].name, "kimi")


# ---------------------------------------------------------------------------
# Fallback runner (no pytest)
# ---------------------------------------------------------------------------


def _run_all_tests() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestBuildAgent,
        TestDecodeCatalog,
        TestGetDefaultSynthesizer,
        TestResolveAgents,
        TestRedactCatalog,
        TestProviderHTTPCalls,
        TestExecutorGetDefaults,
        TestExecutorCompleteOnce,
        TestExecutorPanels,
        TestAuthWrapper,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    if _MONGOMOCK_AVAILABLE:
        suite.addTests(loader.loadTestsFromTestCase(TestJobsWithMongomock))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(_run_all_tests())
