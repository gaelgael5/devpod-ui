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


def test_enabled_requires_full_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, BastionConfig(enabled=False))
    assert p.enabled() is False  # désactivé
    _use(monkeypatch, BastionConfig(enabled=True, api_url="https://x", host="1.2.3.4"))
    assert p.enabled() is False  # role manquant
    _use(
        monkeypatch,
        BastionConfig(enabled=True, api_url="https://x", host="1.2.3.4", role="devpod-users"),
    )
    assert p.enabled() is True


@pytest.mark.asyncio
async def test_provision_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, BastionConfig(enabled=False))
    with pytest.raises(p.BastionNotConfiguredError):
        await p.provision_workspace("admin", "admin-doc")


@pytest.mark.asyncio
async def test_deprovision_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, BastionConfig(enabled=True, api_url="https://x", host="", role="r"))
    with pytest.raises(p.BastionNotConfiguredError):
        await p.deprovision_workspace("admin", "admin-doc")


def test_reconcile_orphans_removed() -> None:
    # Le mode « réconciliation au boot » n'existe plus : le journal durable
    # (workspace.deleted écrit dans la transaction de la mutation) + le curseur
    # des automates garantissent la délivrance, même portail down.
    assert not hasattr(p, "reconcile_orphans")
