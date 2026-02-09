"""Unit tests for token revocation policy behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from gabi.auth.token_revocation import TokenRevocationList
from gabi.config import settings
from gabi.exceptions import AuthenticationError
from gabi.types import Environment


@pytest.mark.asyncio
async def test_is_user_revoked_fail_open_in_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local env should fail-open when revocation backend is unavailable."""
    monkeypatch.setattr(settings, "auth_fail_closed", False)
    monkeypatch.setattr(settings, "environment", Environment.LOCAL)

    revocation = TokenRevocationList()
    with patch.object(revocation, "_get_redis", AsyncMock(side_effect=RuntimeError("redis down"))):
        result = await revocation.is_user_revoked("user-1", datetime.now(timezone.utc))
    assert result is False


@pytest.mark.asyncio
async def test_is_user_revoked_fail_closed_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed config should raise AuthenticationError on backend failure."""
    monkeypatch.setattr(settings, "auth_fail_closed", True)
    monkeypatch.setattr(settings, "environment", Environment.LOCAL)

    revocation = TokenRevocationList()
    with patch.object(revocation, "_get_redis", AsyncMock(side_effect=RuntimeError("redis down"))):
        with pytest.raises(AuthenticationError):
            await revocation.is_user_revoked("user-1", datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_is_user_revoked_fail_closed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production should fail-closed even when auth_fail_closed is false."""
    monkeypatch.setattr(settings, "auth_fail_closed", False)
    monkeypatch.setattr(settings, "environment", Environment.PRODUCTION)

    revocation = TokenRevocationList()
    with patch.object(revocation, "_get_redis", AsyncMock(side_effect=RuntimeError("redis down"))):
        with pytest.raises(AuthenticationError):
            await revocation.is_user_revoked("user-1", datetime.now(timezone.utc))
