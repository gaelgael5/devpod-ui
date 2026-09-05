"""Socle IaC — invocation d'OpenTofu (ticket 8).

Une stack **par machine** : le nom de la machine est le workspace OpenTofu
(backend `pg`, base du portail). Le state fait autorité sur l'infrastructure,
la base du portail sur le métier — le portail ne stocke qu'une référence.

Aucun secret ne touche le disque ni l'argv :

- la chaîne de connexion Postgres passe par `PG_CONN_STR` (env du process
  enfant uniquement) ;
- la passphrase de chiffrement du state passe par `TF_ENCRYPTION` (env), un
  bloc HCL complet — pbkdf2 → AES-GCM, `enforced` : un state en clair est
  refusé en lecture comme en écriture ;
- les credentials providers arrivent résolus (références `${vault://...}`
  déballées par l'appelant) et partent en env du process enfant ;
- les variables passent en `TF_VAR_*` (env), jamais en `-var` (argv lisible
  dans `ps`).

La séparation plan/apply n'est pas cosmétique : un échec de **plan** n'a rien
créé (`EchecAvantCreation`), un échec d'**apply** s'arbitre sur le state — des
ressources présentes = machine partiellement créée (`EchecApresCreation`,
`provider_ref = {"stack": ...}`), un state vide = rien derrière
(`EchecAvantCreation`), un state illisible = `Indetermine`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path
from typing import Any

import structlog

from .errors import (
    DriverError,
    EchecApresCreation,
    EchecAvantCreation,
    Indetermine,
)

_log = structlog.get_logger(__name__)

_TIMEOUT_DEFAULT_S = 1800.0

# Modèle du bloc TF_ENCRYPTION : pbkdf2 (>= 16 caractères) → AES-GCM, imposé
# au state ET aux plans. `enforced = true` interdit la relecture d'un state en
# clair : le chiffrement n'est pas une option qu'un oubli peut désactiver.
_ENCRYPTION_HCL = """
key_provider "pbkdf2" "portal" {{
  passphrase = "{passphrase}"
}}
method "aes_gcm" "portal" {{
  keys = key_provider.pbkdf2.portal
}}
state {{
  method   = method.aes_gcm.portal
  enforced = true
}}
plan {{
  method   = method.aes_gcm.portal
  enforced = true
}}
"""

# En conditions nominales, AUCUN téléchargement : le miroir local est la seule
# source (`direct` exclu). Un miroir incomplet échoue fort et tôt — mieux qu'un
# init qui télécharge en silence et casse le jour où le réseau manque.
_CLI_CONFIG_MIRROR = """
provider_installation {{
  filesystem_mirror {{
    path    = "{mirror}"
    include = ["*/*"]
  }}
  direct {{
    exclude = ["*/*"]
  }}
}}
"""


class TofuError(DriverError):
    """Échec d'OpenTofu, phase en clair dans le message."""


