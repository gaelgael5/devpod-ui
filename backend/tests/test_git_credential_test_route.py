# backend/tests/test_git_credential_test_route.py
"""Tests de POST /me/git-credentials/{name}/test (unitaires, sans DB/app complète)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


def _cfg(creds: list[object]):
    from portal.config.models import UserConfig

    return UserConfig.model_validate(
        {
            "version": "1",
            "secret_ns": "a3f8c1d2-4b56-7890-abcd-ef1234567890",
            "git_credentials": creds,
        }
    )


def _user():
    from portal.auth.rbac import UserInfo

    return UserInfo(login="alice", roles=["dev"])


@pytest.mark.asyncio
async def test_returns_404_when_credential_missing() -> None:
    from portal.routes.me import test_git_credential_connection

    with (
        patch("portal.routes.me.load_user", new=AsyncMock(return_value=_cfg([]))),
        pytest.raises(HTTPException) as exc_info,
    ):
        await test_git_credential_connection("ghost", user=_user())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_returns_ok_true_on_successful_probe() -> None:
    from portal.config.models import GitCredential
    from portal.routes.me import test_git_credential_connection

    cred = GitCredential(name="gh", host="github.com", kind="ssh", key_path="/data/k")
    with (
        patch("portal.routes.me.load_user", new=AsyncMock(return_value=_cfg([cred]))),
        patch(
            "portal.routes.me.probe_git_credential",
            new=AsyncMock(return_value=(True, "remote: Repository not found.")),
        ) as mock_probe,
    ):
        res = await test_git_credential_connection("gh", user=_user())

    assert res == {"ok": True, "message": "remote: Repository not found."}
    mock_probe.assert_awaited_once_with("gh", "github.com", "alice")


@pytest.mark.asyncio
async def test_returns_ok_false_on_failed_probe() -> None:
    from portal.config.models import GitCredential
    from portal.routes.me import test_git_credential_connection

    cred = GitCredential(name="gh", host="github.com", kind="ssh", key_path="/data/k")
    with (
        patch("portal.routes.me.load_user", new=AsyncMock(return_value=_cfg([cred]))),
        patch(
            "portal.routes.me.probe_git_credential",
            new=AsyncMock(return_value=(False, "Permission denied (publickey).")),
        ),
    ):
        res = await test_git_credential_connection("gh", user=_user())

    assert res == {"ok": False, "message": "Permission denied (publickey)."}
