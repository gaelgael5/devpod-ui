#!/usr/bin/env bash
#
# dev-deploy.sh — Build local + déploiement Docker pour une instance DEV.
#
# Cible : machine de dev (LXC, VM, poste local) avec Docker installé.
# Le script :
#   1. git pull (ou clone si pas encore fait)
#   2. Crée .env depuis .env.example si absent (+ secrets aléatoires)
#   3. Build les images locales (backend ; frontend skippé tant que M5 pas commencé)
#   4. Down de la stack (avec -v si --reset)
#   5. Pull images registry (postgres + caddy + pgweb) + up -d
#   Final : attend que /health réponde et affiche /version (timeout 60s)
#
# Usage :
#   ./dev-deploy.sh                       # reste sur la branche courante, pull
#   ./dev-deploy.sh feat/ma-branche       # checkout cette branche, puis pull
#   ./dev-deploy.sh --reset               # DESTRUCTIF : down -v (purge volumes)
#   ./dev-deploy.sh feat/ma-branche --reset
#
# Le flag --reset force un `docker compose down -v` qui purge les volumes
# nommés Docker (`postgres_data`, `caddy_data`, `caddy_config`). La base
# Postgres repart de zéro avec POSTGRES_PASSWORD du .env. Le `.env` est
# conservé.
#
# ─── Réutilisabilité ────────────────────────────────────────────────────────
# Ce script est conçu comme un template. Pour le reprendre dans un autre
# projet, modifier UNIQUEMENT la section « Configuration du projet » ci-dessous
# (PROJECT_NAME et REPO_URL). Tous les noms dérivés — images Docker, env vars,
# répertoires applicatifs — sont calculés à partir de PROJECT_NAME.

set -euo pipefail

# ─── Configuration du projet (À MODIFIER lors d'une réutilisation) ──────────
PROJECT_NAME="rag"
PROJECT_NAME_UPPER="$(echo "$PROJECT_NAME" | tr '[:lower:]' '[:upper:]')"
REPO_URL="${REPO_URL:-git@github.com:ag-flow/rag.git}"


COMPOSE_FILE="docker-compose-dev.yml"

# Parse args : on accepte un mix « branche optionnelle » + « flags --xxx ».
# Tout ce qui commence par `--` est un flag ; le reste est la branche.
TARGET_BRANCH=""
RESET_DATA=0
for arg in "$@"; do
  case "$arg" in
    --reset)
      RESET_DATA=1
      ;;
    --*)
      echo "✗ Flag inconnu : ${arg}" >&2
      echo "  Flags supportés : --reset" >&2
      exit 1
      ;;
    *)
      if [ -n "$TARGET_BRANCH" ]; then
        echo "✗ Plusieurs branches passées en argument : '${TARGET_BRANCH}' et '${arg}'" >&2
        exit 1
      fi
      TARGET_BRANCH="$arg"
      ;;
  esac
done

# ─── 0) Pré-requis : Docker installé ─────────────────────────────────────────

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<EOF
✗ Docker n'est pas installé sur ce serveur.

Installer Docker sur Debian/Ubuntu :
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable --now docker

Puis relancer ./dev-deploy.sh.
EOF
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "✗ Docker Compose v2 manquant (commande 'docker compose' absente)." >&2
  echo "  Installer le plugin compose : sudo apt install docker-compose-plugin" >&2
  exit 1
fi

# ─── 1) Positionnement dans le repo ─────────────────────────────────────────

if [ -d ".git" ]; then
  if [ -n "$TARGET_BRANCH" ]; then
    echo "[1/5] Repo détecté dans $(pwd) — switch vers ${TARGET_BRANCH}..."
    git fetch origin
    git checkout "$TARGET_BRANCH"
    git pull --ff-only origin "$TARGET_BRANCH"
  else
    CURRENT_BRANCH="$(git branch --show-current)"
    echo "[1/5] Repo détecté dans $(pwd) — pull branche courante (${CURRENT_BRANCH})..."
    git pull --ff-only
  fi
