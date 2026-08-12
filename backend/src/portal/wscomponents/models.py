"""Contrat déclaratif d'un composant système de workspace (spec 18 T1).

Un composant décrit ce que le portail injecte dans un workspace au `up` :
paquets à installer, fichiers à poser, services à lancer, args de publication de
ports. Le tout est **rendu** avec un contexte (`ssh_port`, `ssh_pubkey`,
`ws_user`…) avant d'être matérialisé dans le devcontainer (fait en brique 3).

Système extensible : ajouter/changer un élément = déclarer un `WorkspaceComponent`
au registre, sans toucher au cœur. `ssh-access` (sshd + tmux) est le premier.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ComponentFile(BaseModel):
    """Fichier posé dans le conteneur : chemin, contenu, perms, propriétaire."""

    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    mode: str = "0644"
    owner: str | None = None  # None = root


class WorkspaceComponent(BaseModel):
    """Composant système injecté dans un workspace. Champs = contrat déclaratif."""

    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool = True
    # Noms des composants à installer avant celui-ci (tri topologique).
    installs_after: list[str] = Field(default_factory=list)
    packages: list[str] = Field(default_factory=list)
    files: list[ComponentFile] = Field(default_factory=list)
    # Commandes de démarrage des services (postStartCommand) — non bloquantes.
    post_start: list[str] = Field(default_factory=list)
    # Args `docker run` (runArgs devcontainer), ex. ["--publish", "0.0.0.0:{ssh_port}:22"].
    run_args: list[str] = Field(default_factory=list)


class ComponentRender(BaseModel):
    """Composant rendu (placeholders substitués), prêt à matérialiser."""

    model_config = ConfigDict(extra="forbid")

    name: str
    packages: list[str]
    files: list[ComponentFile]
    post_start: list[str]
    run_args: list[str]


def _sub(text: str, ctx: dict[str, str]) -> str:
    """Substitue `{clef}` par sa valeur pour chaque entrée du contexte.

    Remplacement littéral par clef (pas `str.format`) : robuste aux accolades
    présentes dans les contenus (scripts, config) et aux clefs inconnues laissées
    intactes.
    """
    for key, value in ctx.items():
        text = text.replace("{" + key + "}", value)
    return text


def render(component: WorkspaceComponent, ctx: dict[str, str]) -> ComponentRender:
    """Rend un composant : substitue les placeholders de chaque champ avec `ctx`."""
    return ComponentRender(
        name=component.name,
        packages=list(component.packages),
        files=[
            ComponentFile(
                path=_sub(f.path, ctx),
                content=_sub(f.content, ctx),
                mode=f.mode,
                owner=_sub(f.owner, ctx) if f.owner is not None else None,
            )
            for f in component.files
        ],
        post_start=[_sub(c, ctx) for c in component.post_start],
        run_args=[_sub(a, ctx) for a in component.run_args],
    )
