"""Application d'une recette sur une machine (scope=host).

Trois garde-fous, dans cet ordre, et l'ordre EST le sujet :

1. **compatibilité** — la recette déclare-t-elle cette famille de machine ?
   Refus local, rien ne part sur le réseau ;
2. **préconditions** — vérifiées AVANT tout téléchargement. Une recette de host
   pèse parfois 20 Go : échouer en cours de route laisse la machine à moitié
   faite ;
3. **idempotence** — une sentinelle porte l'identifiant ET la version. Déjà
   posée à la même version : on ne rejoue rien.

L'état vit sur la MACHINE, pas dans une table. C'est elle qui sait ce qui y est
réellement installé : une base de données diverge dès qu'on réinstalle le
portail, qu'on restaure une sauvegarde ou qu'on touche la machine à la main.
"""

from __future__ import annotations

import base64
import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .host_preconditions import build_check_command, parse_check_output
from .models import RecipeMeta

# Racine des sentinelles. Sous /var/lib : l'état survit à un redémarrage et à un
# nettoyage de /tmp, contrairement à ce qu'on poserait dans un home.
SENTINEL_ROOT = "/var/lib/workspace-portal/recipes"

# Marqueur de ligne d'état : le shell distant écrit ses propres lignes
# (bannière, avertissement ssh), sans marqueur on ne les distingue pas.
_STATE = "RECIPE_STATE"

# Une commande de sonde répond en quelques secondes ; une installation, non.
PROBE_TIMEOUT_S = 30.0
APPLY_TIMEOUT_S = 3600.0

Runner = Callable[..., Awaitable[tuple[int, str, str]]]


# Sequences ANSI : le script colore ses messages, et remontes tels quels les
# codes s'affichaient en clair dans l'interface.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Au-dela, une bulle d'erreur ne sert plus personne — `sdkmanager` est bavard.
_SORTIE_MAX = 2000


def nettoyer_sortie(brut: str) -> str:
    """Rend une sortie de script lisible par un humain dans l'interface.

    Retire les couleurs, condense les lignes vides d'un preflight verbeux, et
    borne la longueur en gardant la FIN : c'est la derniere ligne qui porte la
    cause.
    """
    sans_ansi = _ANSI_RE.sub("", brut)
    lignes = [ligne.rstrip() for ligne in sans_ansi.splitlines()]
    condense = "\n".join(ligne for ligne in lignes if ligne)
    if len(condense) <= _SORTIE_MAX:
        return condense
    return "…" + condense[-(_SORTIE_MAX - 1) :]


class HostApplyError(Exception):
    """Refus ou échec d'application, avec un message exploitable tel quel."""


@dataclass(frozen=True)
class RecipeState:
    """Ce qu'une machine dit d'une recette qu'elle porte."""

    version: str
    applied_at: str


@dataclass(frozen=True)
class ApplyResult:
    """`changed=False` = déjà posée dans cette version, rien n'a été exécuté."""

    changed: bool
    version: str


def build_state_probe() -> str:
    """Commande listant les recettes posées sur la machine, avec leur version."""
    racine = shlex.quote(SENTINEL_ROOT)
    return (
        f'for f in {racine}/*.done; do [ -e "$f" ] || continue; '
        f'echo "{_STATE} $(basename "$f" .done) $(cat "$f")"; done 2>/dev/null'
    )


def parse_state(out: str) -> dict[str, RecipeState]:
    """Décode la sonde d'état. Machine vierge → dictionnaire vide."""
    etat: dict[str, RecipeState] = {}
    for ligne in out.splitlines():
        champs = ligne.strip().split()
        if len(champs) < 3 or champs[0] != _STATE:
            continue
        recette, version = champs[1], champs[2]
        applied_at = champs[3] if len(champs) > 3 else ""
        etat[recette] = RecipeState(version=version, applied_at=applied_at)
    return etat


# Une valeur d'option traverse un shell distant privilegie. On la borne a ce
# qu'un parametre de recette a legitimement besoin d'etre : pas de saut de
# ligne (qui couperait l'affectation et ferait passer la suite pour une
# commande), pas de caractere de controle.
_OPTION_VALUE_RE = re.compile(r"^[A-Za-z0-9 ._/:@+-]{0,255}$")


