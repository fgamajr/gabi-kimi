from __future__ import annotations

from datetime import date

import httpx
import pytest

from src.backend.worker.inlabs_client import (
    COOKIE_NAME,
    DOWNLOAD_URL,
    INLabsClient,
    InlabsWindowError,
    MAX_LOOKBACK_DAYS,
)


class DummyResponse:
    def raise_for_status(self) -> None:
        return None


class DummyClient:
    def __init__(self) -> None:
        self.cookies = httpx.Cookies()
        self.last_post: dict[str, object] | None = None

    async def post(self, url: str, data: dict[str, str], headers: dict[str, str]) -> DummyResponse:
        self.last_post = {"url": url, "data": data, "headers": headers}
        self.cookies.set(COOKIE_NAME, "session-123")
        return DummyResponse()


def test_supports_recent_dates_inside_30_day_window() -> None:
    today = date(2026, 3, 9)
    publication_date = date(2026, 2, 7)
    assert (today - publication_date).days == MAX_LOOKBACK_DAYS
    assert INLabsClient.supports_date(publication_date, today=today) is True


def test_rejects_historical_dates_outside_30_day_window() -> None:
    with pytest.raises(InlabsWindowError):
        INLabsClient.build_target(
            date(2026, 1, 31),
            "DO1",
            today=date(2026, 3, 9),
        )


def test_build_target_uses_official_inlabs_url_shape() -> None:
    target = INLabsClient.build_target(
        date(2026, 3, 9),
        "do1e",
        today=date(2026, 3, 9),
    )
    assert target.filename == "2026-03-09-DO1E.zip"
    assert target.url == f"{DOWNLOAD_URL}?p=2026-03-09&dl=2026-03-09-DO1E.zip"


@pytest.mark.asyncio
async def test_login_extracts_session_cookie_from_client() -> None:
    client = DummyClient()
    inlabs = INLabsClient("fernando@example.com", "secret", client=client)  # type: ignore[arg-type]

    cookie = await inlabs.login()

    assert cookie == "session-123"
    assert client.last_post is not None
    assert client.last_post["data"] == {
        "email": "fernando@example.com",
        "password": "secret",
    }