else
  APP_DIR="${PROJECT_NAME}"
  if [ -d "$APP_DIR/.git" ]; then
    if [ -n "$TARGET_BRANCH" ]; then
      echo "[1/5] Repo dans ./${APP_DIR} — switch vers ${TARGET_BRANCH}..."
      git -C "$APP_DIR" fetch origin
      git -C "$APP_DIR" checkout "$TARGET_BRANCH"
      git -C "$APP_DIR" pull --ff-only origin "$TARGET_BRANCH"
    else
      CURRENT_BRANCH="$(git -C "$APP_DIR" branch --show-current)"
      echo "[1/5] Repo dans ./${APP_DIR} — pull branche courante (${CURRENT_BRANCH})..."
      git -C "$APP_DIR" pull --ff-only
    fi
  else
    # Premier clone : on demande explicitement une branche cible (sinon
    # on ne sait pas laquelle prendre — pas de "branche courante" possible).
    if [ -z "$TARGET_BRANCH" ]; then
      echo "[1/5] Aucun repo trouvé. Premier clone — précise la branche en argument :"
      echo "      ./dev-deploy.sh main"
      exit 1
    fi
    echo "[1/5] Clone du repo dans ./${APP_DIR} (branche ${TARGET_BRANCH})..."
    git clone --branch "$TARGET_BRANCH" "$REPO_URL" "$APP_DIR"
  fi
  cd "$APP_DIR"
fi

# ─── 2) .env ────────────────────────────────────────────────────────────────

# Génère un secret URL-safe de N chars (base64-derived, sans +/=).
# Utilisable directement dans une URL ou un DSN sans escape.
gen_urlsafe() {
  openssl rand -base64 48 | tr '+/' '-_' | tr -d '=' | head -c "${1:-24}"
}

# Substitue la valeur d'une clé `KEY=...` dans un .env.
# Délimiteur sed = `#` pour ne pas être gêné par `/` (présent dans base64).
# Les valeurs générées ne contiennent ni `#` ni `&` (caractères spéciaux sed).
set_env_value() {
  local file="$1" key="$2" value="$3"
  sed -i "s#^${key}=.*#${key}=${value}#" "$file"
}

# Lit la valeur d'une variable depuis .env. Centralisé ici pour éviter de
# coder la regex inline dans une awk single-quoted (où ${PROJECT_NAME_UPPER}
# ne s'expanserait pas).
# Retourne une chaîne vide si .env absent ou clé non trouvée.
read_env_var() {
  local key="$1"
  [ -f ".env" ] || return 0
  awk -F'=' -v k="$key" '$1 == k {print $2; exit}' .env | tr -d '\r'
}

# Détecte l'IPv4 de l'interface eth0. Retourne vide si l'interface n'existe
# pas (ex: serveur où l'interface s'appelle ens18, enp0s3, etc.).
detect_eth0_ip() {
  ip -4 -o addr show dev eth0 2>/dev/null \
    | awk '{print $4}' | cut -d/ -f1 | head -1
}

