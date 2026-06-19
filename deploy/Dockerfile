# deploy/Dockerfile
# Image générique du portail workspace — aucun secret embarqué (§D-21)
# Build : docker build -f deploy/Dockerfile -t workspace-portal:latest .

# --- Stage 1 : build du frontend ---
FROM node:22-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2 : image Python de production ---
FROM python:3.12-slim

# Version DevPod à pinner — vérifier avec : devpod version
ARG DEVPOD_VERSION=0.6.15

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        openssl \
        openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && printf 'precedence ::ffff:0:0/96  100\n' >> /etc/gai.conf

# Docker CLI uniquement (pas le daemon — §D-21)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# DevPod CLI pinné — binaire seul, pas de daemon ni plugin (§D-21)
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
        amd64) DEVPOD_ARCH="linux-amd64" ;; \
        arm64) DEVPOD_ARCH="linux-arm64" ;; \
        *) echo "Architecture non supportée : $ARCH" && exit 1 ;; \
    esac \
    && curl -fsSL \
        "https://github.com/loft-sh/devpod/releases/download/v${DEVPOD_VERSION}/devpod-${DEVPOD_ARCH}" \
        -o /usr/local/bin/devpod \
    && chmod 755 /usr/local/bin/devpod

# Installer uv pour résoudre les deps depuis le lockfile (builds déterministes)
RUN pip install --no-cache-dir uv

WORKDIR /app

# SDK harpocrate — dépendance locale path = "../Sdk/harpocrate-0.6.0"
# Doit être copié avant uv sync pour que le lockfile puisse le résoudre.
COPY Sdk/ /Sdk/

# Étape 1 : installer les dépendances depuis le lockfile (layer cachée si seul le code change)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

# Scripts d'exploitation (install-node.sh, backup.sh…)
COPY scripts/ ./scripts/

# Étape 2 : copier le code source et installer le package (layer invalidée si src/ change)
COPY backend/src/ ./src/
RUN uv sync --no-dev --frozen

# Migrations Alembic — nécessaires au démarrage (run_migrations dans le lifespan)
COPY backend/alembic/ ./alembic/
COPY backend/alembic.ini ./

# Assets frontend buildés dans le stage précédent
COPY --from=frontend-builder /build/dist ./static

# Catalogue de recettes bundlées — synchronisées vers /data/recipes/ au démarrage
COPY recipes/ /app/recipes/

# Exposer le venv uv sur PATH — évite le surcoût de `uv run` à chaque démarrage
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

# Pas d'ENV avec secret — tout vient de /data/.env au runtime
CMD ["uvicorn", "portal.app:app", "--host", "0.0.0.0", "--port", "8080", "--access-log"]
