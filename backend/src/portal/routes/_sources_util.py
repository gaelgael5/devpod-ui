"""Utilitaires partagés pour les galeries à base de toc.txt."""
from __future__ import annotations


def split_toc_url(source: str) -> tuple[str, str]:
    """Normalise une source en (toc_url, dir_base).

    Accepte indifféremment le dossier (``.../jinja/``) ou l'URL complète du
    fichier d'index (``.../jinja/toc.txt``). ``dir_base`` est le répertoire sans
    slash final ; ``toc_url`` pointe toujours sur un unique ``toc.txt``.
    """
    stripped = source.rstrip("/")
    head, _, tail = stripped.rpartition("/")
    if tail == "toc.txt":
        return stripped, head
    return f"{stripped}/toc.txt", stripped
