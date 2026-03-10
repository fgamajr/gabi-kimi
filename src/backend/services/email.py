"""Email sending abstraction. Implementations (Resend, SMTP, etc.) in separate modules."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmailSender(ABC):
    """Interface for sending transactional email. Config from env, not hardcoded."""

    @abstractmethod
    async def send(self, to: str, subject: str, html_body: str) -> bool:
        """Send an email. Returns True on success, False on failure (e.g. provider error)."""
        ...
