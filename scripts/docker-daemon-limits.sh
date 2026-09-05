#!/usr/bin/env bash
# docker-daemon-limits.sh — plafonne le cache de build et les journaux du démon
# Docker (enabler 6e8c661f). Idempotent, et JAMAIS destructeur :
#
#   - daemon.json absent  → posé entier ;
#   - daemon.json présent → FUSION : seules les clefs absentes sont ajoutées.
#     Un réglage existant (registres, pilote de stockage, valeurs différentes)
#     n'est jamais écrasé — le script le dit et le laisse ;
#   - sans python3 → échec BRUYANT plutôt qu'un écrasement en silence.
#
# Le GC du builder borne le cache EN CONTINU ; la purge hebdomadaire de
# deploy-portal.sh ramasse les images détaggées qu'aucune option de daemon.json
# ne couvre. Les deux gardes sont complémentaires.
#
# Variables (les seuils se calibrent au disque de la machine, jamais en dur) :
#   DOCKER_GC_KEEP      défaut 10GB   — cache conservé en temps normal
#   DOCKER_GC_MAX       défaut 20GB   — plafond absolu
#   DOCKER_LOG_MAX_SIZE défaut 50m    — taille max d'un fichier de log
#   DOCKER_LOG_MAX_FILE défaut 3      — fichiers de rotation
#   DAEMON_JSON         défaut /etc/docker/daemon.json (surcharge pour tests)
#   RESTART_DOCKER      défaut 0      — 1 = restart si le fichier a changé.
#     Le restart COUPE tous les conteneurs de la machine : à réserver au
#     provisionnement (machine vierge). Sur une machine en service, relancer
#     plus tard, dans une fenêtre choisie — le script le rappelle.
set -euo pipefail

DAEMON_JSON="${DAEMON_JSON:-/etc/docker/daemon.json}"
DOCKER_GC_KEEP="${DOCKER_GC_KEEP:-10GB}"
DOCKER_GC_MAX="${DOCKER_GC_MAX:-20GB}"
DOCKER_LOG_MAX_SIZE="${DOCKER_LOG_MAX_SIZE:-50m}"
DOCKER_LOG_MAX_FILE="${DOCKER_LOG_MAX_FILE:-3}"
RESTART_DOCKER="${RESTART_DOCKER:-0}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERREUR: python3 absent — fusion de ${DAEMON_JSON} impossible." >&2
    echo "        On ÉCHOUE plutôt que d'écraser un réglage existant en silence." >&2
    exit 1
fi

mkdir -p "$(dirname "$DAEMON_JSON")"

CHANGED=$(DAEMON_JSON="$DAEMON_JSON" \
    DOCKER_GC_KEEP="$DOCKER_GC_KEEP" DOCKER_GC_MAX="$DOCKER_GC_MAX" \
    DOCKER_LOG_MAX_SIZE="$DOCKER_LOG_MAX_SIZE" DOCKER_LOG_MAX_FILE="$DOCKER_LOG_MAX_FILE" \
    python3 - <<'PYEOF'
import json
import os
import sys

chemin = os.environ["DAEMON_JSON"]
voulu = {
    "builder": {
        "gc": {
            "enabled": True,
            "defaultKeepStorage": os.environ["DOCKER_GC_KEEP"],
            "policy": [
                {"keepStorage": os.environ["DOCKER_GC_KEEP"], "filter": ["unused-for=168h"]},
                {"keepStorage": os.environ["DOCKER_GC_MAX"], "all": True},
            ],
        }
    },
    "log-driver": "json-file",
    "log-opts": {
        "max-size": os.environ["DOCKER_LOG_MAX_SIZE"],
        "max-file": os.environ["DOCKER_LOG_MAX_FILE"],
    },
}

actuel = {}
if os.path.exists(chemin):
    with open(chemin) as f:
        contenu = f.read().strip()
    if contenu:
        try:
            actuel = json.loads(contenu)
        except ValueError:
            print(f"ERREUR: {chemin} illisible (JSON invalide) — rien n'est touché.", file=sys.stderr)
            sys.exit(1)

# Fusion NON destructrice : une clef déjà posée par l'exploitant fait foi.
ajoutees, laissees = [], []
for cle, valeur in voulu.items():
    if cle in actuel:
        laissees.append(cle)
    else:
        actuel[cle] = valeur
        ajoutees.append(cle)

if not ajoutees:
    print("inchange")
    for cle in laissees:
        print(f"  clef {cle!r} déjà réglée — laissée telle quelle", file=sys.stderr)
    sys.exit(0)

with open(chemin, "w") as f:
    json.dump(actuel, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("modifie")
for cle in ajoutees:
    print(f"  clef {cle!r} ajoutée", file=sys.stderr)
for cle in laissees:
    print(f"  clef {cle!r} déjà réglée — laissée telle quelle", file=sys.stderr)
PYEOF
)

echo "docker-daemon-limits: ${DAEMON_JSON} ${CHANGED}"
if [[ "$CHANGED" == "modifie" ]]; then
    if [[ "$RESTART_DOCKER" == "1" ]]; then
        systemctl restart docker
        echo "docker-daemon-limits: démon Docker redémarré — réglages actifs."
    else
        echo "docker-daemon-limits: ⚠ réglages posés mais PAS actifs — le démon" >&2
        echo "  Docker doit redémarrer (coupe tous les conteneurs) : à faire dans" >&2
        echo "  une fenêtre choisie, ou relancer avec RESTART_DOCKER=1." >&2
    fi
fi
