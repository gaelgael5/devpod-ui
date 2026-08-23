"""Utilisateur SSH d'un workspace (`image_user` du profil) — source de vérité unique.

Les façades d'exécution codaient `vscode` en dur alors que le composant
`ssh-access` pose `authorized_keys` dans le foyer d'`image_user` et restreint
`AllowUsers` à lui : tout le post-readiness (primitives MCP, sondes tmux, clone
des sources, config des agents) visait le mauvais compte sur un profil à image
personnalisée.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from portal.devpod import ws_user as mod


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    mod.clear_cache()


def test_default_is_devcontainer_base_user() -> None:
    assert mod.DEFAULT_WS_USER == "vscode"


@pytest.mark.asyncio
async def test_resolver_is_fail_safe() -> None:
    """Une base indisponible ne doit pas casser une exécution : repli sur le
    défaut historique, jamais une exception qui remonterait dans ws_exec."""
    with patch(
        "portal.db.engine._get_engine", side_effect=RuntimeError("db down")
    ):
        assert await mod.resolve_ws_user("alice", "alice-proj") == mod.DEFAULT_WS_USER


@pytest.mark.asyncio
async def test_cache_avoids_repeated_db_reads() -> None:
    """ws_exec est appelé en rafale (sondes TTL 4 s + ~25 primitives MCP) : une
    lecture de profil par appel serait une régression de perf."""
    calls = 0

    async def _fake(login: str, ws_id: str, conn: object) -> str:
        nonlocal calls
        calls += 1
        return "devuser"

    class _Conn:
        async def __aenter__(self) -> _Conn:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    class _Engine:
        def connect(self) -> _Conn:
            return _Conn()

    with (
        patch("portal.db.engine._get_engine", return_value=_Engine()),
        patch.object(mod, "resolve_ws_user_db", _fake),
    ):
        first = await mod.resolve_ws_user("alice", "alice-proj")
        second = await mod.resolve_ws_user("alice", "alice-proj")

    assert first == second == "devuser"
    assert calls == 1  # le second appel sort du cache

    # invalidate() force une relecture (profil changé au `up`).
    mod.invalidate("alice-proj")
    with (
        patch("portal.db.engine._get_engine", return_value=_Engine()),
        patch.object(mod, "resolve_ws_user_db", _fake),
    ):
        await mod.resolve_ws_user("alice", "alice-proj")
    assert calls == 2


def test_ws_name_strips_login_prefix() -> None:
    assert mod._ws_name("alice", "alice-proj") == "proj"
    assert mod._ws_name("alice", "autre-proj") == "autre-proj"  # pas le préfixe
