"""Spec 35b T4′ — livraison des fichiers agents PAR ÉCRITURE dans le conteneur.

Révision de la spec 35 §4.3 : la livraison ne passe plus par un bind mount (qui ne
s'attache qu'à la construction du conteneur, imposant un recreate), mais par une
écriture directe via le canal `container_files` (`devpod ssh`). Conséquence : un
simple `restart` du workspace suffit à (ré)installer la config des agents.

Un seul chemin unifie les deux modes :
- `replace` (Claude, Cursor…) : le template rend le fichier complet → écrit tel quel ;
- `merge` (Codex, Gemini) : le template rend un fragment `portal-*` → fusionné dans
  le fichier existant du conteneur (réglages utilisateur préservés).
"""

from __future__ import annotations

from typing import Any

import structlog

from ..devpod.exec import ws_exec
from .container_files import read_container_file, write_container_file
from .keys import WorkspaceKey, rotate_workspace_keys
from .merge import Format, merge_config
from .provisioning import AgentProvisionError, _load_requested_agent_types
from .renderer import AgentRenderError, build_render_context, render_agent_file
from .sync_state import compute_agent_fingerprint

_log = structlog.get_logger(__name__)

# Le target rendu est interpolé dans le shell postCreate du .git/info/exclude (entre
# double quotes) : on interdit tout métacaractère susceptible d'en sortir. `home`
# étant résolu en chemin concret, aucun `$` légitime ne subsiste.
_FORBIDDEN = set("\"'`;\\\n$")


async def push_agent_files(
    *,
    login: str,
    ws_id: str,
    ws_name: str,
    agents: list[str],
    mcp_url: str,
    project_root: str,
    home: str | None = None,
) -> list[str]:
    """Rend et écrit la config de chaque agent dans le conteneur. Retourne les ids
    effectivement poussés. Appelé en hook post-readiness du `up` (T5′) et par le
    resync à chaud (T6). Lève `AgentProvisionError` en cas d'agent invalide ou de
    config manquante (external_url)."""
    if not mcp_url.startswith(("https://", "http://")):
        raise AgentProvisionError(
            "server.external_url doit être configurée pour exposer la gateway MCP "
            f"aux agents workspace (url calculée : {mcp_url!r})"
        )
    agent_rows = await _load_requested_agent_types(agents)
    if not agent_rows:
        return []

    resolved_home = home if home is not None else await resolve_container_home(login, ws_id)
    ws_meta = {"id": ws_id, "name": ws_name, "owner": login}
    # Cibles calculées AVANT toute rotation (le target ne dépend pas du token).
    targets = [_resolve_target(row, project_root, resolved_home, ws_meta) for row in agent_rows]

    # Empreinte de la config rendue (hors token/home). Si elle est identique à la
    # dernière livrée ET que les fichiers sont toujours dans le conteneur, on ne
    # rotationne pas les clefs et on ne réécrit rien : l'agent en cours garde son
    # token (plus de ré-auth gratuite au boot/reconnexion du portail — spec 35b).
    # Fichiers absents (conteneur recréé) ou empreinte différente → livraison.
    fingerprint = compute_agent_fingerprint(
        agent_rows=agent_rows,
        profiles=await _exposed_profiles(login),
        mcp_url=mcp_url,
        project_root=project_root,
        ws_name=ws_name,
        owner=login,
        ws_id=ws_id,
    )
    stored = await _stored_config_hash(login, ws_id)
    if stored == fingerprint and await _targets_present(login, ws_id, targets):
        _log.info("agent_files_unchanged", ws_id=ws_id, agents=[str(r["id"]) for r in agent_rows])
        return []

    keys = await _rotate_keys(login, ws_id)
    context = build_render_context(
        keys=keys,
        mcp_url=mcp_url,
        ws_id=ws_id,
        workspace_name=ws_name,
        owner_login=login,
        home=resolved_home,
        project_root=project_root,
    )

    written: list[str] = []
    for row, target in zip(agent_rows, targets, strict=True):
        content = _render(row, context)
        if str(row["mode"]) == "merge":
            fmt, servers_key = _merge_params(target)
            existing = await read_container_file(login, ws_id, target)
            content = merge_config(existing, content, fmt=fmt, servers_key=servers_key)
        await write_container_file(login, ws_id, target, content)
        if target.startswith(f"{project_root}/"):
            await _git_exclude(login, ws_id, project_root, target)
        written.append(str(row["id"]))

    await _record_config_hash(login, ws_id, fingerprint)
    _log.info("agent_files_pushed", ws_id=ws_id, agents=written)
    return written


