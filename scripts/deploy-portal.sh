#!/usr/bin/env bash
# deploy-portal.sh — Script de déploiement UNIQUE du portail workspace.
# À exécuter en root sur la VM cible (directement, via ./dev-deploy.sh à la
# racine, via scripts/dev-deploy.sh, ou via remote-deploy.ps1 — les deux
# dev-deploy.sh sont des shims qui délèguent ici avec le compose de dev).
# Idempotent : peut être relancé sans danger.
#
# Usage :
#   ./scripts/deploy-portal.sh [BRANCH] [--resetdb]
#   ./scripts/deploy-portal.sh --delete-user <login|email> [--yes]
#   ex : ./scripts/deploy-portal.sh dev
#   ex : ./scripts/deploy-portal.sh main --resetdb
#   ex : ./scripts/deploy-portal.sh --delete-user gaelgael5
#
#   --resetdb            Arrête la stack, supprime les volumes DB et le fichier
#                        .env, puis repart de zéro (nouveaux credentials générés).
#                        Ne touche PAS au reste de /data (CA, certs, recettes) :
#                        install.sh ne régénère jamais la CA.
#   --delete-user X      Supprime un compte (login OU email) et court-circuite le
#                        déploiement. Destructif : DELETE users (CASCADE) + le
#                        dossier <DATA_ROOT>/users/<login>. --yes saute la confirmation.
#
# Variables d'env reconnues (toutes optionnelles si /data déjà initialisé) :
#   REPO_URL               URL git du repo        (défaut : HTTPS public gaelgael5/devpod-ui)
#   APP_DIR                Répertoire du repo      (défaut : /opt/workspace-portal)
#   DATA_ROOT              Racine /data            (défaut : /data)
#   COMPOSE_FILE           Fichier compose cible   (défaut : deploy/docker-compose.yml)
#   PORTAL_BASE_DOMAIN     Domaine wildcard        (défaut : dev.yoops.org)
#   PORTAL_EXTERNAL_URL    URL externe du portail
#   PORTAL_OIDC_ISSUER     URL issuer Keycloak
#   PORTAL_OIDC_CLIENT_ID  Client ID OIDC
#   OIDC_CLIENT_SECRET     Secret client Keycloak (injecté dans /data/.env)

set -euo pipefail
IFS=$'\n\t'

# ─── Survie à la perte de la session (incident du 16/08) ─────────────────────
# Le script s'arrête lui-même (`docker compose down`) : lancé depuis une session
# Termix — dont le conteneur fait partie de la stack — il se coupe la branche.
# La session meurt, SIGHUP tue le script entre le `down` et la fin du `up -d`,
# et la stack reste à moitié debout (postgres+loki seuls, portail absent,
# migrations jamais jouées). Un lien mobile qui tombe produit le même résultat.
#
# On ignore donc SIGHUP, et on journalise tout dans un fichier : même si le
# terminal disparaît, le déploiement va au bout et reste diagnosticable.
# `DEPLOY_NO_DETACH=1` désactive ce filet (CI, débogage pas à pas).
trap '' HUP
if [[ "${DEPLOY_NO_DETACH:-0}" != "1" ]]; then
    DEPLOY_LOG="${DEPLOY_LOG:-/tmp/deploy-portal.$(date +%Y%m%d-%H%M%S).log}"
    # tee dans un `setsid` : le pipe survit à la mort du terminal (sans quoi une
    # écriture sur un pty fermé remonte EIO et `set -e` avorte le script).
    if [[ -z "${_DEPLOY_LOGGING:-}" ]]; then
        export _DEPLOY_LOGGING=1
        echo "==> Journal du déploiement : ${DEPLOY_LOG}"
        echo "    (si la session tombe : tail -f ${DEPLOY_LOG})"
        exec > >(setsid tee -a "$DEPLOY_LOG") 2>&1
    fi
fi

