"""Tests du bundle mTLS par host (tranche 3 docker-tls cert).

Le bundle `/data/certs/hosts/<name>/{ca.pem,cert.pem,key.pem}` est matérialisé
à l'association d'un cert du gestionnaire à un host docker-tls. Exigences :
- nom de host validé strictement avant tout usage en chemin (pas de traversal)
- écritures atomiques (tempfile + os.replace), dossier 700, fichiers 600
- suppression idempotente
"""

from __future__ import annotations

from pathlib import Path

import pytest

CA = "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----\n"
CERT = "-----BEGIN CERTIFICATE-----\nCLIENT\n-----END CERTIFICATE-----\n"
KEY = "-----BEGIN PRIVATE KEY-----\nKEY\n-----END PRIVATE KEY-----\n"


# ─── host_bundle_dir ─────────────────────────────────────────────────────────


def test_host_bundle_dir_under_data_root(tmp_data_root: Path) -> None:
    from portal.certificates.docker_bundle import host_bundle_dir

    assert host_bundle_dir("node1") == tmp_data_root / "certs" / "hosts" / "node1"


@pytest.mark.parametrize(
    "bad_name",
    ["", "../evil", "a/b", "a\\b", ".hidden", "-lead", "a" * 64, "nom avec espace"],
)
def test_host_bundle_dir_rejects_invalid_name(tmp_data_root: Path, bad_name: str) -> None:
    from portal.certificates.docker_bundle import host_bundle_dir

    with pytest.raises(ValueError):
        host_bundle_dir(bad_name)


# ─── materialize / exists / remove ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_materialize_writes_three_files_with_perms(tmp_data_root: Path) -> None:
    from portal.certificates.docker_bundle import bundle_exists, materialize_host_bundle

    await materialize_host_bundle("node1", ca_pem=CA, cert_pem=CERT, key_pem=KEY)

    bundle = tmp_data_root / "certs" / "hosts" / "node1"
    assert (bundle / "ca.pem").read_text() == CA
    assert (bundle / "cert.pem").read_text() == CERT
    assert (bundle / "key.pem").read_text() == KEY
    assert bundle.stat().st_mode & 0o777 == 0o700
    for name in ("ca.pem", "cert.pem", "key.pem"):
        assert (bundle / name).stat().st_mode & 0o777 == 0o600, name
    assert bundle_exists("node1")


@pytest.mark.asyncio
async def test_materialize_overwrites_previous_bundle(tmp_data_root: Path) -> None:
    from portal.certificates.docker_bundle import materialize_host_bundle

    await materialize_host_bundle("node1", ca_pem=CA, cert_pem=CERT, key_pem=KEY)
    await materialize_host_bundle("node1", ca_pem=CA, cert_pem=CERT, key_pem="NEW-KEY\n")

    bundle = tmp_data_root / "certs" / "hosts" / "node1"
    assert (bundle / "key.pem").read_text() == "NEW-KEY\n"


@pytest.mark.asyncio
async def test_remove_host_bundle_idempotent(tmp_data_root: Path) -> None:
    from portal.certificates.docker_bundle import (
        bundle_exists,
        materialize_host_bundle,
        remove_host_bundle,
    )

    await materialize_host_bundle("node1", ca_pem=CA, cert_pem=CERT, key_pem=KEY)
    await remove_host_bundle("node1")
    assert not bundle_exists("node1")
    assert not (tmp_data_root / "certs" / "hosts" / "node1").exists()

    # Idempotent : pas d'erreur si absent
    await remove_host_bundle("node1")


def test_bundle_exists_requires_all_three_files(tmp_data_root: Path) -> None:
    from portal.certificates.docker_bundle import bundle_exists

    bundle = tmp_data_root / "certs" / "hosts" / "node1"
    bundle.mkdir(parents=True)
    (bundle / "ca.pem").write_text(CA)
    (bundle / "cert.pem").write_text(CERT)
    assert not bundle_exists("node1")  # key.pem manquant
    (bundle / "key.pem").write_text(KEY)
    assert bundle_exists("node1")
