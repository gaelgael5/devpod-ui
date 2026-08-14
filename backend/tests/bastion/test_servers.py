"""Push serveurs → Termix : helpers déterministes (cible SSH, mapping usage→dossier)."""

from __future__ import annotations

import pytest

from portal.bastion import servers as srv


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("root@10.0.0.1", ("10.0.0.1", "root")),
        ("deploy@pve2.yoops.org", ("pve2.yoops.org", "deploy")),
        ("10.0.0.5", ("10.0.0.5", "root")),  # pas de user@ → root
        ("@host", ("host", "root")),  # user vide → root
    ],
)
def test_ssh_target(address: str, expected: tuple[str, str]) -> None:
    assert srv._ssh_target(address) == expected


def test_usage_folder_mapping() -> None:
    # hosts d'infra → dossier "hosts" ; autres → "Others" (section « Autres serveurs »
    # de l'écran hosts) ; ressources → "Ressources" ; tests → "workspaces".
    assert srv._USAGE_FOLDER["workspaces"] == "hosts"
    assert srv._USAGE_FOLDER["portail"] == "hosts"
    assert srv._USAGE_FOLDER["autres"] == "Others"
    assert srv._USAGE_FOLDER["ressources"] == "Ressources"
    assert srv._USAGE_FOLDER["tests"] == "workspaces"


def test_srv_slug() -> None:
    assert srv._srv_slug("pve2") == "srv-bastion-pve2"