# ─── Configuration ────────────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/gaelgael5/devpod-ui.git}"
APP_DIR="${APP_DIR:-/opt/workspace-portal}"
DATA_ROOT="${DATA_ROOT:-/data}"
# Exporté : le compose dev interpole ${DATA_ROOT} (env_file, volume) — VM partagée.
export DATA_ROOT
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
ENV_FILE="${DATA_ROOT}/.env"
# Le compose de dev active les commodités de VM éphémère (VAULT_DEV_PIN,
# CADDY_DEV_PORT) ; jamais sur une instance réelle.
_IS_DEV_COMPOSE=0
[[ "$COMPOSE_FILE" == *docker-compose.dev.yml ]] && _IS_DEV_COMPOSE=1

# ─── Arguments : branche cible + flags ───────────────────────────────────────
TARGET_BRANCH=""
RESETDB=0
DELETE_USER=""
ASSUME_YES=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --resetdb) RESETDB=1 ;;
        --yes | -y) ASSUME_YES=1 ;;
        --delete-user)
            shift
            if [[ $# -eq 0 || -z "$1" ]]; then
                echo "ERREUR : --delete-user attend un login ou un email." >&2; exit 1
            fi
            DELETE_USER="$1"
            ;;
        --delete-user=*) DELETE_USER="${1#*=}" ;;
        --*) echo "ERREUR : flag inconnu : $1" >&2; exit 1 ;;
        *)
            if [[ -n "$TARGET_BRANCH" ]]; then
                echo "ERREUR : plusieurs branches passées en argument." >&2; exit 1
            fi
            TARGET_BRANCH="$1"
            ;;
    esac
    shift
done

# ─── 0) Prérequis ─────────────────────────────────────────────────────────────
echo "==> Vérification des prérequis..."

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERREUR : ce script doit être exécuté en root." >&2
    exit 1
fi

for cmd in docker git openssl; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable." >&2
        echo "  Installer : apt-get install -y docker.io git openssl" >&2
        exit 1
    }
done

if ! docker compose version &>/dev/null; then
    echo "ERREUR : docker compose v2 manquant." >&2
    echo "  Installer : apt-get install -y docker-compose-plugin" >&2
    exit 1
fi

echo "    Prérequis OK."

# ─── Fonctions utilitaires .env ───────────────────────────────────────────────

# Lit la valeur d'une clé dans $ENV_FILE (retourne "" si absente ou vide).
# tr -d '\r' protège contre les fichiers à fins de ligne CRLF (copie depuis Windows).
_get_env() {
    local key="$1"
    grep -m1 "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '\r' || true
}

# Écrit (ou remplace) une clé=valeur dans $ENV_FILE.
_set_env() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

# ─── Mode admin : suppression d'un compte (login ou email) ────────────────────
# Court-circuite tout déploiement (aucun clone/pull/build). Opération destructive :
# supprime la ligne `users` — les FK ON DELETE CASCADE purgent workspaces, secrets,
# sessions, mcp, compose… — puis le dossier <DATA_ROOT>/users/<login>. Les secrets
# stockés dans Harpocrate (namespace secret_ns) NE sont PAS purgés (système externe).
_ACCOUNT_LOGIN_RE='^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$'

_sql_lit() {
    # Échappe une valeur pour un littéral SQL entre quotes simples : double les
    # quotes. standard_conforming_strings=on (défaut Postgres) → le backslash est
    # littéral, donc doubler les quotes suffit à neutraliser toute injection.
    printf "%s" "${1//\'/\'\'}"
}

_psql_portal() {
    # Exécute une requête SQL (valeurs déjà quotées via _sql_lit) dans le conteneur
    # postgres. -tA : sortie brute (tuples-only, non alignée) ; ON_ERROR_STOP=1 :
    # exit ≠ 0 sur erreur SQL.
    local pguser
    pguser="$(_get_env POSTGRES_USER)"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
        psql -U "$pguser" -d portal -tA -v ON_ERROR_STOP=1 -c "$1"
}

