"""Provision bastion : détection d'orphelins + gating de config (sans DB/Termix)."""

from __future__ import annotations

import pytest

from portal.bastion import provision as p


def test_orphan_ws_ids() -> None:
    valid = {"admin-doc", "admin-rag"}
    slugs = [
        "ws-bastion-admin-doc",  # valide
        "ws-bastion-admin-old",  # orphelin (workspace supprimé)
        "termix-apikey",  # secret hors périmètre → ignoré
        "ws-bastion-gael-ghost",  # orphelin
    ]
    assert set(p._orphan_ws_ids(valid, slugs)) == {"admin-old", "gael-ghost"}


def test_orphan_ws_ids_empty_valid_flags_all() -> None:
    # Aucun workspace connu → tous les états bastion sont orphelins.
    assert p._orphan_ws_ids(set(), ["ws-bastion-a", "ws-bastion-b"]) == ["a", "b"]


def test_enabled_requires_full_config(monkeypatch: pytest.MonkeyPatch) -> None:
    class _S:
        termix_api_url = ""
        termix_bastion_host = ""
        termix_role = ""

    monkeypatch.setattr(p, "get_settings", lambda: _S())
    assert p.enabled() is False  # config incomplète → provisioning inactif

    _S.termix_api_url = "https://termix.yoops.org"
    _S.termix_bastion_host = "192.168.10.164"
    _S.termix_role = "devpod-users"
    assert p.enabled() is True


@pytest.mark.asyncio
async def test_provision_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p, "enabled", lambda: False)
    # Ne doit rien tenter (ni DB, ni Termix) — juste retourner.
    await p.provision_workspace("admin", "admin-doc")
    await p.deprovision_workspace("admin", "admin-doc")
    assert await p.reconcile_orphans() == 0
