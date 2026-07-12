#!/usr/bin/env bash
# deploy-portal.sh — Déploiement du portail workspace sur une VM de dev/test.
# À exécuter en root dans la VM (directement ou via remote-deploy.ps1).
# Idempotent : peut être relancé sans danger.
#
# Usage :
#   ./scripts/deploy-portal.sh [BRANCH] [--resetdb]
#   ./scripts/deploy-portal.sh --delete-user <login|email> [--yes]
#   ex : ./scripts/deploy-portal.sh main --resetdb
#   ex : ./scripts/deploy-portal.sh --delete-user gaelgael5
#
#   --resetdb            Arrête la stack, supprime les volumes DB et le fichier
#                        .env, puis repart de zéro (nouveaux credentials générés).
#   --delete-user X      Supprime un compte (login OU email) et court-circuite le
#                        déploiement. Destructif : DELETE users (CASCADE) + le
#                        dossier <DATA_ROOT>/users/<login>. --yes saute la confirmation.
#
# Variables d'env reconnues (toutes optionnelles si /data déjà initialisé) :
#   REPO_URL               URL git du repo        (défaut : HTTPS public gaelgael5/devpod-ui)
#   DATA_ROOT              Racine /data            (défaut : /data)
#   COMPOSE_FILE           Fichier compose cible   (défaut : deploy/docker-compose.yml)
#   PORTAL_BASE_DOMAIN     Domaine wildcard        (défaut : dev.yoops.org)
#   PORTAL_EXTERNAL_URL    URL externe du portail
#   PORTAL_OIDC_ISSUER     URL issuer Keycloak
#   PORTAL_OIDC_CLIENT_ID  Client ID OIDC
#   OIDC_CLIENT_SECRET     Secret client Keycloak (injecté dans /data/.env)

set -euo pipefail
IFS=$'\n\t'

# ─── Configuration ────────────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/gaelgael5/devpod-ui.git}"
APP_DIR="${APP_DIR:-/opt/workspace-portal}"
DATA_ROOT="${DATA_ROOT:-/data}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"

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

# ─── Mode admin : suppression d'un compte (login ou email) ────────────────────
# Court-circuite tout déploiement (aucun clone/pull/build). Opération destructive :
# supprime la ligne `users` — les FK ON DELETE CASCADE purgent workspaces, secrets,
# sessions, mcp, compose… — puis le dossier <DATA_ROOT>/users/<login>. Les secrets
# stockés dans Harpocrate (namespace secret_ns) NE sont PAS purgés (système externe).
_ACCOUNT_LOGIN_RE='^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$'

_psql_portal() {
    # Requête SQL non interactive dans le conteneur postgres. -tA : sortie brute
    # (tuples-only, non alignée) ; ON_ERROR_STOP=1 : exit ≠ 0 sur erreur SQL.
    # psql -v ident=… + référence :'ident' → le littéral est quoté par psql
    # (échappement des quotes) : pas d'injection via un login/email malicieux.
    local pguser
    pguser="$(grep -m1 '^POSTGRES_USER=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '\r')"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
        psql -U "$pguser" -d portal -tA -v ON_ERROR_STOP=1 "$@"
}