delete_account() {
    local ident="$1" assume_yes="$2" login="" confirm exists user_dir
    local matches=()

    if [[ ! -f "$ENV_FILE" ]]; then
        echo "ERREUR : ${ENV_FILE} absent — stack non initialisée ?" >&2; exit 1
    fi
    if ! _psql_portal "SELECT 1;" >/dev/null 2>&1; then
        echo "ERREUR : postgres injoignable (la stack est-elle démarrée ?)." >&2; exit 1
    fi

    local esc
    esc="$(_sql_lit "$ident")"
    if [[ "$ident" == *@* ]]; then
        mapfile -t matches < <(_psql_portal "SELECT login FROM users WHERE email = '${esc}';")
        if [[ "${#matches[@]}" -eq 0 || -z "${matches[0]}" ]]; then
            echo "ERREUR : aucun compte avec l'email '${ident}'." >&2; exit 1
        fi
        if [[ "${#matches[@]}" -gt 1 ]]; then
            echo "ERREUR : plusieurs comptes partagent l'email '${ident}' :" >&2
            printf '  - %s\n' "${matches[@]}" >&2
            echo "  → relance avec le login précis." >&2; exit 1
        fi
        login="${matches[0]}"
    else
        login="$ident"
        exists="$(_psql_portal "SELECT 1 FROM users WHERE login = '${esc}';")"
        if [[ -z "$exists" ]]; then
            echo "ERREUR : aucun compte '${login}'." >&2; exit 1
        fi
    fi

    # Garde-fou anti-traversal : le login résolu DOIT matcher la regex avant le rm.
    if [[ ! "$login" =~ $_ACCOUNT_LOGIN_RE ]]; then
        echo "ERREUR : login résolu '${login}' invalide — abandon." >&2; exit 1
    fi

    user_dir="${DATA_ROOT}/users/${login}"
    echo "⚠️  Suppression du compte :"
    echo "    login     : ${login}"
    echo "    base      : DELETE users (CASCADE : workspaces, secrets, sessions, mcp, compose…)"
    echo "    fichiers  : ${user_dir}"
    echo "    NON purgé : secrets Harpocrate (namespace externe)"

    if [[ "$assume_yes" != "1" ]]; then
        read -r -p "Confirme en retapant le login (${login}) : " confirm
        if [[ "$confirm" != "$login" ]]; then
            echo "Abandon (saisie ≠ '${login}')." >&2; exit 1
        fi
    fi

    _psql_portal "DELETE FROM users WHERE login = '$(_sql_lit "$login")';" >/dev/null
    echo "    ✓ ligne users supprimée (CASCADE appliqué)"

    if [[ -d "$user_dir" ]]; then
        rm -rf "$user_dir"
        echo "    ✓ ${user_dir} supprimé"
    else
        echo "    (dossier ${user_dir} déjà absent)"
    fi
    echo "==> Compte '${login}' supprimé."
    exit 0
}

if [[ -n "$DELETE_USER" ]]; then
    cd "$APP_DIR" 2>/dev/null || { echo "ERREUR : ${APP_DIR} introuvable." >&2; exit 1; }
    delete_account "$DELETE_USER" "$ASSUME_YES"
fi

