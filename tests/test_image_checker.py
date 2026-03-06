"""Unit tests for image classification and fallback metadata.

Run:
    python3 tests/test_image_checker.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.backend.ingest.image_checker import build_fallback_text, infer_context_hint
from src.backend.ingest.image_checker import _probe_remote_image


_passed = 0
_failed = 0


def _assert(condition: bool, msg: str) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f"FAIL: {msg}", file=sys.stderr)


def _response(method: str, url: str, status_code: int, *, headers: dict[str, str] | None = None, content: bytes = b""):
    return httpx.Response(
        status_code,
        headers=headers,
        content=content,
        request=httpx.Request(method, url),
    )


class FakeClient:
    def __init__(self, head_items: list[object], get_items: list[object] | None = None) -> None:
        self.head_items = list(head_items)
        self.get_items = list(get_items or [])

    async def head(self, url: str, follow_redirects: bool = False):
        item = self.head_items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url: str, follow_redirects: bool = True):
        item = self.get_items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def test_available_status() -> None:
    client = FakeClient(
        head_items=[
            _response("HEAD", "https://example.com/img.gif", 200, headers={"content-type": "image/gif"}),
        ],
        get_items=[
            _response("GET", "https://example.com/img.gif", 200, headers={"content-type": "image/gif"}, content=b"GIF89a"),
        ],
    )
    out = await _probe_remote_image(client, "https://example.com/img.gif")
    _assert(out["status"] == "available", "200 image/* classified as available")
    _assert(out["media_type"] == "image/gif", "keeps image media type")
    _assert(out["size_bytes"] == 6, "captures payload size")


async def test_missing_status() -> None:
    client = FakeClient([
        _response("HEAD", "https://example.com/missing.gif", 404),
    ])
    out = await _probe_remote_image(client, "https://example.com/missing.gif")
    _assert(out["status"] == "missing", "404 classified as missing")


async def test_redirected_status() -> None:
    client = FakeClient([
        _response("HEAD", "https://www.in.gov.br/images/test.gif", 302, headers={"location": "https://www.in.gov.br/"}),
    ])
    out = await _probe_remote_image(client, "https://www.in.gov.br/images/test.gif")
    _assert(out["status"] == "missing", "redirect to generic page treated as missing")


async def test_blocked_status() -> None:
    client = FakeClient([
        _response("HEAD", "https://example.com/blocked.gif", 403),
    ])
    out = await _probe_remote_image(client, "https://example.com/blocked.gif")
    _assert(out["status"] == "unknown", "403 classified as unknown")


async def test_timeout_status() -> None:
    client = FakeClient([
        httpx.TimeoutException("timeout"),
    ])
    out = await _probe_remote_image(client, "https://example.com/slow.gif")
    _assert(out["status"] == "missing", "timeout classified as missing")


def test_context_hint_and_fallback_text() -> None:
    hint = infer_context_hint("0214_tabela1.gif", None, "conforme tabela abaixo")
    _assert(hint == "table", "infers table from filename/context")
    _assert(
        build_fallback_text("table") == "Tabela disponível apenas no documento original",
        "uses table fallback copy",
    )


async def _run_async() -> None:
    await test_available_status()
    await test_missing_status()
    await test_redirected_status()
    await test_blocked_status()
    await test_timeout_status()


def main() -> int:
    asyncio.run(_run_async())
    test_context_hint_and_fallback_text()
    print(f"{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