async def _exposed_profiles(login: str) -> list[tuple[str, str]]:
    """Profils (id, nom) exposés aux workspaces — entrée de l'empreinte. Mockable."""
    from ..db.engine import _get_engine
    from ..db.mcp_profiles import list_exposed_profiles

    async with _get_engine().connect() as conn:
        return [(str(p["id"]), str(p["name"])) for p in await list_exposed_profiles(conn, login)]


async def _stored_config_hash(login: str, ws_id: str) -> str | None:
    """Empreinte de la dernière livraison (None si jamais livré). Mockable."""
    from ..db.agent_sync import get_config_hash
    from ..db.engine import _get_engine

    async with _get_engine().connect() as conn:
        return await get_config_hash(conn, ws_id)


async def _targets_present(login: str, ws_id: str, targets: list[str]) -> bool:
    """True si TOUS les fichiers cibles existent dans le conteneur (sinon → livraison).

    Discrimine un conteneur recréé (fichiers perdus → livrer) d'une simple
    reconnexion (fichiers présents → skip possible). Une seule commande shell.
    """
    if not targets:
        return True
    import shlex

    test = " && ".join(f"test -f {shlex.quote(t)}" for t in targets)
    rc, _out = await ws_exec(login, ws_id, test)
    return rc == 0


async def _record_config_hash(login: str, ws_id: str, fingerprint: str) -> None:
    """Persiste l'empreinte livrée (isolé pour être mockable en test)."""
    from ..db.agent_sync import upsert_config_hash
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        await upsert_config_hash(conn, ws_id, fingerprint)


async def _rotate_keys(login: str, ws_id: str) -> list[WorkspaceKey]:
    """Rotation systématique des clefs workspace (les tokens ne vivent qu'ici, en
    clair, le temps du rendu). Isolé pour être mockable en test."""
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        return await rotate_workspace_keys(conn, login, ws_id)


async def resolve_container_home(login: str, ws_id: str) -> str:
    """`$HOME` réel du conteneur (l'image décide son remoteUser). Sert aussi de
    sonde de readiness avant l'écriture des fichiers."""
    rc, out = await ws_exec(login, ws_id, 'printf %s "$HOME"')
    home = out.strip()
    if rc != 0 or not home.startswith("/"):
        raise AgentProvisionError(f"home du conteneur introuvable (rc={rc})")
    return home


def _render(row: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        return render_agent_file(str(row["template"]), context)
    except AgentRenderError as exc:
        raise AgentProvisionError(f"agent '{row['id']}' : {exc}") from exc


def _resolve_target(
    row: dict[str, Any], project_root: str, home: str, ws_meta: dict[str, str]
) -> str:
    try:
        target = render_agent_file(
            str(row["target_path"]),
            {"home": home, "project_root": project_root, "workspace": ws_meta},
        )
    except AgentRenderError as exc:
        raise AgentProvisionError(f"agent '{row['id']}' : target_path — {exc}") from exc
    if not target.startswith("/"):
        raise AgentProvisionError(
            f"agent '{row['id']}' : target_path doit être absolu ({target!r})"
        )
    if ".." in target.split("/") or _FORBIDDEN & set(target):
        raise AgentProvisionError(f"agent '{row['id']}' : target_path rendu invalide ({target!r})")
    return target


def _merge_params(target: str) -> tuple[Format, str]:
    """Format et clé de tête déduits de l'extension (spec 35b D2 : clé conventionnelle)."""
    if target.endswith(".toml"):
        return "toml", "mcp_servers"
    return "json", "mcpServers"


async def _git_exclude(login: str, ws_id: str, project_root: str, target: str) -> None:
    """Ajoute le fichier au `.git/info/exclude` du clone (jamais le .gitignore versionné)."""
    rel = "/" + target.removeprefix(f"{project_root}/")
    exclude = f"{project_root}/.git/info/exclude"
    cmd = (
        f'if [ -d "{project_root}/.git" ]; then '
        f'mkdir -p "{project_root}/.git/info" && '
        f'{{ grep -qxF "{rel}" "{exclude}" 2>/dev/null || '
        f'printf \'%s\\n\' "{rel}" >> "{exclude}"; }}; fi'
    )
    await ws_exec(login, ws_id, cmd)
