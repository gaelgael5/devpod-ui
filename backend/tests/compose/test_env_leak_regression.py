"""Régression bug 002 — fuite de secrets du portail via env_values compose.

Un utilisateur `dev` pouvait exfiltrer n'importe quelle variable du process portail
(PORTAL_VAULT_KEK, SESSION_SECRET_KEY, OIDC_CLIENT_SECRET…) via
``env_values: {"LEAK": "${env://PORTAL_VAULT_KEK}"}`` dans POST /compose/deployments.

Défense en profondeur vérifiée ici (sans DB / sans Docker) :
  1. le résolveur user-facing refuse toute référence ``env://`` ;
  2. ``_SECRET_REF_RE`` côté compose n'accepte plus que ``vault://`` ;
  3. ``env_values`` est filtré aux seules clés déclarées par le template (rejet).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.compose import service
from portal.compose.models import ComposeParam, ComposeTemplate
from portal.compose.service import ComposeServiceError
from portal.secrets.resolver import Scope, SecretAccessError, resolve
from portal.secrets.types import Secret

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
USER_SCOPE = Scope(kind="user", secret_ns=USER_NS, login="alice")


def _backend(return_value: str = "resolved"):
    from unittest.mock import MagicMock

    from portal.secrets.backends.base import SecretsBackend

    b = MagicMock(spec=SecretsBackend)  # type: ignore[arg-type]
    b.get.return_value = return_value
    b.base_path = "devpod"
    return b


def _tpl_secret() -> ComposeTemplate:
    return ComposeTemplate(
        id="svc", name="Svc", version="1",
        compose_content="services:\n  s:\n    image: x:1",
        parameters=[ComposeParam(key="TOKEN", label="Token", type="secret", required=True)],
        source="user",
    )


def _tpl_port() -> ComposeTemplate:
    return ComposeTemplate(
        id="svc", name="Svc", version="1",
        compose_content='services:\n  s:\n    image: x:1\n    ports: ["${PORT}:3000"]',
        parameters=[ComposeParam(key="PORT", label="Port", type="port", required=True)],
        source="user",
    )


# --- Couche 1 : résolveur user-facing refuse env:// -------------------------

def test_resolver_rejects_env_ref_and_does_not_read_process_env(monkeypatch) -> None:
    monkeypatch.setenv("PORTAL_VAULT_KEK", "kek-super-secret")
    b = _backend()
    with pytest.raises(SecretAccessError, match="env://"):
        resolve("${env://PORTAL_VAULT_KEK}", USER_SCOPE, b)
    b.get.assert_not_called()


def test_resolver_still_resolves_vault_ref() -> None:
    b = _backend("real_secret")
    result = resolve("${vault://git/token}", USER_SCOPE, b)
    b.get.assert_called_once_with(f"devpod/{USER_NS}/git/token")
    assert isinstance(result, Secret)
    assert result.reveal() == "real_secret"


# --- Couche 2 : _SECRET_REF_RE compose n'accepte que vault:// ---------------

def test_validate_secret_refs_rejects_env_ref() -> None:
    tpl = _tpl_secret()
    with pytest.raises(ComposeServiceError, match="vault://"):
        service._validate_secret_refs(tpl, {"TOKEN": "${env://PORTAL_VAULT_KEK}"})


def test_validate_secret_refs_accepts_vault_ref() -> None:
    tpl = _tpl_secret()
    # ne doit pas lever
    service._validate_secret_refs(tpl, {"TOKEN": "${vault://git/token}"})


# --- Couche 3 : env_values filtré aux clés déclarées ------------------------

def test_foreign_env_keys_flags_undeclared() -> None:
    tpl = _tpl_port()
    assert service.foreign_env_keys(tpl, {"PORT": "3000", "LEAK": "x"}) == ["LEAK"]
    assert service.foreign_env_keys(tpl, {"PORT": "3000"}) == []


@pytest.mark.asyncio
async def test_deploy_rejects_foreign_env_key(monkeypatch) -> None:
    host = SimpleNamespace(name="n1", type="ssh", address="root@x")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    resolve_spy = AsyncMock()
    monkeypatch.setattr(service, "resolve_env_values", lambda *a, **k: resolve_spy())
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(0, "", "")))

    with pytest.raises(ComposeServiceError, match="non déclarées"):
        await service.deploy(
            None, name="dep1", template=_tpl_port(), node_id="n1",
            owner_login="alice", secret_ns=USER_NS,
            env_values={"PORT": "3000", "LEAK": "${env://PORTAL_VAULT_KEK}"},
        )
    # La résolution ne doit jamais être atteinte pour une clé étrangère.
    resolve_spy.assert_not_called()
    service.write_host_file.assert_not_awaited()
