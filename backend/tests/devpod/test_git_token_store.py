"""git credential store temporaire pour un PAT HTTPS injecté dans `devpod up`.

DevPod forwarde `git credential fill` au git côté portail ; on lui fournit donc le
token via un helper `store`. Le token ne doit jamais transiter par argv ni les logs
(fichier 0600), et l'appelant nettoie le répertoire après l'up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from portal.devpod.git import write_token_credential_store


def test_writes_store_with_encoded_credentials() -> None:
    home, env = write_token_credential_store(
        "gitlab.example.com", "g.beard@corp.com", "glpat-XyZ/42"
    )
    try:
        creds = Path(home, ".git-credentials").read_text()
        # user/token percent-encodés (le @ et le / casseraient l'URL sinon)
        assert creds.strip() == "https://g.beard%40corp.com:glpat-XyZ%2F42@gitlab.example.com"
        gitconfig = Path(home, ".gitconfig").read_text()
        assert "helper = store --file=" in gitconfig
        assert str(Path(home, ".git-credentials")) in gitconfig
        # L'env redirige la config globale git vers notre fichier, sans prompt.
        assert env["GIT_CONFIG_GLOBAL"] == str(Path(home, ".gitconfig"))
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_permissions_are_locked_down() -> None:
    home, _env = write_token_credential_store("h", "u", "t")
    try:
        assert os.stat(home).st_mode & 0o777 == 0o700
        assert os.stat(Path(home, ".git-credentials")).st_mode & 0o777 == 0o600
        assert os.stat(Path(home, ".gitconfig")).st_mode & 0o777 == 0o600
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_token_absent_from_gitconfig() -> None:
    """Le token n'est QUE dans .git-credentials (0600), jamais dans .gitconfig."""
    home, _env = write_token_credential_store("h", "u", "s3cr3t-token")
    try:
        assert "s3cr3t-token" not in Path(home, ".gitconfig").read_text()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_git_credential_fill_returns_stored_token() -> None:
    """Preuve de bout en bout : `git credential fill` (ce que devpod forwarde)
    résout bien le token via notre store + env."""
    if shutil.which("git") is None:
        pytest.skip("git absent")
    home, env = write_token_credential_store("gitlab.example.com", "g.beard@corp.com", "glpat-XyZ")
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=gitlab.example.com\n\n",
            capture_output=True,
            text=True,
            env={**os.environ, **env},
            timeout=10,
        )
        assert proc.returncode == 0, proc.stderr
        assert "username=g.beard@corp.com" in proc.stdout
        assert "password=glpat-XyZ" in proc.stdout
    finally:
        shutil.rmtree(home, ignore_errors=True)
