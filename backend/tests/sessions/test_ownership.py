from __future__ import annotations

import pytest

from portal.auth.rbac import UsernameError
from portal.sessions.ownership import OwnershipDenied, resolve_owner


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings par défaut (admin_role='admin') isolés entre cas."""
    monkeypatch.delenv("OIDC_ADMIN_ROLE", raising=False)
    import portal.settings as mod

    mod._settings = None
    yield
    mod._settings = None


def test_resolve_owner_defaults_to_caller_when_owner_absent() -> None:
    assert resolve_owner(login="alice", roles=["dev"], owner=None) == "alice"


def test_resolve_owner_defaults_to_caller_when_owner_equals_login() -> None:
    # Même un non-admin peut se cibler lui-même explicitement.
    assert resolve_owner(login="alice", roles=["dev"], owner="alice") == "alice"


def test_resolve_owner_admin_can_target_other_user() -> None:
    assert resolve_owner(login="root", roles=["admin"], owner="bob") == "bob"


def test_resolve_owner_non_admin_targeting_other_is_denied() -> None:
    with pytest.raises(OwnershipDenied):
        resolve_owner(login="alice", roles=["dev"], owner="bob")


def test_resolve_owner_admin_targeting_invalid_login_is_rejected() -> None:
    with pytest.raises(UsernameError):
        resolve_owner(login="root", roles=["admin"], owner="bad!name")
