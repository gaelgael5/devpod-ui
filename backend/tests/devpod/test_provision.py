# backend/tests/devpod/test_provision.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.devpod import provision


@pytest.mark.asyncio
async def test_provision_workspace_calls_up(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = SimpleNamespace(up=AsyncMock(return_value="alice-dev"))
    monkeypatch.setattr(provision, "_get_service", lambda: svc)
    monkeypatch.setattr(provision, "_resolve_recipes_and_secrets", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(provision, "_load_profile", AsyncMock(return_value=None))
    params = provision.ProvisionParams(name="dev", source="git@x/y.git", recipes=[])
    ws_id = await provision.provision_workspace("alice", params, conn=None)
    assert ws_id == "alice-dev"
    # Assert svc.up was called with the expected mapped kwargs
    svc.up.assert_awaited_once()
    call_kwargs = svc.up.call_args.kwargs
    assert call_kwargs["login"] == "alice"
    assert call_kwargs["recipes"] is None          # [] → None
    assert call_kwargs["feature_env"] is None      # {} → None
    assert call_kwargs["generate_ssh_key"] is False
    assert call_kwargs["request_host"] == ""
    assert call_kwargs["profile"] is None


@pytest.mark.asyncio
async def test_provision_secret_failure_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretResolutionError doit masquer le message brut de l'exception originale."""
    import sys

    # Build a minimal recipe stub with one secret ref so the resolution branch is hit
    secret_ref = SimpleNamespace(env="MY_TOKEN", path="token/path")
    recipe_stub = SimpleNamespace(requires_secrets=[secret_ref])

    # The raw secret value that must NEVER appear in the raised exception message
    raw_secret_value = "super-secret-value"

    # Patch asyncio.to_thread so _resolve_feature_secrets raises with the raw value
    async def _evil_to_thread(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(raw_secret_value)

    monkeypatch.setattr(provision.asyncio, "to_thread", _evil_to_thread)

    # Stub load_user (imported at call time inside _resolve_recipes_and_secrets)
    user_cfg_stub = SimpleNamespace(secret_ns="ns-alice")

    async def _fake_load_user(login: str):  # type: ignore[no-untyped-def]
        return user_cfg_stub

    store_mod = sys.modules.get("portal.config.store")
    if store_mod is None:
        import portal.config.store as _store_mod

        store_mod = _store_mod
    monkeypatch.setattr(store_mod, "load_user", _fake_load_user)

    # Patch registry helpers (imported from workspace_ops at call time)
    ops_mod = sys.modules.get("portal.routes.workspace_ops")
    if ops_mod is None:
        import portal.routes.workspace_ops as _ops_mod

        ops_mod = _ops_mod

    def _fake_registry():  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            expand_with_deps=lambda ids, avail: ids,
            resolve_order=lambda expanded, avail: [recipe_stub],
        )

    def _fake_available(db: dict) -> dict:  # type: ignore[type-arg]
        return db

    monkeypatch.setattr(ops_mod, "_get_recipe_registry", _fake_registry)
    monkeypatch.setattr(ops_mod, "_available_with_bundled_fallback", _fake_available)

    async def _fake_load_recipes_as_dict(login, conn):  # type: ignore[no-untyped-def]
        return {}

    db_mod = sys.modules.get("portal.db.recipes")
    if db_mod is None:
        import portal.db.recipes as _db_mod

        db_mod = _db_mod
    monkeypatch.setattr(db_mod, "load_recipes_as_dict", _fake_load_recipes_as_dict)

    with pytest.raises(provision.SecretResolutionError) as exc_info:
        await provision._resolve_recipes_and_secrets("alice", ["some-recipe"], conn=None)

    err_str = str(exc_info.value)
    assert "Secret resolution failed: RuntimeError" in err_str
    assert raw_secret_value not in err_str, (
        f"Raw secret value leaked into exception message: {err_str!r}"
    )
