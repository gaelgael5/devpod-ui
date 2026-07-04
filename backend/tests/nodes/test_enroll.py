"""Tests de sign_csr (validation CSR) et enroll_node (tokens + certs en DB)."""
from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.config.models import GlobalConfig
from portal.db.tokens import create_token
from portal.nodes.enroll import CsrValidationError, enroll_node, sign_csr

NODE = "test-node"
ADDR = "192.168.1.100"


def _san_of(cert_pem: bytes) -> x509.SubjectAlternativeName:
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value


def _csr_with_san(
    cn: str, san: list[x509.GeneralName]
) -> bytes:
    """CSR arbitraire avec un SAN choisi (pour tester la non-recopie du SAN)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
    )


# ─── sign_csr ─────────────────────────────────────────────────────────────────


def test_valid_csr_is_signed(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path], valid_csr: bytes
) -> None:
    ca_cert_path, ca_key_path = ca_fixture
    cert_pem, ca_pem = sign_csr(
        csr_pem=valid_csr,
        expected_cn=NODE,
        expected_address=ADDR,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )
    assert b"BEGIN CERTIFICATE" in cert_pem
    assert b"BEGIN CERTIFICATE" in ca_pem


def test_csr_ca_flag_rejected(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path], csr_ca_flag: bytes
) -> None:
    ca_cert_path, ca_key_path = ca_fixture
    with pytest.raises(CsrValidationError, match="CA:TRUE"):
        sign_csr(
            csr_pem=csr_ca_flag,
            expected_cn=NODE,
            expected_address=ADDR,
            ca_cert_path=ca_cert_path,
            ca_key_path=ca_key_path,
        )


def test_csr_wrong_cn_rejected(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path], csr_wrong_cn: bytes
) -> None:
    ca_cert_path, ca_key_path = ca_fixture
    with pytest.raises(CsrValidationError, match="CN"):
        sign_csr(
            csr_pem=csr_wrong_cn,
            expected_cn=NODE,
            expected_address=ADDR,
            ca_cert_path=ca_cert_path,
            ca_key_path=ca_key_path,
        )


def test_csr_missing_san_rejected(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path], csr_no_san: bytes
) -> None:
    ca_cert_path, ca_key_path = ca_fixture
    with pytest.raises(CsrValidationError, match="SAN"):
        sign_csr(
            csr_pem=csr_no_san,
            expected_cn=NODE,
            expected_address=ADDR,
            ca_cert_path=ca_cert_path,
            ca_key_path=ca_key_path,
        )


# ─── §013 : SAN autoritatif, jamais recopié de la CSR ─────────────────────────


def test_foreign_ip_in_csr_san_is_stripped(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path]
) -> None:
    """Une CSR dont le SAN contient l'adresse attendue + une IP étrangère produit
    un cert dont le SAN ne contient QUE l'adresse attendue (§013, usurpation)."""
    ca_cert_path, ca_key_path = ca_fixture
    foreign = ipaddress.ip_address("10.0.0.20")
    csr = _csr_with_san(
        NODE,
        [
            x509.IPAddress(ipaddress.ip_address(ADDR)),
            x509.IPAddress(foreign),
            x509.DNSName("evil.example.com"),
        ],
    )
    cert_pem, _ = sign_csr(
        csr_pem=csr,
        expected_cn=NODE,
        expected_address=ADDR,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )
    san = _san_of(cert_pem)
    ips = san.get_values_for_type(x509.IPAddress)
    dns = san.get_values_for_type(x509.DNSName)
    assert ips == [ipaddress.ip_address(ADDR)]
    assert foreign not in ips
    assert dns == []


def test_signed_san_is_ip_type_for_ip_address(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path], valid_csr: bytes
) -> None:
    """Adresse = IP ⇒ SAN reconstruit en IPAddress, exactement l'adresse."""
    ca_cert_path, ca_key_path = ca_fixture
    cert_pem, _ = sign_csr(
        csr_pem=valid_csr,
        expected_cn=NODE,
        expected_address=ADDR,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )
    san = _san_of(cert_pem)
    assert san.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address(ADDR)]
    assert san.get_values_for_type(x509.DNSName) == []