class TofuStack:
    """Une stack = un répertoire de module + un workspace nommé (la machine).

    `pg_conn_str` et `state_passphrase` sont des secrets déjà résolus ;
    `secret_env` porte les credentials providers (ex. `PROXMOX_VE_API_TOKEN`).
    Le timeout est une propriété du module appelant : un `qm clone` et un
    apply Azure n'ont pas le même horizon.
    """

    def __init__(
        self,
        *,
        workdir: Path,
        stack: str,
        pg_conn_str: str,
        state_passphrase: str,
        binary: str = "tofu",
        provider_mirror: Path | None = None,
        secret_env: dict[str, str] | None = None,
        timeout_s: float = _TIMEOUT_DEFAULT_S,
    ) -> None:
        if len(state_passphrase) < 16:
            raise ValueError("passphrase de chiffrement du state : 16 caractères minimum")
        self._workdir = workdir
        self._stack = stack
        self._pg_conn_str = pg_conn_str
        self._passphrase = state_passphrase
        self._binary = binary
        self._provider_mirror = provider_mirror
        self._secret_env = dict(secret_env or {})
        self._timeout_s = timeout_s

    # ─── Cycle de vie ────────────────────────────────────────────────────────

    async def provision(self, variables: dict[str, Any]) -> dict[str, Any]:
        """init → plan → apply → outputs. Les échecs sortent déjà classés."""
        await self._init()
        plan_file = "portal.tfplan"
        rc, _out, err = await self._run(
            "plan", "-input=false", f"-out={plan_file}", variables=variables
        )
        if rc != 0:
            # Un plan n'agit pas : rien n'existe, rejouable à l'identique.
            raise EchecAvantCreation(f"tofu plan ({self._stack}) : {_diagnostics(err)}")
        rc, _out, err = await self._run(
            "apply", "-input=false", "-json", plan_file, variables=variables
        )
        if rc != 0:
            raise await self._classer_echec_apply(err)
        return await self.outputs()

    async def destroy(self, variables: dict[str, Any]) -> None:
        await self._init()
        rc, _out, err = await self._run(
            "destroy", "-input=false", "-auto-approve", "-json", variables=variables
        )
        if rc != 0:
            raise TofuError(f"tofu destroy ({self._stack}) : {_diagnostics(err)}")

    async def outputs(self) -> dict[str, Any]:
        rc, out, err = await self._run("output", "-json")
        if rc != 0:
            raise TofuError(f"tofu output ({self._stack}) : {_diagnostics(err)}")
        brut = json.loads(out or "{}")
        return {k: v.get("value") for k, v in brut.items()}

    async def resources_in_state(self) -> list[str]:
        """Adresses présentes dans le state — vide = rien n'a été créé."""
        rc, out, err = await self._run("state", "list")
        if rc != 0:
            # Un state absent (workspace jamais appliqué) n'est pas une erreur.
            if "No state file" in err or "does not exist" in err:
                return []
            raise TofuError(f"tofu state list ({self._stack}) : {_diagnostics(err)}")
        return [ligne for ligne in out.splitlines() if ligne.strip()]

    async def import_resource(self, address: str, resource_id: str) -> None:
        """Procédure « state perdu » : réadopter une ressource existante pour
        que la machine redevienne destructible par le portail."""
        await self._init()
        rc, _out, err = await self._run("import", "-input=false", address, resource_id)
        if rc != 0:
            raise TofuError(f"tofu import ({self._stack}) : {_diagnostics(err)}")

    # ─── Mécanique ───────────────────────────────────────────────────────────

    async def _init(self) -> None:
        # L'init se fait HORS workspace : TF_WORKSPACE pointant sur un
        # workspace encore inexistant fait échouer `init` (vérifié v1.10).
        # `select -or-create` crée ensuite la stack au premier passage.
        rc, _out, err = await self._run("init", "-input=false", "-no-color", workspace=False)
        if rc != 0:
            raise EchecAvantCreation(f"tofu init ({self._stack}) : {_diagnostics(err)}")
        rc, _out, err = await self._run(
            "workspace", "select", "-or-create=true", self._stack, workspace=False
        )
        if rc != 0:
            raise EchecAvantCreation(f"tofu workspace select ({self._stack}) : {_diagnostics(err)}")

    async def _classer_echec_apply(self, err: str) -> DriverError:
        """Après un apply en échec, le state dit ce qu'il reste derrière."""
        try:
            restes = await self.resources_in_state()
        except TofuError as exc:
            return Indetermine(
                f"tofu apply ({self._stack}) en échec ET state illisible — issue inconnue : {exc}"
            )
        if restes:
            return EchecApresCreation(
                f"tofu apply ({self._stack}) : machine partiellement créée "
                f"({len(restes)} ressource(s) en state) — {_diagnostics(err)}",
                provider_ref={"stack": self._stack, "resources": restes},
            )
        return EchecAvantCreation(
            f"tofu apply ({self._stack}) : rien de créé — {_diagnostics(err)}"
        )

    def _env(
        self, variables: dict[str, Any] | None = None, *, workspace: bool = True
    ) -> dict[str, str]:
        env = {
            # PATH minimal : tofu appelle ses providers, rien d'autre.
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),  # noqa: S108 — plugins cache par défaut
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "PG_CONN_STR": self._pg_conn_str,
            "TF_ENCRYPTION": _ENCRYPTION_HCL.format(passphrase=self._passphrase),
        }
        if workspace:
            env["TF_WORKSPACE"] = self._stack
        if self._provider_mirror is not None:
            config = self._workdir / ".portal-cli.tfrc"
            config.write_text(_CLI_CONFIG_MIRROR.format(mirror=self._provider_mirror))
            env["TF_CLI_CONFIG_FILE"] = str(config)
        for nom, valeur in (variables or {}).items():
            env[f"TF_VAR_{nom}"] = valeur if isinstance(valeur, str) else json.dumps(valeur)
        env.update(self._secret_env)
        return env

    async def _run(
        self,
        *args: str,
        variables: dict[str, Any] | None = None,
        workspace: bool = True,
    ) -> tuple[int | None, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self._binary,
            *args,
            cwd=self._workdir,
            env=self._env(variables, workspace=workspace),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_s)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            await proc.wait()
            raise Indetermine(
                f"tofu {args[0]} ({self._stack}) : délai dépassé "
                f"({self._timeout_s:.0f}s) — issue inconnue"
            ) from None
        _log.info(
            "tofu_run",
            stack=self._stack,
            command=args[0],
            rc=proc.returncode,
        )
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _diagnostics(err: str) -> str:
    """Condense la sortie d'erreur : lignes de diagnostic `-json` si présentes,
    sinon la fin brute. Un wrapper qui remonte « rc=1 » est inutilisable."""
    messages: list[str] = []
    for ligne in err.splitlines():
        ligne = ligne.strip()
        if not ligne.startswith("{"):
            continue
        try:
            evt = json.loads(ligne)
        except ValueError:
            continue
        if evt.get("@level") == "error" or evt.get("severity") == "error":
            messages.append(str(evt.get("@message") or evt.get("summary") or ""))
    if messages:
        return " ; ".join(m for m in messages if m)[:800]
    return err.strip()[-800:] or "<stderr vide>"
