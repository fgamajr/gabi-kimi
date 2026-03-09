"""INLABS client for recent DOU ZIP downloads.

This mirrors the official login/download flow from the Imprensa Nacional
repository, while making the 30-day retention rule explicit in code so the
worker never attempts historical backfills through INLABS.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

LOGIN_URL = "https://inlabs.in.gov.br/logar.php"
DOWNLOAD_URL = "https://inlabs.in.gov.br/index.php"
COOKIE_NAME = "inlabs_session_cookie"
ORIGIN_HEADER = "736372697074"
MAX_LOOKBACK_DAYS = 30
VALID_SECTIONS = frozenset({"DO1", "DO2", "DO3", "DO1E", "DO2E", "DO3E"})


class InlabsWindowError(ValueError):
    """Raised when a requested publication is outside the INLABS window."""


@dataclass(slots=True)
class InlabsDownloadTarget:
    publication_date: date
    section: str
    filename: str
    url: str


class INLabsClient:
    """Async client wrapping the official INLABS auth + ZIP download flow."""

    def __init__(
        self,
        email: str,
        password: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.email = email
        self.password = password
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=60, follow_redirects=True)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    @staticmethod
    def supports_date(publication_date: date, *, today: date | None = None) -> bool:
        reference = today or datetime.now(UTC).date()
        delta_days = (reference - publication_date).days
        return 0 <= delta_days <= MAX_LOOKBACK_DAYS

    @staticmethod
    def build_target(
        publication_date: date,
        section: str,
        *,
        today: date | None = None,
    ) -> InlabsDownloadTarget:
        normalized_section = section.upper()
        if normalized_section not in VALID_SECTIONS:
            raise ValueError(f"Unsupported INLABS section: {section}")
        if not INLabsClient.supports_date(publication_date, today=today):
            raise InlabsWindowError(
                "INLABS only serves the last 30 days; use Liferay/catalog for older data"
            )

        day = publication_date.isoformat()
        filename = f"{day}-{normalized_section}.zip"
        return InlabsDownloadTarget(
            publication_date=publication_date,
            section=normalized_section,
            filename=filename,
            url=f"{DOWNLOAD_URL}?p={day}&dl={filename}",
        )

    async def login(self) -> str:
        response = await self.client.post(
            LOGIN_URL,
            data={"email": self.email, "password": self.password},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        response.raise_for_status()
        cookie = self.client.cookies.get(COOKIE_NAME)
        if not cookie:
            raise RuntimeError("INLABS login did not yield a session cookie")
        return cookie

    def build_download_headers(self) -> dict[str, str]:
        cookie = self.client.cookies.get(COOKIE_NAME)
        if not cookie:
            raise RuntimeError("INLABS session cookie missing; call login() first")
        return {
            "Cookie": f"{COOKIE_NAME}={cookie}",
            "origem": ORIGIN_HEADER,
        }

    async def download(
        self,
        publication_date: date,
        section: str,
        destination: Path,
        *,
        today: date | None = None,
    ) -> InlabsDownloadTarget:
        target = self.build_target(publication_date, section, today=today)
        if not self.client.cookies.get(COOKIE_NAME):
            await self.login()

        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self.client.stream(
            "GET",
            target.url,
            headers=self.build_download_headers(),
        ) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    handle.write(chunk)
        return target