def test_signed_san_dns_for_hostname(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path]
) -> None:
    """Adresse = hostname ⇒ SAN reconstruit en DNSName, exactement le hostname."""
    ca_cert_path, ca_key_path = ca_fixture
    hostname = "node-a.dev.yoops.org"
    csr = _csr_with_san(
        NODE,
        [x509.DNSName(hostname), x509.DNSName("evil.example.com")],
    )
    cert_pem, _ = sign_csr(
        csr_pem=csr,
        expected_cn=NODE,
        expected_address=hostname,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )
    san = _san_of(cert_pem)
    assert san.get_values_for_type(x509.DNSName) == [hostname]
    assert san.get_values_for_type(x509.IPAddress) == []


def test_nominal_san_matches_expected_address(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path]
) -> None:
    """Cas nominal : SAN de la CSR = juste l'adresse attendue ⇒ signé tel quel."""
    ca_cert_path, ca_key_path = ca_fixture
    csr = _csr_with_san(NODE, [x509.IPAddress(ipaddress.ip_address(ADDR))])
    cert_pem, _ = sign_csr(
        csr_pem=csr,
        expected_cn=NODE,
        expected_address=ADDR,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )
    assert _san_of(cert_pem).get_values_for_type(x509.IPAddress) == [
        ipaddress.ip_address(ADDR)
    ]


# ─── enroll_node ──────────────────────────────────────────────────────────────


@pytest.fixture
def patched_save_global(db_conn: AsyncConnection) -> Iterator[None]:
    """Redirige save_global vers save_global_db sur la connexion de test.

    save_global ouvre sa propre connexion via le moteur global ; en test le
    pool (pool_size=1) est déjà occupé par db_conn. On réutilise donc la même
    connexion : les écritures restent dans la transaction rollbackée et le
    cache RAM est mis à jour comme en production.
    """
    from portal.db.global_config import save_global_db

    async def _save(cfg: GlobalConfig) -> None:
        await save_global_db(cfg, db_conn)

    with patch("portal.nodes.enroll.save_global", _save):
        yield


async def test_enroll_node_updates_config(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    db_conn: AsyncConnection,
    patched_save_global: None,
) -> None:
    from portal.db.global_config import load_global_db

    token = await create_token(NODE, ADDR, db_conn)
    result = await enroll_node(token=token, csr_pem=valid_csr.decode(), conn=db_conn)
    assert "cert_pem" in result
    assert "ca_pem" in result
    cfg = await load_global_db(db_conn)
    assert cfg is not None
    assert NODE in [h.name for h in cfg.hosts]


async def test_enroll_node_saves_cert_file(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    db_conn: AsyncConnection,
    patched_save_global: None,
) -> None:
    token = await create_token(NODE, ADDR, db_conn)
    await enroll_node(token=token, csr_pem=valid_csr.decode(), conn=db_conn)
    cert_path = tmp_data_root / "certs" / "nodes" / NODE / "server-cert.pem"
    assert cert_path.exists()
    assert b"BEGIN CERTIFICATE" in cert_path.read_bytes()


async def test_enroll_node_duplicate_rejected(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    db_conn: AsyncConnection,
    patched_save_global: None,
) -> None:
    token1 = await create_token(NODE, ADDR, db_conn)
    await enroll_node(token=token1, csr_pem=valid_csr.decode(), conn=db_conn)
    token2 = await create_token(NODE, ADDR, db_conn)
    with pytest.raises(ValueError, match="already registered"):
        await enroll_node(token=token2, csr_pem=valid_csr.decode(), conn=db_conn)


def test_enroll_node_path_traversal_rejected(tmp_data_root: Path) -> None:
    from portal.nodes.enroll import _safe_node_cert_path

    with pytest.raises(ValueError, match="DNS-safe"):
        _safe_node_cert_path("../ca")

    with pytest.raises(ValueError, match="DNS-safe"):
        _safe_node_cert_path("foo/bar")
