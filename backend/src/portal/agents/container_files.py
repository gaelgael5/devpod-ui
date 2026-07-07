"""Spec 35b T3 — canal fichier conteneur (read/write atomique via `ws_exec`).

Le mode `merge` traite un fichier de config qui vit DANS le conteneur (avec des
réglages utilisateur) : on ne peut ni le lire ni le réécrire côté host. Ce module
donne au portail un couple lire/écrire s'appuyant sur la façade `ws_exec`
(`devpod ssh --stdio`, canal réseau + mTLS déjà en place — jamais de SSH ad hoc).

Le contenu traverse le shell distant **encodé en base64** : aucun quoting fragile,
aucune corruption sur les octets non-ASCII, aucune fuite du contenu en clair dans
la ligne de commande. L'écriture est atomique (`base64 -d > tmp && chmod 600 && mv`,
`mkdir -p` du parent) : un conteneur qui lit le fichier ne voit jamais un état
partiel.
"""

from __future__ import annotations

import base64
import shlex
import uuid

from ..devpod.exec import ws_exec

# Sentinelle d'absence : `NOFILE` fait 6 caractères, or toute sortie `base64`
# est padée à un multiple de 4 — la collision avec un vrai contenu est impossible.
_ABSENT = "NOFILE"


class ContainerFileError(Exception):
    """Lecture ou écriture impossible dans le conteneur (canal ou droits)."""


async def read_container_file(
    login: str, ws_id: str, path: str, *, timeout: float = 30.0
) -> str | None:
    """Lit `path` dans le conteneur. Retourne `None` si le fichier est absent.

    Distingue « absent » (→ `None`) de « présent mais vide » (→ `""`) : le merge
    crée le fichier dans le premier cas, préserve les réglages dans le second.
    Toute autre erreur (droits, canal) lève `ContainerFileError` — l'appelant ne
    doit jamais écraser un fichier qu'il n'a pas pu lire.
    """
    q = shlex.quote(path)
    command = f"if [ -e {q} ]; then base64 -- {q}; else echo {_ABSENT}; fi"
    rc, output = await ws_exec(login, ws_id, command, timeout=timeout)
    if rc != 0:
        raise ContainerFileError(f"lecture de {path!r} échouée (rc={rc}): {output}")
    if output == _ABSENT:
        return None
    try:
        return base64.b64decode(output, validate=True).decode()
    except Exception as exc:  # sortie non-base64 = canal cassé, pas un fichier valide
        raise ContainerFileError(f"sortie illisible pour {path!r}: {type(exc).__name__}") from exc


async def write_container_file(
    login: str, ws_id: str, path: str, content: str, *, timeout: float = 30.0
) -> None:
    """Écrit atomiquement `content` dans `path` (crée le parent, perms 600)."""
    encoded = base64.b64encode(content.encode()).decode()
    q_path = shlex.quote(path)
    q_tmp = shlex.quote(f"{path}.portal.{uuid.uuid4().hex}.tmp")
    q_parent = shlex.quote(_parent(path))
    q_b64 = shlex.quote(encoded)
    command = (
        f"mkdir -p -- {q_parent} && "
        f"printf %s {q_b64} | base64 -d > {q_tmp} && "
        f"chmod 600 {q_tmp} && "
        f"mv -- {q_tmp} {q_path}"
    )
    rc, output = await ws_exec(login, ws_id, command, timeout=timeout)
    if rc != 0:
        raise ContainerFileError(f"écriture de {path!r} échouée (rc={rc}): {output}")


def _parent(path: str) -> str:
    """Répertoire parent d'un chemin POSIX absolu, sans importer pathlib côté conteneur."""
    head = path.rsplit("/", 1)[0]
    return head or "/"