def resolve_options(
    meta: RecipeMeta,
    fournies: dict[str, str],
    context: dict[str, str] | None = None,
) -> dict[str, str]:
    """Valeurs finales des parametres.

    Priorite : SAISIE > CONTEXTE (`from:`) > DEFAUT. Elle est arbitree ICI, une
    fois, et non par une cascade de replis dans chaque script — l'auteur d'une
    recette lit `from: workspace.git_url` dans son manifeste et sait ce qui
    arrivera dans `RECIPE_OPT_REPO_URL`.

    Valide CONTRE LA DECLARATION : un nom absent de la meta est refuse, faute de
    quoi n'importe quel nom arriverait dans l'environnement du script.
    """
    for nom in fournies:
        if nom not in meta.options:
            raise HostApplyError(
                f"option {nom!r} inconnue pour la recette {meta.id!r} — "
                f"declarees : {', '.join(sorted(meta.options)) or 'aucune'}"
            )
    ctx = context or {}
    resolues: dict[str, str] = {}
    for nom, declaration in meta.options.items():
        valeur = fournies.get(nom, "").strip()
        if not valeur and declaration.from_context:
            # Une valeur de contexte VIDE (workspace sans depot) ne masque pas
            # le defaut : elle n'apporte rien, autant retomber sur la suite.
            valeur = ctx.get(declaration.from_context, "").strip()
        if not valeur:
            valeur = declaration.default
        if not _OPTION_VALUE_RE.fullmatch(valeur):
            raise HostApplyError(
                f"valeur invalide pour l'option {nom!r} de {meta.id!r} : {valeur!r}"
            )
        resolues[nom] = valeur
    return resolues


def build_apply_script(meta: RecipeMeta, script: str, options: dict[str, str]) -> str:
    """Script d'installation suivi de la pose de la sentinelle.

    `set -e` et l'enchaînement font que la sentinelle n'est posée QUE si
    l'installation réussit : sinon la machine se dirait équipée alors qu'elle ne
    l'est pas, et le re-run suivant ne corrigerait rien.

    Le script voyage en base64 : il traverse un shell distant, et tout guillemet
    ou saut de ligne y serait réinterprété.
    """
    # Les parametres passent par l'ENVIRONNEMENT, en valeurs quotees : jamais
    # par substitution textuelle dans la commande, ou une valeur bien choisie
    # deviendrait du code.
    exports = "".join(
        f"export RECIPE_OPT_{nom.upper()}={shlex.quote(valeur)}\n"
        for nom, valeur in sorted(options.items())
    )
    encode = base64.b64encode(script.encode("utf-8")).decode("ascii")
    racine = shlex.quote(SENTINEL_ROOT)
    sentinelle = shlex.quote(f"{SENTINEL_ROOT}/{meta.id}.done")
    version = shlex.quote(meta.version)
    return (
        "set -e\n"
        "D=$(mktemp -d)\n"
        "trap 'rm -rf \"$D\"' EXIT\n"
        f"printf %s '{encode}' | base64 -d > \"$D/install.sh\"\n"
        f"{exports}"
        'sh "$D/install.sh"\n'
        f"mkdir -p {racine}\n"
        f"printf '%s %s\\n' {version} \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > {sentinelle}\n"
    )


async def apply_recipe_to_host(
    meta: RecipeMeta,
    *,
    host_usage: str,
    script: str,
    run: Runner,
    options: dict[str, str] | None = None,
    context: dict[str, str] | None = None,
) -> ApplyResult:
    """Pose la recette sur la machine, ou explique pourquoi elle ne l'est pas.

    `run` est le canal d'exécution (SSH), injecté : ce module reste testable
    sans machine, et l'abstraction de backend prévue par l'exécuteur de scripts
    générique viendra s'y substituer sans réécriture.
    """
    if meta.scope != "host":
        raise HostApplyError(
            f"recette {meta.id!r} de portée {meta.scope!r} : seules les recettes "
            "de portée 'host' s'appliquent à une machine"
        )
    if not meta.applies_to_host(host_usage):
        raise HostApplyError(
            f"recette {meta.id!r} non applicable à la famille {host_usage!r} — "
            f"familles déclarées : {', '.join(meta.host_usages)}"
        )

    if meta.preconditions:
        rc, out, err = await run(build_check_command(meta.preconditions), timeout=PROBE_TIMEOUT_S)
        if rc != 0:
            raise HostApplyError(
                f"vérification des préconditions impossible : {nettoyer_sortie(err or out)}"
            )
        manquantes = parse_check_output(out)
        if manquantes:
            raise HostApplyError(
                f"préconditions non satisfaites pour {meta.id!r} : " + " ; ".join(manquantes)
            )

    rc, out, err = await run(build_state_probe(), timeout=PROBE_TIMEOUT_S)
    if rc == 0:
        pose = parse_state(out).get(meta.id)
        if pose and pose.version == meta.version:
            return ApplyResult(changed=False, version=meta.version)

    resolues = resolve_options(meta, options or {}, context)
    rc, out, err = await run(build_apply_script(meta, script, resolues), timeout=APPLY_TIMEOUT_S)
    if rc != 0:
        cause = nettoyer_sortie(err or out)
        raise HostApplyError(f"échec de l'application de {meta.id!r} (code {rc}) : {cause}")
    return ApplyResult(changed=True, version=meta.version)
