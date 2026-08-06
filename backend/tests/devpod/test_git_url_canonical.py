"""Canonicalisation de l'URL git http(s) → `.git`.

GitLab self-hosted répond 301 (redirection vers l'endpoint `.git`) quand on tape
le chemin web nu ; git avec `followRedirects=false` échoue alors. On canonicalise
donc l'URL http(s) en suffixe `.git` avant `ls-remote` (GitHub sert les deux, donc
inchangé). SSH / git@ ne sont pas touchés.
"""

from __future__ import annotations

import pytest

from portal.devpod.git import _canonical_http_git_url, strip_http_userinfo


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Chemin web nu (frontend retire .git) → suffixe restauré
        ("https://gitlab.example.com/grp/sub/docs", "https://gitlab.example.com/grp/sub/docs.git"),
        # Slash final → retiré + .git
        ("https://gitlab.example.com/grp/docs/", "https://gitlab.example.com/grp/docs.git"),
        # Déjà .git → inchangé
        ("https://gitlab.example.com/grp/docs.git", "https://gitlab.example.com/grp/docs.git"),
        # .git + slash → normalisé
        ("https://gitlab.example.com/grp/docs.git/", "https://gitlab.example.com/grp/docs.git"),
        # http simple
        ("http://host/a/b", "http://host/a/b.git"),
        # GitHub inchangé (sert les deux formes)
        ("https://github.com/owner/repo.git", "https://github.com/owner/repo.git"),
    ],
)
def test_canonicalizes_http_git_url(raw: str, expected: str) -> None:
    assert _canonical_http_git_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "git@gitlab.example.com:grp/docs.git",
        "ssh://git@gitlab.example.com/grp/docs.git",
        # Azure DevOps : convention /_git/<repo> sans .git → ne pas suffixer
        "https://dev.azure.com/org/project/_git/repo",
    ],
)
def test_leaves_non_http_untouched(raw: str) -> None:
    assert _canonical_http_git_url(raw) == raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Azure : org en userinfo → retiré (sinon git clone cherche le credential
        # de l'utilisateur `org`, que le store username=oauth2 ne matche pas).
        (
            "https://pickupsa@dev.azure.com/pickupsa/Pickup/_git/Architecture-COR-Documentation",
            "https://dev.azure.com/pickupsa/Pickup/_git/Architecture-COR-Documentation",
        ),
        # user:token@ éventuel → tout l'userinfo retiré
        ("https://user:tok@host/a/b.git", "https://host/a/b.git"),
        # Port préservé, casse du host préservée
        ("https://Org@Host.example.com:8443/a", "https://Host.example.com:8443/a"),
        # http simple avec userinfo
        ("http://u@host/a", "http://host/a"),
    ],
)
def test_strips_http_userinfo(raw: str, expected: str) -> None:
    assert strip_http_userinfo(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # Pas d'userinfo → inchangé
        "https://dev.azure.com/org/project/_git/repo",
        "https://github.com/owner/repo.git",
        # ssh/git@ → inchangé (le `git@` n'est pas un userinfo http à retirer)
        "git@github.com:owner/repo.git",
        "ssh://git@host/owner/repo.git",
    ],
)
def test_strip_userinfo_leaves_others_untouched(raw: str) -> None:
    assert strip_http_userinfo(raw) == raw
