"""Resend.com implementation of EmailSender. Requires RESEND_API_KEY and RESEND_FROM (e.g. 'GABI Search <noreply@yourdomain.com>')."""

from __future__ import annotations

import os

import httpx

from src.backend.services.email import EmailSender


class ResendEmailSender(EmailSender):
    """Send email via Resend API. Config from env: RESEND_API_KEY, RESEND_FROM."""

    def __init__(self) -> None:
        self._api_key = (os.getenv("RESEND_API_KEY") or "").strip()
        self._from = (os.getenv("RESEND_FROM") or "GABI Search <onboarding@resend.dev>").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def send(self, to: str, subject: str, html_body: str) -> bool:
        if not self._api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": self._from,
                        "to": [to.strip()],
                        "subject": subject,
                        "html": html_body,
                    },
                )
                return 200 <= r.status_code < 300
        except Exception:
            return False


def get_email_sender() -> EmailSender:
    """Return the configured EmailSender (Resend if RESEND_API_KEY set)."""
    sender = ResendEmailSender()
    if sender.is_configured:
        return sender
    # Fallback: no-op sender so register flow doesn't break when key is missing
    return _NoOpEmailSender()


class _NoOpEmailSender(EmailSender):
    """No-op when no provider is configured (e.g. local dev without RESEND_API_KEY)."""

    async def send(self, to: str, subject: str, html_body: str) -> bool:
        return False
