# backend/tests/test_provisioning_tofu.py
"""Socle IaC (ticket 8) : couche d'invocation OpenTofu.

Deux niveaux :
- unitaire (toujours joué) : classification des échecs, garde-fous ;
- intégration (j1oué si `tofu` est disponible ET TEST_DATABASE_URL posé) :
  cycle complet contre le backend pg réel, avec LA vérification de la DoD —
  un state lu brut en base est illisible.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

from portal.provisioning.errors import (
    EchecApresCreation,
    EchecAvantCreation,
    Indetermine,
)
from portal.provisioning.tofu import TofuError, TofuStack

_TOFU = os.environ.get("TOFU_BIN") or shutil.which("tofu") or ""
_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

integration = pytest.mark.skipif(
    not (_TOFU and _DB_URL),
    reason="binaire tofu et TEST_DATABASE_URL requis pour l'intégration pg",
)

_MODULE_OK = """
terraform {
  backend "pg" {}
}
variable "marker" { type = string }
resource "terraform_data" "machine" { input = var.marker }
output "echo" { value = terraform_data.machine.input }
"""

# La validation de variable échoue AU PLAN (config valide, valeur refusée) :
# rien n'est créé — le cas echec_avant_creation.
_MODULE_PLAN_KO = """
terraform {
  backend "pg" {}
}
variable "marker" {
  type = string
  validation {
    condition     = length(var.marker) > 100
    error_message = "marqueur trop court — échec de plan volontaire"
  }
}
resource "terraform_data" "machine" { input = var.marker }
"""


def _conn_str() -> str:
    # TEST_DATABASE_URL est en dialecte SQLAlchemy ; tofu veut du libpq.
    return _DB_URL.replace("postgresql+asyncpg://", "postgres://") + "?sslmode=disable"


def _stack(tmp_path: Path, module: str, **over: object) -> TofuStack:
    (tmp_path / "main.tf").write_text(module)
    params: dict[str, object] = {
        "workdir": tmp_path,
        "stack": f"test-{uuid.uuid4().hex[:12]}",
        "pg_conn_str": _conn_str() if _DB_URL else "postgres://invalide/x",
        "state_passphrase": "passphrase-de-test-0123456789",
        "binary": _TOFU or "tofu",
        "timeout_s": 300.0,
    }
    params.update(over)
    return TofuStack(**params)  # type: ignore[arg-type]


# ─── Unitaire ─────────────────────────────────────────────────────────────────


def test_passphrase_trop_courte_refusee(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _stack(tmp_path, _MODULE_OK, state_passphrase="court")


async def test_apply_en_echec_avec_state_est_apres_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Des ressources en state après un apply raté = machine partiellement
    créée : provider_ref porte la stack, la reprise ou la destruction est
    possible."""
    stack = _stack(tmp_path, _MODULE_OK)

    async def _restes() -> list[str]:
        return ["terraform_data.machine"]

    monkeypatch.setattr(stack, "resources_in_state", _restes)
    exc = await stack._classer_echec_apply("boom")
    assert isinstance(exc, EchecApresCreation)
    assert exc.provider_ref["stack"] == stack._stack


async def test_apply_en_echec_sans_state_est_avant_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = _stack(tmp_path, _MODULE_OK)

    async def _rien() -> list[str]:
        return []

    monkeypatch.setattr(stack, "resources_in_state", _rien)
    assert isinstance(await stack._classer_echec_apply("boom"), EchecAvantCreation)


async def test_apply_en_echec_state_illisible_est_indetermine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = _stack(tmp_path, _MODULE_OK)

    async def _casse() -> list[str]:
        raise TofuError("decryption failed")

    monkeypatch.setattr(stack, "resources_in_state", _casse)
    assert isinstance(await stack._classer_echec_apply("boom"), Indetermine)


def test_les_secrets_ne_passent_jamais_en_argv(tmp_path: Path) -> None:
    """Contrat : conn_str, passphrase, credentials et variables partent en
    environnement du process enfant — jamais en argv (lisible dans ps)."""
    stack = _stack(tmp_path, _MODULE_OK, secret_env={"PROXMOX_VE_API_TOKEN": "tok"})
    env = stack._env({"marker": "val", "complexe": {"a": 1}})
    assert env["PG_CONN_STR"].startswith("postgres://")
    assert "passphrase-de-test" in env["TF_ENCRYPTION"]
    assert env["TF_VAR_marker"] == "val"
    assert env["TF_VAR_complexe"] == '{"a": 1}'
    assert env["PROXMOX_VE_API_TOKEN"] == "tok"
    assert env["TF_WORKSPACE"] == stack._stack


def test_miroir_de_providers_exclut_le_telechargement(tmp_path: Path) -> None:
    stack = _stack(tmp_path, _MODULE_OK, provider_mirror=Path("/data/tofu/mirror"))
    env = stack._env()
    config = Path(env["TF_CLI_CONFIG_FILE"]).read_text()
    assert 'path    = "/data/tofu/mirror"' in config
    assert "direct" in config and 'exclude = ["*/*"]' in config


# ─── Intégration (tofu réel + backend pg réel) ───────────────────────────────


@integration
async def test_cycle_complet_et_state_illisible_en_base(tmp_path: Path) -> None:
    """DoD du ticket 8 : provision/destroy bout-en-bout sans secret sur disque,
    chiffrement actif VÉRIFIÉ — le state lu brut en base ne contient pas le
    marqueur en clair."""
    import asyncpg

    stack = _stack(tmp_path, _MODULE_OK)
    marker = f"SECRET-{uuid.uuid4().hex}"

    outputs = await stack.provision({"marker": marker})
    assert outputs["echo"] == marker
    assert await stack.resources_in_state() == ["terraform_data.machine"]

    # Aucun secret sur disque dans le répertoire de travail.
    for fichier in tmp_path.rglob("*"):
        if fichier.is_file() and fichier.suffix != ".tfplan":
            assert marker not in fichier.read_text(errors="ignore"), fichier

    conn = await asyncpg.connect(_DB_URL.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        data = await conn.fetchval(
            "SELECT data FROM terraform_remote_state.states WHERE name = $1",
            stack._stack,
        )
    finally:
        await conn.close()
    assert data is not None
    assert marker not in data
    assert "encrypted_data" in data

    await stack.destroy({"marker": marker})
    assert await stack.resources_in_state() == []


@integration
async def test_echec_de_plan_ne_cree_rien(tmp_path: Path) -> None:
    stack = _stack(tmp_path, _MODULE_PLAN_KO)
    with pytest.raises(EchecAvantCreation):
        await stack.provision({"marker": "x"})
    assert await stack.resources_in_state() == []
