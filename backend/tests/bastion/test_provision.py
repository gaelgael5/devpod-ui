"""Provision bastion (mode automates) : gating de config strict + erreurs propagées.

Le provisioning n'est plus best-effort : config incomplète → BastionNotConfiguredError
(l'endpoint service la traduit en 409, le run de l'automate est visible et rejouable).
"""

from __future__ import annotations

import pytest

from portal.bastion import provision as p
from portal.config.models import BastionConfig


class _Cfg:
    def __init__(self, b: BastionConfig) -> None:
        self.bastion = b


def _use(monkeypatch: pytest.MonkeyPatch, b: BastionConfig) -> None:
    monkeypatch.setattr(p, "load_global", lambda: _Cfg(b))


class _OidcTx:
    def __init__(self, cfg: dict | None) -> None:
        self._cfg = cfg

    async def get_oidc_config(self) -> dict | None:
        return self._cfg


@pytest.mark.asyncio
async def test_oidc_mapping_warning_when_name_path_not_email() -> None:
    """SSO configuré avec name_path≠email → les comptes OIDC Termix ont un username
    qui n'est PAS l'email → jamais matchés par `find_user_ids(email)` → aucun host
    poussé sur le compte que l'utilisateur voit. Détection + message actionnable."""
    warn = await p._oidc_mapping_warning(_OidcTx({"client_id": "termix", "name_path": "name"}))
    assert warn is not None and "name_path" in warn and "email" in warn


@pytest.mark.asyncio
async def test_oidc_mapping_no_warning_when_email_or_unconfigured() -> None:
    assert (
        await p._oidc_mapping_warning(_OidcTx({"client_id": "termix", "name_path": "email"}))
    ) is None
    assert await p._oidc_mapping_warning(_OidcTx(None)) is None  # pas de SSO → rien
    assert await p._oidc_mapping_warning(_OidcTx({"name_path": "name"})) is None  # sans client_id


@pytest.mark.asyncio
async def test_oidc_mapping_warning_swallows_errors() -> None:
    class _Boom:
        async def get_oidc_config(self) -> dict | None:
            raise RuntimeError("Termix GET /users/oidc-config/admin → 500")

    assert await p._oidc_mapping_warning(_Boom()) is None  # best-effort


def test_enabled_is_master_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    # Spec 18 T5 (Modèle B) : le gating est le seul toggle `enabled` ; api_url/
    # host/role de BastionConfig sont vestigiaux (instance résolue par le registre).
    _use(monkeypatch, BastionConfig(enabled=False))
    assert p.enabled() is False
    _use(monkeypatch, BastionConfig(enabled=True))
    assert p.enabled() is True


@pytest.mark.asyncio
async def test_provision_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, BastionConfig(enabled=False))
    with pytest.raises(p.BastionNotConfiguredError):
        await p.provision_workspace("admin", "admin-doc")


@pytest.mark.asyncio
async def test_deprovision_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, BastionConfig(enabled=False))
    with pytest.raises(p.BastionNotConfiguredError):
        await p.deprovision_workspace("admin", "admin-doc")


def test_node_ip_strips_user(monkeypatch: pytest.MonkeyPatch) -> None:
    class _H:
        address = "root@192.168.10.5"

    monkeypatch.setattr(p, "load_global", lambda: object())
    monkeypatch.setattr(p, "_find_host", lambda name, cfg: _H())
    assert p._node_ip("node1") == "192.168.10.5"

    class _H2:
        address = "10.0.0.2"

    monkeypatch.setattr(p, "_find_host", lambda name, cfg: _H2())
    assert p._node_ip("node1") == "10.0.0.2"


class _FakeTx:
    """Faux TermixClient : enregistre create/delete, host_ids configurable."""

    def __init__(self, host_ids: list[int] | None = None) -> None:
        self.host_ids = host_ids
        self.created: list[tuple] = []
        self.deleted: list[tuple] = []

    async def list_host_ids(self) -> list[int] | None:
        return self.host_ids

    async def list_hosts(self) -> list[dict]:
        return []

    async def create_credential(self, name: str, user: str, priv: str) -> int:
        self.created.append(("cred", name, user))
        return 100

    async def create_host(
        self, name: str, ip: str, port: int, user: str, cred: int, folder: str | None = None
    ) -> int:
        self.created.append(("host", ip, port, user, cred, folder))
        return 200

    async def delete_host(self, hid: int) -> None:
        self.deleted.append(("host", hid))

    async def delete_credential(self, cid: int) -> None:
        self.deleted.append(("cred", cid))