# ─── 1) Positionnement dans le repo + auto-mise à jour ───────────────────────
echo ""
if [[ -d "${APP_DIR}/.git" ]]; then
    if [[ -n "$TARGET_BRANCH" ]]; then
        echo "==> [1/5] Repo présent — switch vers ${TARGET_BRANCH}..."
        git -C "$APP_DIR" fetch origin
        git -C "$APP_DIR" checkout "$TARGET_BRANCH"
    else
        TARGET_BRANCH="$(git -C "$APP_DIR" branch --show-current)"
        echo "==> [1/5] Repo présent — pull (${TARGET_BRANCH})..."
    fi
    BEFORE="$(git -C "$APP_DIR" rev-parse HEAD)"
    git -C "$APP_DIR" pull --ff-only origin "$TARGET_BRANCH"
    AFTER="$(git -C "$APP_DIR" rev-parse HEAD)"
    # Ré-exécution si le pull a changé quoi que ce soit : garantit que ce script
    # (et install.sh, compose, Dockerfile) tournent dans leur version courante.
    if [[ "$BEFORE" != "$AFTER" && -z "${_DEPLOY_REEXEC:-}" ]]; then
        echo "    Dépôt mis à jour — ré-exécution du script..."
        export _DEPLOY_REEXEC=1
        exec "$APP_DIR/scripts/deploy-portal.sh" "$@"
    fi
else
    TARGET_BRANCH="${TARGET_BRANCH:-main}"
    echo "==> [1/5] Premier clone (branche ${TARGET_BRANCH})..."
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$TARGET_BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

# ─── --resetdb : purge DB + credentials avant toute initialisation ───────────
if [[ $RESETDB -eq 1 ]]; then
    echo ""
    echo "==> [--resetdb] Arrêt de la stack et suppression des volumes DB..."
    docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans 2>/dev/null || true
    echo "    Suppression des containers arrêtés résiduels..."
    docker container prune -f || true
    if [[ -f "$ENV_FILE" ]]; then
        rm -f "$ENV_FILE"
        echo "    ${ENV_FILE} supprimé."
    fi
    echo "    Reset terminé — le .env et la DB seront recréés depuis zéro."
    echo "    (CA, certs et recettes de ${DATA_ROOT} sont conservés — install.sh"
    echo "     ne régénère jamais la CA ; purge manuelle si nécessaire.)"
    echo ""
fi

# ─── 2) Initialiser /data (install.sh — idempotent, §E-25) ────────────────────
echo ""
echo "==> [2/5] Initialisation de /data (install.sh)..."

# Construire le préfixe d'env vars pour install.sh non-interactif
INSTALL_VARS=()
[[ -n "${PORTAL_BASE_DOMAIN:-}"    ]] && INSTALL_VARS+=( "PORTAL_BASE_DOMAIN=${PORTAL_BASE_DOMAIN}" )
[[ -n "${PORTAL_EXTERNAL_URL:-}"   ]] && INSTALL_VARS+=( "PORTAL_EXTERNAL_URL=${PORTAL_EXTERNAL_URL}" )
[[ -n "${PORTAL_OIDC_ISSUER:-}"    ]] && INSTALL_VARS+=( "PORTAL_OIDC_ISSUER=${PORTAL_OIDC_ISSUER}" )
[[ -n "${PORTAL_OIDC_CLIENT_ID:-}" ]] && INSTALL_VARS+=( "PORTAL_OIDC_CLIENT_ID=${PORTAL_OIDC_CLIENT_ID}" )

env "${INSTALL_VARS[@]}" bash scripts/install.sh \
    --data-root    "$DATA_ROOT" \
    --compose-file "$APP_DIR/$COMPOSE_FILE"

# ─── 3) Complétion du .env : credentials manquants ────────────────────────────
# install.sh crée le .env depuis .env.example mais ne génère pas les secrets.
echo ""
echo "==> [3/5] Vérification de ${ENV_FILE}..."

if [[ ! -f "$ENV_FILE" ]]; then
    echo "    ${ENV_FILE} absent — copie depuis deploy/.env.example"
    cp deploy/.env.example "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi

# Normaliser les fins de ligne CRLF → LF (fichier potentiellement édité sur Windows)
if grep -qP '\r' "$ENV_FILE" 2>/dev/null; then
    sed -i 's/\r$//' "$ENV_FILE"
    echo "    Fins de ligne CRLF converties en LF"
fi

if [[ -z "$(_get_env POSTGRES_USER)" ]]; then
    PG_USER="portal_$(openssl rand -hex 4)"
    _set_env POSTGRES_USER "$PG_USER"
    echo "    POSTGRES_USER généré : ${PG_USER}"
