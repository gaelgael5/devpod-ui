"""Rendu Jinja sandboxé des fichiers de configuration agents (spec 35).

Les templates sont saisis par l'admin et rendus avec des tokens en contexte :
le sandbox Jinja est obligatoire (pas d'accès aux attributs Python), et les
messages d'erreur ne contiennent jamais de valeur de token (seulement des noms
de variables/attributs).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from .keys import WorkspaceKey


class AgentRenderError(Exception):
    pass


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9_-]+")

# autoescape=False : on génère du JSON/TOML, pas du HTML — les templates
# échappent eux-mêmes via | tojson. StrictUndefined : variable inconnue = erreur.
_env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


def _slugify(name: str) -> str:
    """Nom de serveur MCP sûr pour les clients (clé de mcpServers).

    Les accents sont TRANSLITTÉRÉS avant le nettoyage (« Défaut » → `defaut`),
    pas traités comme des séparateurs (`d-faut`) : la clé doit rester lisible,
    et surtout STABLE — le merge purge puis repose les serveurs `portal-*` par
    nom, une clé qui varie selon la fonction de slugification changerait
    d'identité au premier passage.
    """
    decompose = unicodedata.normalize("NFKD", name)
    ascii_seulement = decompose.encode("ascii", "ignore").decode("ascii")
    return _SLUG_STRIP_RE.sub("-", ascii_seulement.lower()).strip("-")


def build_render_context(
    *,
    keys: list[WorkspaceKey],
    mcp_url: str,
    ws_id: str,
    workspace_name: str,
    owner_login: str,
    home: str,
    project_root: str,
) -> dict[str, Any]:
    """Contexte canonique passé aux templates (contrat : spec 35 §4.1)."""
    servers: list[dict[str, str]] = []
    used: set[str] = set()
    for key in keys:
        base = _slugify(key.profile_name) or key.profile_id
        slug, i = base, 2
        while slug in used:
            slug, i = f"{base}-{i}", i + 1
        used.add(slug)
        servers.append({"name": slug, "url": mcp_url, "token": key.token})
    return {
        "servers": servers,
        "workspace": {"id": ws_id, "name": workspace_name, "owner": owner_login},
        "home": home,
        "project_root": project_root,
    }


def render_agent_file(template: str, context: dict[str, Any]) -> str:
    try:
        return _env.from_string(template).render(**context)
    except Exception as exc:
        # Message d'origine préservé (noms de variables/attributs uniquement,
        # jamais de valeurs) — utile pour l'éditeur de template côté admin.
        raise AgentRenderError(f"rendu du template impossible : {exc}") from exc