@pytest.mark.asyncio
async def test_ensure_host_creates_when_no_prev() -> None:
    tx = _FakeTx()
    rec = await p._ensure_host_on_instance(
        tx,  # type: ignore[arg-type]
        "admin-doc",
        "PK",
        "1.2.3.4",
        50001,
        "vscode",
        None,
        folder="workspace-agflow",
    )
    assert rec == {
        "host_id": 200,
        "cred_id": 100,
        "ip": "1.2.3.4",
        "port": 50001,
        "user": "vscode",
        "owner": None,
        "folder": "workspace-agflow",
    }
    assert tx.created[0][0] == "cred" and tx.created[1][0] == "host"
    assert tx.created[1][-1] == "workspace-agflow"  # folder transmis à create_host
    assert tx.deleted == []


@pytest.mark.asyncio
async def test_ensure_host_keeps_when_unchanged() -> None:
    prev = {"host_id": 200, "cred_id": 100, "ip": "1.2.3.4", "port": 50001, "user": "vscode"}
    tx = _FakeTx(host_ids=[200])  # host toujours présent
    rec = await p._ensure_host_on_instance(tx, "admin-doc", "PK", "1.2.3.4", 50001, "vscode", prev)  # type: ignore[arg-type]
    assert rec == prev
    assert tx.created == [] and tx.deleted == []


@pytest.mark.asyncio
async def test_ensure_host_recreates_when_target_changed() -> None:
    prev = {"host_id": 200, "cred_id": 100, "ip": "1.2.3.4", "port": 50001, "user": "vscode"}
    tx = _FakeTx(host_ids=[200])
    rec = await p._ensure_host_on_instance(tx, "admin-doc", "PK", "9.9.9.9", 50001, "vscode", prev)  # type: ignore[arg-type]
    assert rec["ip"] == "9.9.9.9" and rec["host_id"] == 200
    assert ("host", 200) in tx.deleted and ("cred", 100) in tx.deleted


@pytest.mark.asyncio
async def test_ensure_host_recreates_when_lost() -> None:
    prev = {"host_id": 200, "cred_id": 100, "ip": "1.2.3.4", "port": 50001, "user": "vscode"}
    tx = _FakeTx(host_ids=[])  # host disparu côté Termix
    rec = await p._ensure_host_on_instance(tx, "admin-doc", "PK", "1.2.3.4", 50001, "vscode", prev)  # type: ignore[arg-type]
    assert rec["host_id"] == 200  # recréé (le fake renvoie 200)
    assert ("host", 200) in tx.deleted


@pytest.mark.asyncio
async def test_ensure_host_keeps_when_same_owner() -> None:
    prev = {
        "host_id": 200,
        "cred_id": 100,
        "ip": "1.2.3.4",
        "port": 50001,
        "user": "vscode",
        "owner": "oidc-uid",
    }
    tx = _FakeTx(host_ids=[200])
    rec = await p._ensure_host_on_instance(
        tx,  # type: ignore[arg-type]
        "admin-doc",
        "PK",
        "1.2.3.4",
        50001,
        "vscode",
        prev,
        owner="oidc-uid",
    )
    assert rec == prev
    assert tx.created == [] and tx.deleted == []


@pytest.mark.asyncio
async def test_ensure_host_recreates_when_owner_changed() -> None:
    # Ré-appropriation : le host passe du compte placeholder au compte OIDC → recréé.
    prev = {
        "host_id": 200,
        "cred_id": 100,
        "ip": "1.2.3.4",
        "port": 50001,
        "user": "vscode",
        "owner": "old-uid",
    }
    tx = _FakeTx(host_ids=[200])
    rec = await p._ensure_host_on_instance(
        tx,  # type: ignore[arg-type]
        "admin-doc",
        "PK",
        "1.2.3.4",
        50001,
        "vscode",
        prev,
        owner="oidc-uid",
    )
    assert rec["owner"] == "oidc-uid" and rec["host_id"] == 200
    assert ("host", 200) in tx.deleted and ("cred", 100) in tx.deleted


def test_reconcile_orphans_removed() -> None:
    # Le mode « réconciliation au boot » n'existe plus : le journal durable
    # (workspace.deleted écrit dans la transaction de la mutation) + le curseur
    # des automates garantissent la délivrance, même portail down.
    assert not hasattr(p, "reconcile_orphans")