fi

if [[ -z "$(_get_env POSTGRES_PASSWORD)" ]]; then
    _set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
    echo "    POSTGRES_PASSWORD généré (48 chars hex)"
fi

if [[ -z "$(_get_env DATABASE_URL)" ]]; then
    DB_URL="postgresql+asyncpg://$(_get_env POSTGRES_USER):$(_get_env POSTGRES_PASSWORD)@postgres/portal"
    _set_env DATABASE_URL "$DB_URL"
    echo "    DATABASE_URL construit"
fi

if [[ -z "$(_get_env SESSION_SECRET_KEY)" ]]; then
    _set_env SESSION_SECRET_KEY "$(openssl rand -hex 32)"
    echo "    SESSION_SECRET_KEY généré"
fi

# Requis hors dev_mode ; vault désactivé sinon.
if [[ -z "$(_get_env PORTAL_VAULT_KEK)" ]]; then
    _set_env PORTAL_VAULT_KEK "$(openssl rand -hex 32)"
    echo "    PORTAL_VAULT_KEK généré"
fi

# VAULT_DEV_PIN : VM de test éphémère uniquement (compose dev) — le vault de
# chaque utilisateur s'initialise/déverrouille automatiquement avec ce PIN
# (dev_mode, cf. portal.vault.pin._dev_auto_unlock). Jamais sur instance réelle.
if [[ $_IS_DEV_COMPOSE -eq 1 && -z "$(_get_env VAULT_DEV_PIN)" ]]; then
    _set_env VAULT_DEV_PIN "$(printf '%06d' "$((RANDOM % 1000000))")"
    echo "    VAULT_DEV_PIN généré"
fi

if [[ -z "$(_get_env LOCAL_PASSWORD)" ]]; then
    command -v python3 &>/dev/null || apt-get install -y --no-install-recommends python3 >/dev/null 2>&1
    python3 -c "import bcrypt" 2>/dev/null || apt-get install -y --no-install-recommends python3-bcrypt >/dev/null 2>&1
    LOCAL_PASS="$(openssl rand -hex 12)"
    LOCAL_HASH="$(PASS="$LOCAL_PASS" python3 -c \
        "import bcrypt, os; print(bcrypt.hashpw(os.environ['PASS'].encode(), bcrypt.gensalt()).decode())")"
    # docker compose et bash interprètent $VAR dans les env_file / source :
    # doubler $ → $$ pour que le hash bcrypt ($2b$12$…) soit transmis intact.
    LOCAL_HASH_ESCAPED="$(printf '%s' "$LOCAL_HASH" | sed 's/\$/\$\$/g')"
    _set_env LOCAL_PASSWORD "$LOCAL_PASS"
    _set_env LOCAL_PASSWORD_HASH "$LOCAL_HASH_ESCAPED"
    echo "    LOCAL_PASSWORD généré : ${LOCAL_PASS}"
else
    # install.sh peut avoir stocké le hash sans doubler les $ (docker compose
    # interpolerait $VAR → vide, hash corrompu dans le container).
    _CURRENT_HASH="$(_get_env LOCAL_PASSWORD_HASH)"
    if [[ -n "$_CURRENT_HASH" && "$_CURRENT_HASH" != '$$'* ]]; then
        _set_env LOCAL_PASSWORD_HASH "$(printf '%s' "$_CURRENT_HASH" | sed 's/\$/\$\$/g')"
        echo "    LOCAL_PASSWORD_HASH : escaping \$→\$\$ appliqué"
    fi
    unset _CURRENT_HASH
fi

# Injecter OIDC_CLIENT_SECRET si fourni en variable d'env (jamais écrasé)
if [[ -n "${OIDC_CLIENT_SECRET:-}" && -z "$(_get_env OIDC_CLIENT_SECRET)" ]]; then
    _set_env OIDC_CLIENT_SECRET "$OIDC_CLIENT_SECRET"
    echo "    OIDC_CLIENT_SECRET injecté dans ${ENV_FILE}."
