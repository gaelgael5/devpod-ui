"""Préconditions d'une recette de host, vérifiées AVANT tout téléchargement.

Une recette de host pèse parfois 20 Go (chaîne Android SDK + émulateur).
Échouer après 2 Go téléchargés est inacceptable : ce qui peut être su d'avance
doit l'être, et le message doit dire LAQUELLE des préconditions manque — pas
« ça n'a pas marché ».

Le script produit ici teste TOUTES les préconditions puis rend la main, plutôt
que de s'arrêter à la première : sinon l'administrateur recommence autant de
fois qu'il manque de choses.
"""

from __future__ import annotations

import shlex

from .models import RecipePrecondition

# Marqueur de ligne d'échec. Le shell distant écrit ses propres lignes
# (bannière, avertissement ssh) : sans marqueur, impossible de les distinguer.
_FAIL = "PRECOND_FAIL"

# `df -kP` compte en blocs de 1 Ko. Le format POSIX (-P) garantit une ligne par
# système de fichiers, là où le format par défaut en coupe certaines en deux.
_KO_PAR_GO = 1024 * 1024


def _test_chemin(chemin: str) -> str:
    cible = shlex.quote(chemin)
    return f'[ -e {cible} ] || echo "{_FAIL} path_exists {cible}"'


def _test_accessible(chemin: str) -> str:
    """Lisible ET inscriptible. Un fichier de peripherique peut exister sans
    etre accessible — /dev/kvm appartient au groupe `kvm`."""
    cible = shlex.quote(chemin)
    return f'[ -r {cible} ] && [ -w {cible} ] || echo "{_FAIL} path_writable {cible}"'


def _test_disque(gb: int, chemin: str) -> str:
    cible = shlex.quote(chemin)
    requis = gb * _KO_PAR_GO
    return (
        f"libre=$(df -kP {cible} 2>/dev/null | awk 'NR==2 {{print $4}}'); "
        f'[ -n "$libre" ] && [ "$libre" -ge {requis} ] '
        f'|| echo "{_FAIL} disk_free_gb {gb} {cible}"'
    )


def _test_arch(arch: str) -> str:
    attendue = shlex.quote(arch)
    return f'[ "$(uname -m)" = {attendue} ] || echo "{_FAIL} arch {attendue}"'


def build_check_command(preconditions: list[RecipePrecondition]) -> str:
    """Script sh testant toutes les préconditions ; vide s'il n'y en a aucune.

    Chaque valeur est quotée alors même qu'elle vient du catalogue et a déjà
    passé la validation du modèle : une regex qui laisserait filer un caractère
    inattendu ne doit pas se transformer en injection sur une machine où l'on
    exécute avec les droits d'administration.
    """
    tests: list[str] = []
    for p in preconditions:
        if p.path_exists:
            tests.append(_test_chemin(p.path_exists))
        if p.path_writable:
            tests.append(_test_accessible(p.path_writable))
        if p.disk_free_gb is not None:
            tests.append(_test_disque(p.disk_free_gb, p.disk_path))
        if p.arch:
            tests.append(_test_arch(p.arch))
    return "\n".join(tests)


def parse_check_output(out: str) -> list[str]:
    """Préconditions non satisfaites, en clair. Liste vide = tout est bon."""
    manquantes: list[str] = []
    for ligne in out.splitlines():
        ligne = ligne.strip()
        if not ligne.startswith(_FAIL):
            continue
        champs = ligne[len(_FAIL) :].split()
        if not champs:
            continue
        nom, args = champs[0], champs[1:]
        if nom == "path_exists":
            manquantes.append(f"chemin absent : {' '.join(args)}")
        elif nom == "path_writable":
            # Distinct de l'absence : « absent » appelle a activer le nesting,
            # « pas accessible » a ajouter l'utilisateur au groupe.
            manquantes.append(f"chemin non accessible en lecture/ecriture : {' '.join(args)}")
        elif nom == "disk_free_gb":
            taille = args[0] if args else "?"
            chemin = args[1] if len(args) > 1 else "/"
            manquantes.append(f"espace disque insuffisant : {taille} Go requis sur {chemin}")
        elif nom == "arch":
            manquantes.append(f"architecture incompatible : {' '.join(args)} attendue")
        else:
            manquantes.append(ligne)
    return manquantes