delete_account() {
    local ident="$1" assume_yes="$2" login="" confirm exists user_dir
    local matches=()

    if [[ ! -f "$ENV_FILE" ]]; then
        echo "ERREUR : ${ENV_FILE} absent — stack non initialisée ?" >&2; exit 1
    fi
    if ! _psql_portal -c "SELECT 1;" >/dev/null 2>&1; then
        echo "ERREUR : postgres injoignable (la stack est-elle démarrée ?)." >&2; exit 1
    fi

    if [[ "$ident" == *@* ]]; then
        mapfile -t matches < <(_psql_portal -v ident="$ident" \
            -c "SELECT login FROM users WHERE email = :'ident';")
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
        exists="$(_psql_portal -v ident="$login" \
            -c "SELECT 1 FROM users WHERE login = :'ident';")"
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

    _psql_portal -v ident="$login" -c "DELETE FROM users WHERE login = :'ident';" >/dev/null
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
    ENV_FILE="${DATA_ROOT}/.env"
    delete_account "$DELETE_USER" "$ASSUME_YES"
fi

# ─── 1) Positionnement dans le repo ───────────────────────────────────────────
echo ""
if [[ -d "${APP_DIR}/.git" ]]; then
    if [[ -n "$TARGET_BRANCH" ]]; then
        echo "==> [1/4] Repo présent — switch vers ${TARGET_BRANCH}..."
        git -C "$APP_DIR" fetch origin
        git -C "$APP_DIR" checkout "$TARGET_BRANCH"
        git -C "$APP_DIR" pull --ff-only origin "$TARGET_BRANCH"
    else
        CURRENT="$(git -C "$APP_DIR" branch --show-current)"
        echo "==> [1/4] Repo présent — pull (${CURRENT})..."
        git -C "$APP_DIR" pull --ff-only
    fi
else
    TARGET_BRANCH="${TARGET_BRANCH:-main}"
    echo "==> [1/4] Premier clone (branche ${TARGET_BRANCH})..."
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$TARGET_BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

# ─── --resetdb : purge complète avant toute initialisation ────────────────────
if [[ $RESETDB -eq 1 ]]; then
    echo ""
    echo "==> [--resetdb] Arrêt de la stack et suppression des volumes DB..."
    docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans 2>/dev/null || true
    echo "    Suppression des containers arrêtés résiduels..."
    docker container prune -f || true
    ENV_FILE="${DATA_ROOT}/.env"
    if [[ -f "$ENV_FILE" ]]; then
        rm -f "$ENV_FILE"
        echo "    ${ENV_FILE} supprimé."
    fi
    echo "    Reset terminé — le .env et la DB seront recréés depuis zéro."
    echo ""
fi

# ─── 2) Initialiser /data (install.sh — idempotent, §E-25) ──────────────────
echo ""
echo "==> [2/4] Initialisation de /data (install.sh)..."

# Construire le préfixe d'env vars pour install.sh non-interactif
INSTALL_VARS=()
[[ -n "${PORTAL_BASE_DOMAIN:-}"    ]] && INSTALL_VARS+=( "PORTAL_BASE_DOMAIN=${PORTAL_BASE_DOMAIN}" )
[[ -n "${PORTAL_EXTERNAL_URL:-}"   ]] && INSTALL_VARS+=( "PORTAL_EXTERNAL_URL=${PORTAL_EXTERNAL_URL}" )
[[ -n "${PORTAL_OIDC_ISSUER:-}"    ]] && INSTALL_VARS+=( "PORTAL_OIDC_ISSUER=${PORTAL_OIDC_ISSUER}" )
[[ -n "${PORTAL_OIDC_CLIENT_ID:-}" ]] && INSTALL_VARS+=( "PORTAL_OIDC_CLIENT_ID=${PORTAL_OIDC_CLIENT_ID}" )

env "${INSTALL_VARS[@]}" bash scripts/install.sh \
    --data-root    "$DATA_ROOT" \
    --compose-file "$APP_DIR/$COMPOSE_FILE"

# Générer les credentials manquants après install.sh (crée le .env depuis
# .env.example mais ne génère pas les secrets : postgres, session, local login).
ENV_FILE="${DATA_ROOT}/.env"
if [[ -f "$ENV_FILE" ]]; then
    _get_env_val() { grep -m1 "^${1}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true; }

    if [[ -z "$(_get_env_val POSTGRES_USER)" ]]; then
        PG_USER="portal_$(openssl rand -hex 4)"
        PG_PASS="$(openssl rand -hex 24)"
        DB_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@postgres/portal"
        grep -q '^POSTGRES_USER='     "$ENV_FILE" && sed -i "s|^POSTGRES_USER=.*|POSTGRES_USER=${PG_USER}|"         "$ENV_FILE" || echo "POSTGRES_USER=${PG_USER}"     >> "$ENV_FILE"
        grep -q '^POSTGRES_PASSWORD=' "$ENV_FILE" && sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASS}|" "$ENV_FILE" || echo "POSTGRES_PASSWORD=${PG_PASS}" >> "$ENV_FILE"
        grep -q '^DATABASE_URL='      "$ENV_FILE" && sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DB_URL}|"            "$ENV_FILE" || echo "DATABASE_URL=${DB_URL}"        >> "$ENV_FILE"
        echo "    POSTGRES_USER généré : ${PG_USER}"
    fi

    if [[ -z "$(_get_env_val SESSION_SECRET_KEY)" ]]; then
        SESSION_KEY="$(openssl rand -hex 32)"
        grep -q '^SESSION_SECRET_KEY=' "$ENV_FILE" && sed -i "s|^SESSION_SECRET_KEY=.*|SESSION_SECRET_KEY=${SESSION_KEY}|" "$ENV_FILE" || echo "SESSION_SECRET_KEY=${SESSION_KEY}" >> "$ENV_FILE"
        echo "    SESSION_SECRET_KEY généré"
    fi

    if [[ -z "$(_get_env_val LOCAL_PASSWORD)" ]]; then
        command -v python3 &>/dev/null || apt-get install -y --no-install-recommends python3 >/dev/null 2>&1
        python3 -c "import bcrypt" 2>/dev/null || apt-get install -y --no-install-recommends python3-bcrypt >/dev/null 2>&1
        LOCAL_PASS="$(openssl rand -hex 12)"
        LOCAL_HASH="$(PASS="$LOCAL_PASS" python3 -c \
            "import bcrypt, os; print(bcrypt.hashpw(os.environ['PASS'].encode(), bcrypt.gensalt()).decode())")"
        # Doubler $ → $$ : docker compose interpole $VAR dans les valeurs env_file.
        LOCAL_HASH_ESCAPED="$(printf '%s' "$LOCAL_HASH" | sed 's/\$/\$\$/g')"
        grep -q '^LOCAL_PASSWORD='      "$ENV_FILE" && sed -i "s|^LOCAL_PASSWORD=.*|LOCAL_PASSWORD=${LOCAL_PASS}|"             "$ENV_FILE" || echo "LOCAL_PASSWORD=${LOCAL_PASS}"             >> "$ENV_FILE"
        grep -q '^LOCAL_PASSWORD_HASH=' "$ENV_FILE" && sed -i "s|^LOCAL_PASSWORD_HASH=.*|LOCAL_PASSWORD_HASH=${LOCAL_HASH_ESCAPED}|" "$ENV_FILE" || echo "LOCAL_PASSWORD_HASH=${LOCAL_HASH_ESCAPED}" >> "$ENV_FILE"
        echo "    LOCAL_PASSWORD généré : ${LOCAL_PASS}"
    else
        # install.sh peut avoir stocké le hash sans doubler les $ (docker compose
        # interpolerait $VAR → vide, hash corrompu dans le container).
        # Si le hash ne commence pas par $$, on corrige l'escaping.
        _CURRENT_HASH="$(_get_env_val LOCAL_PASSWORD_HASH)"
        if [[ -n "$_CURRENT_HASH" ]] && [[ "$_CURRENT_HASH" != '$$'* ]]; then
            _ESCAPED="$(printf '%s' "$_CURRENT_HASH" | sed 's/\$/\$\$/g')"
            sed -i "s|^LOCAL_PASSWORD_HASH=.*|LOCAL_PASSWORD_HASH=${_ESCAPED}|" "$ENV_FILE"
            echo "    LOCAL_PASSWORD_HASH : escaping \$→\$\$\$ appliqué"
        fi
        unset _CURRENT_HASH _ESCAPED
    fi

    if [[ -z "$(_get_env_val PORTAL_VAULT_KEK)" ]]; then
        VAULT_KEK="$(openssl rand -hex 32)"
        grep -q '^PORTAL_VAULT_KEK=' "$ENV_FILE" && sed -i "s|^PORTAL_VAULT_KEK=.*|PORTAL_VAULT_KEK=${VAULT_KEK}|" "$ENV_FILE" || echo "PORTAL_VAULT_KEK=${VAULT_KEK}" >> "$ENV_FILE"
        echo "    PORTAL_VAULT_KEK généré"
    fi

    unset -f _get_env_val