# Ajoute au .env les clés présentes dans .env.example mais manquantes côté
# local (typiquement : nouvelles variables introduites par un git pull). Les
# valeurs existantes ne sont JAMAIS écrasées — on ajoute seulement les clés
# absentes, avec la valeur par défaut du .env.example. Sans ce sync, une
# nouvelle var Pydantic restera invisible côté container malgré le commit
# repo, jusqu'à ce que l'admin édite manuellement le .env du serveur.
sync_new_vars_from_example() {
  local env_file=".env" example_file=".env.example"
  [ -f "$env_file" ] || return 0
  [ -f "$example_file" ] || return 0
  local added=()
  while IFS= read -r line; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    local key="${line%%=*}"
    [ -z "$key" ] && continue
    if ! grep -qE "^${key}=" "$env_file"; then
      # Premier ajout : on prefixe d'un séparateur lisible.
      if [ ${#added[@]} -eq 0 ]; then
        {
          echo ""
          echo "# Nouvelles variables ajoutées par dev-deploy.sh ($(date -I))"
        } >> "$env_file"
      fi
      echo "$line" >> "$env_file"
      added+=("$key")
    fi
  done < "$example_file"
  if [ ${#added[@]} -gt 0 ]; then
    echo "      + ${#added[@]} nouvelle(s) variable(s) ajoutée(s) au .env :"
    for k in "${added[@]}"; do
      echo "          - ${k}"
    done
  fi
}

# ─── HARPOCRATE_DEK (init si absent) ─────────────────────────
# Passphrase pgcrypto qui chiffre les api_keys des coffres Harpocrate en DB.
# Obligatoire dès qu'un coffre est créé (sinon 500 sur POST /admin/harpocrate-vaults).
ensure_harpocrate_dek() {
  local env_file="$1"
  local current
  current=$(grep -E '^HARPOCRATE_DEK=' "$env_file" 2>/dev/null \
            | head -1 | cut -d= -f2- || true)
  if [[ -n "$current" ]]; then
    echo "  ✓ HARPOCRATE_DEK déjà défini"
    return 0
  fi

  local dek
  dek="$(gen_urlsafe 48)"

  if grep -qE '^HARPOCRATE_DEK=' "$env_file"; then
    sed -i "s|^HARPOCRATE_DEK=.*|HARPOCRATE_DEK=${dek}|" "$env_file"
  else
    echo "HARPOCRATE_DEK=${dek}" >> "$env_file"
  fi

  echo "  ✓ HARPOCRATE_DEK généré (48 chars)"
}

# ─── Bootstrap admin local (init si absent) ─────────────────
ensure_bootstrap_admin_hash() {
  local env_file="$1"
  local current
  current=$(grep -E '^RAG_BOOTSTRAP_ADMIN_PASSWORD_HASH=' "$env_file" 2>/dev/null \
            | head -1 | cut -d= -f2- || true)
  if [[ -n "$current" ]]; then
    echo "  ✓ RAG_BOOTSTRAP_ADMIN_PASSWORD_HASH déjà défini"
    return 0
  fi

  # htpasswd (apache2-utils) génère des hashs bcrypt natifs.
  # NB : openssl ne supporte PAS -bcrypt en upstream — il faut htpasswd.
  if ! command -v htpasswd >/dev/null 2>&1; then
    echo "  ℹ htpasswd absent, installation de apache2-utils..."
    apt-get install -y apache2-utils >/dev/null 2>&1 || {
      echo "  ✗ Échec installation apache2-utils. Installer manuellement : apt install apache2-utils" >&2
      return 1
    }
  fi

  local plain hash hash_escaped
  plain=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
  hash=$(htpasswd -nbBC 12 "" "$plain" | tr -d ':\n') || {
    echo "  ✗ htpasswd a échoué — vérifier le paquet apache2-utils." >&2
    return 1
  }
  # docker-compose interprète $ dans les valeurs env_file : on doit doubler pour échapper.
  # Cf. .env.example : "doubler tout $ en $$ si déposé via env_file".
  hash_escaped="${hash//\$/\$\$}"

  if grep -qE '^RAG_BOOTSTRAP_ADMIN_PASSWORD_HASH=' "$env_file"; then
    sed -i "s|^RAG_BOOTSTRAP_ADMIN_PASSWORD_HASH=.*|RAG_BOOTSTRAP_ADMIN_PASSWORD_HASH=${hash_escaped}|" "$env_file"
  else
    echo "RAG_BOOTSTRAP_ADMIN_PASSWORD_HASH=${hash_escaped}" >> "$env_file"
  fi

  # Écrit aussi le pwd en clair dans .env pour commodité dev (dev-only).
  # Le backend ne lit PAS cette variable — c'est juste un memo pour l'opérateur.
  if grep -qE '^RAG_BOOTSTRAP_ADMIN_PASSWORD_PLAIN=' "$env_file"; then
    sed -i "s|^RAG_BOOTSTRAP_ADMIN_PASSWORD_PLAIN=.*|RAG_BOOTSTRAP_ADMIN_PASSWORD_PLAIN=${plain}|" "$env_file"
  else
    echo "RAG_BOOTSTRAP_ADMIN_PASSWORD_PLAIN=${plain}" >> "$env_file"
  fi

  echo
  echo "═══════════════════════════════════════════════════════════"
  echo "  COMPTE ADMIN BOOTSTRAP CRÉÉ"
  echo "  Username : admin"
  echo "  Password : ${plain}"
  echo "  (aussi mémorisé dans .env sous RAG_BOOTSTRAP_ADMIN_PASSWORD_PLAIN)"
  echo "═══════════════════════════════════════════════════════════"
  echo
}

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo "[2/5] .env absent → création depuis .env.example + génération secrets aléatoires"
    cp .env.example .env

    # Secrets auto-générés (M1) :
    # - POSTGRES_PASSWORD : 32 chars URL-safe — utilisé par DATABASE_URL et
    #   RAG_POSTGRES_ADMIN_URL via interpolation du .env.
    # - RAG_MASTER_KEY    : 48 chars URL-safe — Bearer admin (cf. M2).
    PG_PASS="$(gen_urlsafe 32)"
    MASTER_KEY="$(gen_urlsafe 48)"

    set_env_value .env "POSTGRES_PASSWORD" "$PG_PASS"
    set_env_value .env "${PROJECT_NAME_UPPER}_MASTER_KEY" "$MASTER_KEY"

    # `.env` contient des secrets : restreindre les permissions.
    chmod 600 .env

    echo "      ✓ POSTGRES_PASSWORD              : généré ($(echo -n "$PG_PASS" | wc -c) chars)"
    echo "      ✓ ${PROJECT_NAME_UPPER}_MASTER_KEY                 : généré ($(echo -n "$MASTER_KEY" | wc -c) chars)"
    echo
    echo "      ⚠  Configurer les coffres Harpocrate via l'IHM /ui/settings/harpocrate-vaults"
    echo "         après le premier démarrage (HARPOCRATE_DEK requis)."
  else
    echo "[2/5] ⚠  .env absent et .env.example introuvable — config requise pour démarrer"
  fi
else
  echo "[2/5] .env déjà présent (secrets non régénérés)."
  sync_new_vars_from_example
fi

# Hash bcrypt du compte admin bootstrap — généré une seule fois si absent.
if [ -f ".env" ]; then
  ensure_harpocrate_dek ".env"
  ensure_bootstrap_admin_hash ".env"
fi

# ─── 3) Build images locales ────────────────────────────────────────────────

echo "[3/5] Build de ${PROJECT_NAME}-backend:dev..."
if [ -f backend/Dockerfile ]; then
  # Tag :dev pour la trace de build + :latest pour que docker-compose tire l'image
  # qui vient d'être construite (le compose référence rag-backend:latest).
  docker build -t "${PROJECT_NAME}-backend:dev" -t "${PROJECT_NAME}-backend:latest" backend/
else
  echo "      backend/Dockerfile absent — build skippé (phase d'amorçage)."
fi

echo "      Build de ${PROJECT_NAME}-frontend:dev..."
if [ -f frontend/Dockerfile ]; then
  docker build -t "${PROJECT_NAME}-frontend:dev" -t "${PROJECT_NAME}-frontend:latest" frontend/
else
  echo "      frontend/Dockerfile absent — build skippé (jalon M5 pas encore commencé)."
fi

# ─── 4) Stop + cleanup orphelins ────────────────────────────────────────────

echo "[4/5] Arrêt de la stack (incl. orphelins)..."
if [ "$RESET_DATA" = "1" ]; then
  # `down -v` purge les volumes nommés Docker : `postgres_data` (base
  # complète réinit au prochain up avec POSTGRES_PASSWORD du .env),
  # `caddy_data`, `caddy_config`. Le .env est conservé.
  echo "      ⚠  --reset : down -v (purge postgres_data + caddy_data + caddy_config)"
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
else
  docker compose -f "$COMPOSE_FILE" down --remove-orphans || true
fi

# ─── 5) Pull images registry restantes (postgres) puis up ──────────────────

echo "[5/5] Pull images registry (postgres + caddy + pgweb)..."
# On pull SEULEMENT les services tiers (services avec `image:` pur, sans `build:`).
# Les services rag-backend et rag-frontend ont à la fois `image:` et `build:` :
# `docker compose pull` SANS argument tente quand même de les pull depuis le
# registry (qui n'existe pas — images custom buildées localement en étape [3/5])
# et affiche des erreurs « pull access denied » qui polluent la sortie sans
# bloquer le déploiement. On préfère lister explicitement les services tiers.
docker compose -f "$COMPOSE_FILE" pull postgres caddy pgweb || true

echo "      Démarrage de la stack..."
# Expose le SHA git courant au compose (variable interpolée dans
# docker-compose-dev.yml → backend.environment.GIT_SHA). Fallback "unknown"
# si jamais on est hors d'un repo git (cas du clone fraîchement créé plus haut,
# qui a forcément un .git, mais on garde le filet).
export GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans --pull never

echo
echo "✓ Stack lancée. Services :"
docker compose -f "$COMPOSE_FILE" ps
echo
echo "Logs en direct :"
echo "  docker compose -f ${COMPOSE_FILE} logs -f backend"
echo

# ─── Affichage final : URL d'accès ──────────────────────────────────────────
# Pour le smoke (URLs affichées à l'admin local), on utilise TOUJOURS l'IP
# eth0 — pas RAG_PUBLIC_URL, qui peut contenir une valeur héritée non
# pertinente en dev (ex: `http://localhost` par défaut dans .env.example,
# ou une URL Cloudflare configurée pour la prod). Les URLs doivent être
# copiables tel quel depuis le poste de dev.
IP="$(detect_eth0_ip)"
if [ -z "$IP" ]; then
  echo "✗ Impossible de détecter l'IP eth0 — interface absente ou nommée différemment (ens18, enp0s3…)." >&2
  echo "  Le smoke ne peut pas afficher d'URL utilisable. Adapter detect_eth0_ip si besoin." >&2
  exit 1
fi
APP_URL="http://${IP}"

# ─── Smoke /health : on attend que le backend réponde ─────────────────────
# Timeout 60s (12 × 5s). Le boot inclut : pool DB + migrations idempotentes
# + resolver. En cas d'échec on remonte un exit code non-zero pour que les
# scripts d'orchestration (ex : CI) puissent déclencher une alerte.
# Le smoke tape directement le backend sur eth0:8000 (bypass Caddy) pour
# isoler un éventuel souci de proxy d'un souci backend.

echo "Smoke /health (timeout 60s)..."
SMOKE_OK=0
for _ in $(seq 1 12); do
  if curl -sf -m 3 "http://${IP}:8000/health" >/dev/null 2>&1; then
    SMOKE_OK=1
    break
  fi
  sleep 5
done

if [ "$SMOKE_OK" = "1" ]; then
  VERSION_JSON="$(curl -sf -m 3 "http://${IP}:8000/version" 2>/dev/null || echo '{}')"
  cat <<EOF
═════════════════════════════════════════════════════════════════
  ✓ /health     ${APP_URL}/health → ok
  ✓ /version    ${VERSION_JSON}

  Endpoints exposés (cf. docker compose ps) :
  → IHM (frontend)   : ${APP_URL}/
  → API admin        : ${APP_URL}/api/admin/  (auth Bearer ${PROJECT_NAME_UPPER}_MASTER_KEY)
  → API MCP          : ${APP_URL}/mcp         (auth Bearer api_key workspace)
  → Backend direct   : http://${IP}:8000/     (bypass Caddy, debug)
  → pgweb (DB UI)    : http://${IP}:8081/
  → Postgres CLI     : psql postgresql://rag:<POSTGRES_PASSWORD>@${IP}:5432/postgres
EOF
# Compte admin bootstrap — affiché uniquement si le mot de passe en clair est présent dans .env.
_bootstrap_user=$(grep -E '^RAG_BOOTSTRAP_ADMIN_USERNAME=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)
_bootstrap_plain=$(grep -E '^RAG_BOOTSTRAP_ADMIN_PASSWORD_PLAIN=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)
if [[ -n "$_bootstrap_plain" ]]; then
  echo "  → Compte admin     : ${_bootstrap_user:-admin} / ${_bootstrap_plain}  (login local sur ${APP_URL}/ui/login)"
fi
cat <<EOF
═════════════════════════════════════════════════════════════════
EOF
else
  cat >&2 <<EOF
═════════════════════════════════════════════════════════════════
  ✗ /health n'a pas répondu en 60s — vérifier les logs :
      docker compose -f ${COMPOSE_FILE} logs --tail=80 backend
═════════════════════════════════════════════════════════════════
EOF
  exit 1
fi
