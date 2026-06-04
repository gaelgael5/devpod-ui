# deploy/Dockerfile
# Image générique du portail workspace — aucun secret embarqué (§D-21)
# Build : docker build -f deploy/Dockerfile -t workspace-portal:latest .
FROM python:3.12-slim

# Version DevPod à pinner — vérifier avec : devpod version
ARG DEVPOD_VERSION=0.6.15

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        openssl \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI uniquement (pas le daemon — §D-21, l'image ne pilote aucun docker local)
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

WORKDIR /app

# Installer les dépendances Python AVANT de copier le code (layer cache)
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ ./src/
RUN pip install --no-cache-dir . \
    && rm -rf src/ pyproject.toml README.md

EXPOSE 8080

# Pas d'ENV avec secret — tout vient de /data/.env au runtime
CMD ["uvicorn", "portal.app:app", "--host", "0.0.0.0", "--port", "8080"]