fi

# Validation : échouer explicitement si une variable critique est encore vide
for _required_key in POSTGRES_USER POSTGRES_PASSWORD SESSION_SECRET_KEY; do
    if [[ -z "$(_get_env "$_required_key")" ]]; then
        echo "ERREUR : ${_required_key} vide dans ${ENV_FILE} après génération automatique." >&2
        echo "  → Éditer manuellement ${ENV_FILE} et définir ${_required_key}." >&2
        exit 1
    fi
done

# Charger toutes les variables du .env dans l'environnement shell :
# docker compose résout ${VAR} depuis l'env shell en priorité sur --env-file.
# set +u requis : les hash bcrypt (LOCAL_PASSWORD_HASH=$2b$12$…) contiennent $2
# que bash interprète comme paramètre positionnel → unbound variable avec set -u.
set +u
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a
set -u

# ─── 4) Build + redémarrage + migrations ──────────────────────────────────────
echo ""
echo "==> [4/5] Build de l'image Docker (frontend + backend)..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build

echo ""
echo "==> Redémarrage de la stack..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans || true

# Détection de conflit sur le port 80 (compose dev : Caddy mappe
# ${CADDY_DEV_PORT:-80}:80) — bascule sur 8090 si :80 est déjà pris.
# IMPÉRATIVEMENT APRÈS le down : sinon c'est notre PROPRE Caddy encore actif
# qui est détecté comme conflit, et 8090 se persiste à tort dans .env
# (le front du portail — tunnel → :80 — tombe alors dans le vide).
if [[ $_IS_DEV_COMPOSE -eq 1 && -z "$(_get_env CADDY_DEV_PORT)" ]]; then
    if ss -tlnp 2>/dev/null | grep -q ':80 ' || \
       netstat -tlnp 2>/dev/null | grep -q ':80 '; then
        _set_env CADDY_DEV_PORT "8090"
        export CADDY_DEV_PORT="8090"
        echo "    Port 80 déjà utilisé par un service tiers → CADDY_DEV_PORT=8090"
    fi
fi

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

echo ""
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

echo ""
echo "==> Migrations Alembic..."
# Attente d'un conteneur portail EXÉCUTABLE avant de migrer : juste après
# `up -d` il peut encore démarrer (ou redémarrer en boucle). Sans cette
# attente, `exec` échouait, `set -e` avortait le déploiement AVANT la
# migration, et la stack restait servie avec un schéma en retard — panne
# silencieuse, car le smoke /health qui suit ne teste pas le schéma.
_MIGRATE_READY=0
for _i in $(seq 1 24); do   # 24 × 5 s = 120 s
    if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
        exec -T portal true >/dev/null 2>&1; then
        _MIGRATE_READY=1
        break
    fi
    sleep 5
done
if [[ $_MIGRATE_READY -eq 0 ]]; then
    echo "ERREUR : conteneur 'portal' injoignable après 120 s — migrations NON jouées." >&2
    echo "         Diagnostic : docker compose -f ${COMPOSE_FILE} logs --tail=80 portal" >&2
    exit 1
fi

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
    exec -T portal uv run alembic upgrade head

# Vérification explicite : `upgrade` peut sortir 0 sans avoir atteint head si
# la base a été tamponnée à côté. On refuse de déclarer le déploiement bon sur
# un schéma en retard — c'est exactement le trou par lequel l'incident est passé.
if ! docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
    exec -T portal uv run alembic current 2>/dev/null | grep -q '(head)'; then
    echo "ERREUR : le schéma n'est pas à head après migration." >&2
    echo "         Voir : docker compose -f ${COMPOSE_FILE} exec -T portal uv run alembic current" >&2
    exit 1
fi
echo "    Schéma à jour (head)."

