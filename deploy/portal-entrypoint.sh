#!/bin/sh
# Entrypoint du conteneur portail : démarre (optionnellement) le sshd bastion en
# secondaire, puis exec uvicorn (process principal = PID conteneur).
#
# Le bastion est OPT-IN via PORTAL_BASTION_ENABLED=1 (dans /data/.env). Tant qu'il
# n'est pas activé, le conteneur se comporte exactement comme avant (uvicorn seul).
# Un échec du bastion N'EMPÊCHE JAMAIS le portail de démarrer.
set -eu

if [ "${PORTAL_BASTION_ENABLED:-0}" = "1" ]; then
    BASTION_DIR=/data/bastion
    mkdir -p "$BASTION_DIR"
    chmod 700 "$BASTION_DIR"
    [ -f "$BASTION_DIR/authorized_keys" ] || : > "$BASTION_DIR/authorized_keys"
    chmod 600 "$BASTION_DIR/authorized_keys"
    # Host key persistée — jamais régénérée (cohérent avec la règle CA : une identité
    # stable pour que Termix n'ait pas à ré-accepter l'empreinte à chaque redeploy).
    if [ ! -f "$BASTION_DIR/ssh_host_ed25519_key" ]; then
        ssh-keygen -t ed25519 -f "$BASTION_DIR/ssh_host_ed25519_key" -N '' -q
    fi
    mkdir -p /run/sshd
    if /usr/sbin/sshd -f /etc/ssh/bastion_sshd_config; then
        echo "portal-entrypoint: bastion sshd démarré sur :2222"
    else
        echo "portal-entrypoint: WARN bastion sshd n'a pas démarré (portail démarre quand même)" >&2
    fi
fi

exec uvicorn portal.app:app --host 0.0.0.0 --port 8080 --access-log