fi

# Injecter OIDC_CLIENT_SECRET dans /data/.env si fourni
if [[ -n "${OIDC_CLIENT_SECRET:-}" ]] && [[ -f "$ENV_FILE" ]]; then
    EXISTING=$(grep -E '^OIDC_CLIENT_SECRET=.+' "$ENV_FILE" 2>/dev/null || true)
    if [[ -z "$EXISTING" ]]; then
        sed -i "s|^OIDC_CLIENT_SECRET=.*|OIDC_CLIENT_SECRET=${OIDC_CLIENT_SECRET}|" "$ENV_FILE"
        echo "    OIDC_CLIENT_SECRET injecté dans ${ENV_FILE}."
    else
        echo "    OIDC_CLIENT_SECRET déjà renseigné — non écrasé."
    fi
fi

# ─── 3) Build + démarrage de la stack ─────────────────────────────────────────
echo ""
echo "==> [3/4] Build de l'image Docker (frontend + backend)..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build

echo ""
echo "==> Arrêt de la stack en cours (si active)..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans || true

# Détection du port 80 — si déjà utilisé, Caddy part sur 8090 pour éviter le conflit.
if [[ -z "${CADDY_DEV_PORT:-}" ]]; then
    if ss -tlnp 2>/dev/null | grep -q ':80 ' || \
       netstat -tlnp 2>/dev/null | grep -q ':80 '; then
        export CADDY_DEV_PORT="8090"
        echo "    Port 80 déjà utilisé → CADDY_DEV_PORT=8090"
    fi