# ─── 5) Smoke /health ─────────────────────────────────────────────────────────
echo ""
echo "==> [5/5] Smoke /health (timeout 90s)..."
SMOKE_OK=0
ELAPSED=0
PORTAL_ID="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps -q portal 2>/dev/null)"
while [[ $ELAPSED -lt 90 ]]; do
    # Healthcheck du conteneur si disponible, sinon curl direct (fallback).
    STATUS="$(docker inspect --format='{{.State.Health.Status}}' "$PORTAL_ID" 2>/dev/null || true)"
    if [[ "$STATUS" == "healthy" ]] || curl -sf -m 3 "http://localhost:${PORTAL_DEV_PORT:-8080}/health" &>/dev/null; then
        SMOKE_OK=1; break
    fi
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done

IP="$(ip -4 -o addr show scope global 2>/dev/null | awk 'NR==1 {print $4}' | cut -d/ -f1 || echo '?')"
EXTERNAL="${PORTAL_EXTERNAL_URL:-http://${IP}}"
_LOCAL_USER="$(_get_env LOCAL_USER)"
_LOCAL_PASS="$(_get_env LOCAL_PASSWORD)"

if [[ $SMOKE_OK -eq 1 ]]; then
    echo ""
    echo "══════════════════════════════════════════════════════════════════"
    echo "  ✓ Portail opérationnel"
    echo ""
    echo "  Accès  : ${EXTERNAL}"
    # Le compte break-glass n'est utilisable que si le PORTAIL l'accepte :
    # `local_auth_enabled` dépend aussi du toggle `oidc.allow_local_auth` (en base),
    # que le .env ne reflète pas. Annoncer « Login : admin » sur une instance où
    # l'auth locale est désactivée envoyait droit dans le mur (incident du 17/08 :
    # une heure perdue à chercher une panne inexistante). On interroge donc
    # l'instance qui vient de démarrer plutôt que de déduire du .env.
    _AUTH_CFG="$(curl -sf -m 3 "http://localhost:${PORTAL_DEV_PORT:-8080}/auth/config" 2>/dev/null || true)"
    if [[ "$_AUTH_CFG" == *'"local_auth_enabled":true'* ]]; then
        if [[ -n "${_LOCAL_USER:-}" && -n "${_LOCAL_PASS:-}" && -t 1 ]]; then
            echo "  Login  : ${_LOCAL_USER} / ${_LOCAL_PASS}"
        elif [[ -n "${_LOCAL_USER:-}" ]]; then
            echo "  Login  : ${_LOCAL_USER}  (mot de passe dans ${ENV_FILE})"
        fi
    elif [[ "$_AUTH_CFG" == *'"oidc_enabled":true'* ]]; then
        echo "  Login  : via Keycloak (SSO) — authentification locale DÉSACTIVÉE"
    elif [[ -n "$_AUTH_CFG" ]]; then
        echo "  Login  : ⚠ ni SSO ni auth locale active — voir Admin → Authentification"
    fi
    unset _LOCAL_PASS
    # Port PUBLIÉ, pas le port interne : sur une stack dev à ports décalés, le
    # 8080 en dur envoyait vers un port fermé — l'URL affichée ne répondait pas.
    echo "  Santé  : http://${IP}:${PORTAL_DEV_PORT:-8080}/health"
    echo "  Env    : ${ENV_FILE}"
    echo ""
    echo "  Logs   : docker compose -f ${COMPOSE_FILE} logs -f"
    echo "══════════════════════════════════════════════════════════════════"
    echo ""
    echo "==> Logs (80 dernières lignes) :"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" logs --tail=80
else
    cat >&2 <<EOF

══════════════════════════════════════════════════════════════════
  ✗ /health ne répond pas après 90s

  Vérifier : docker compose -f ${COMPOSE_FILE} logs --tail=80 portal
══════════════════════════════════════════════════════════════════
EOF
    exit 1
fi
