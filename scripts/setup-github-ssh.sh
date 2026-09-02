#!/usr/bin/env bash
# setup-github-ssh.sh — génère et installe une clé SSH ed25519 pour GitHub.
# Idempotent : peut être relancé sans casser une configuration existante.

set -euo pipefail

LABEL="${1:-$(whoami)@$(hostname -s)}"
KEY="${HOME}/.ssh/id_ed25519_github"
CONFIG="${HOME}/.ssh/config"

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m/!\\\033[0m %s\n' "$1"; }

# --- 1. Répertoire ~/.ssh -----------------------------------------------------
mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"

# --- 2. Génération de la clé --------------------------------------------------
if [[ -f "${KEY}" ]]; then
  warn "La clé ${KEY} existe déjà — génération ignorée."
else
  info "Génération d'une clé ed25519 (${LABEL})"
  # -a 100 : KDF renforcé pour la passphrase. Laisser vide = pas de passphrase.
  ssh-keygen -t ed25519 -a 100 -C "${LABEL}" -f "${KEY}"
fi
chmod 600 "${KEY}"
chmod 644 "${KEY}.pub"

# --- 3. Bloc Host dans ~/.ssh/config -----------------------------------------
touch "${CONFIG}"
chmod 600 "${CONFIG}"

if grep -qE '^\s*Host\s+github\.com\s*$' "${CONFIG}"; then
  warn "Un bloc 'Host github.com' existe déjà dans ${CONFIG} — vérifie-le manuellement."
else
  info "Ajout du bloc Host github.com dans ${CONFIG}"
  {
    printf '\n# --- ajouté par setup-github-ssh.sh ---\n'
    printf 'Host github.com\n'
    printf '  HostName github.com\n'
    printf '  User git\n'
    printf '  IdentityFile %s\n' "${KEY}"
    printf '  IdentitiesOnly yes\n'
    if [[ "$(uname -s)" == "Darwin" ]]; then
      printf '  UseKeychain yes\n'
      printf '  AddKeysToAgent yes\n'
    else
      printf '  AddKeysToAgent yes\n'
    fi
  } >> "${CONFIG}"
fi

# --- 4. Chargement dans l'agent ----------------------------------------------
if [[ -z "${SSH_AUTH_SOCK:-}" ]]; then
  info "Démarrage d'un ssh-agent"
  eval "$(ssh-agent -s)" >/dev/null
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  ssh-add --apple-use-keychain "${KEY}" 2>/dev/null || ssh-add "${KEY}"
else
  ssh-add "${KEY}"
fi

# --- 5. Enregistrement de la clé publique sur GitHub -------------------------
info "Clé publique à déclarer sur GitHub :"
echo
cat "${KEY}.pub"
echo

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  info "gh CLI détecté et authentifié — envoi de la clé"
  gh ssh-key add "${KEY}.pub" --title "${LABEL}" --type authentication
else
  warn "Ajoute-la manuellement : https://github.com/settings/ssh/new (type : Authentication Key)"
  read -rp "Appuie sur Entrée une fois la clé enregistrée..."
fi

# --- 6. Vérification ----------------------------------------------------------
info "Test de la connexion"
# GitHub renvoie toujours un code de sortie 1 sur `ssh -T`, même en cas de succès.
ssh -T git@github.com 2>&1 | grep -q "successfully authenticated" \
  && info "Authentification OK." \
  || warn "Échec — relance : ssh -vT git@github.com"