fi

echo "==> Démarrage de la stack..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

echo ""
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

# ─── 4) Smoke /health ─────────────────────────────────────────────────────────
echo ""
echo "==> [4/4] Smoke /health (timeout 60s)..."
SMOKE_OK=0
ELAPSED=0
PORTAL_ID="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps -q portal 2>/dev/null)"
while [[ $ELAPSED -lt 90 ]]; do
    STATUS="$(docker inspect --format='{{.State.Health.Status}}' "$PORTAL_ID" 2>/dev/null)"
    if [[ "$STATUS" == "healthy" ]]; then
        SMOKE_OK=1; break
    fi
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done

IP="$(ip -4 -o addr show scope global 2>/dev/null | awk 'NR==1 {print $4}' | cut -d/ -f1 || echo '?')"
EXTERNAL="${PORTAL_EXTERNAL_URL:-http://${IP}}"

# Lire les credentials locaux depuis .env (pour affichage uniquement)
_LOCAL_USER="$(grep -E '^LOCAL_USER=' "${DATA_ROOT}/.env" 2>/dev/null | cut -d= -f2- || true)"
_LOCAL_PASS="$(grep -E '^LOCAL_PASSWORD=' "${DATA_ROOT}/.env" 2>/dev/null | cut -d= -f2- || true)"

if [[ $SMOKE_OK -eq 1 ]]; then
    echo ""
    echo "══════════════════════════════════════════════════════════════════"
    echo "  ✓ Portail opérationnel"
    echo ""
    echo "  Accès  : ${EXTERNAL}"
    if [[ -n "${_LOCAL_USER:-}" && -n "${_LOCAL_PASS:-}" && -t 1 ]]; then
        echo "  Login  : ${_LOCAL_USER} / ${_LOCAL_PASS}"
        unset _LOCAL_PASS
    elif [[ -n "${_LOCAL_USER:-}" ]]; then
        echo "  Login  : ${_LOCAL_USER}  (mot de passe dans ${DATA_ROOT}/.env)"
    fi
    echo "  Santé  : http://${IP}:8080/health"
    echo "  Config : ${DATA_ROOT}/config.yaml"
    echo "  Env    : ${DATA_ROOT}/.env"
    echo ""
    echo "  Logs   : docker compose -f ${COMPOSE_FILE} logs -f"
    echo "══════════════════════════════════════════════════════════════════"
else
    cat >&2 <<EOF

══════════════════════════════════════════════════════════════════
  ✗ /health ne répond pas après 60s

  Vérifier : docker compose -f ${COMPOSE_FILE} logs --tail=80 portal
══════════════════════════════════════════════════════════════════
EOF
    exit 1
fi
