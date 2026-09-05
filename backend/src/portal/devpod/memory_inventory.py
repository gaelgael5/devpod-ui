"""Inventaire mémoire du parc existant face au plafond des nœuds.

Filet de la migration `max_memory` (enabler « Migration des workspaces existants
vers le plafond mémoire du nœud ») : lister, pour l'exploitant, les workspaces
dont la limite effective dépasse le plafond de leur host — en comptant les
`memory_limit` vides sur un host qui déclare un plafond, invisibles d'un simple
filtre « au-dessus du plafond ».

La borne réelle se produit au `up()` (voir `service.py`) ; cet inventaire ne
touche rien, il rend visible ce qui sera ramené au prochain démarrage/recreate.
"""

from __future__ import annotations

from typing import Any

from ..config.store import load_global, load_user
from ..db.engine import _get_engine
from ..db.workspace_status import list_all_status_db

# Un conteneur dans l'un de ces états tourne encore sur la valeur de son dernier
# build : la borne ne le rattrape qu'au prochain démarrage/recreate demandé.
_EN_COURS = frozenset({"running", "up"})


def _nom_workspace(ws_id: str, login: str) -> str:
    """ws_id = `<login>-<name>` ; renvoie le nom court, ws_id tel quel sinon."""
    prefixe = f"{login}-"
    return ws_id[len(prefixe) :] if ws_id.startswith(prefixe) else ws_id


async def inventaire_memoire() -> list[dict[str, Any]]:
    """Workspaces dont la limite effective sera ramenée au plafond de leur host.

    Chaque entrée : `login`, `workspace`, `host`, `demande` (valeur effective
    injectée aujourd'hui — surcharge du workspace, sinon défaut global),
    `plafond` du nœud, `applique` (valeur bornée), `en_cours` (le conteneur
    tourne-t-il encore sur l'ancienne valeur). Trié pour une lecture stable.
    """
    from ..config.models import borner_memoire

    global_cfg = load_global()
    plafonds = {h.name: h.max_memory for h in global_cfg.hosts}
    defaut = global_cfg.devpod.defaults.memory_limit

    async with _get_engine().connect() as conn:
        rows = await list_all_status_db(conn)

    par_login: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        par_login.setdefault(r.get("login") or "", []).append(r)

    resultat: list[dict[str, Any]] = []
    for login, statuts in par_login.items():
        if not login:
            continue
        cfg = await load_user(login)
        specs = {ws.name: ws for ws in cfg.workspaces}
        for r in statuts:
            name = _nom_workspace(r["ws_id"], login)
            spec = specs.get(name)
            host_name = r.get("host_name") or (spec.host if spec else "")
            plafond = plafonds.get(host_name, "")
            if not plafond:
                continue
            demande = ((spec.memory_limit if spec else "") or defaut).strip()
            applique = borner_memoire(demande, plafond)
            if applique == demande:
                continue  # conforme : rien à signaler
            resultat.append(
                {
                    "login": login,
                    "workspace": name,
                    "host": host_name,
                    "demande": demande,
                    "plafond": plafond,
                    "applique": applique,
                    "en_cours": (r.get("status") or "") in _EN_COURS,
                }
            )

    resultat.sort(key=lambda e: (e["host"], e["login"], e["workspace"]))
    return resultat
