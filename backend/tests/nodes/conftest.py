from __future__ import annotations

import ipaddress as _ipmod
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod

    mod._settings = None
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_global_cache() -> Iterator[None]:
    """Invalide le cache RAM de la GlobalConfig avant et après chaque test.

    enroll_node lit la config via load_global() (cache DB) : sans invalidation,
    un test précédent pourrait laisser un cache peuplé et fausser l'isolation.
    """
    from portal.db.global_config import invalidate_cache

    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture
def ca_fixture(tmp_data_root: Path) -> tuple[Path, Path]:
    """Génère une CA auto-signée de test dans tmp_data_root/certs/ca/."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.now(UTC)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    ca_dir = tmp_data_root / "certs" / "ca"
    ca_dir.mkdir(parents=True, exist_ok=True)
    ca_cert_path = ca_dir / "ca.pem"
    ca_key_path = ca_dir / "ca-key.pem"
    ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    ca_key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    ca_key_path.chmod(0o600)
    return ca_cert_path, ca_key_path


def _build_csr(node_name: str, address: str, *, ca_flag: bool = False) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san_values: list[x509.GeneralName] = [x509.DNSName(node_name)]
    try:
        san_values.insert(0, x509.IPAddress(_ipmod.IPv4Address(address)))
    except ValueError:
        san_values.insert(0, x509.DNSName(address))
    builder = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, node_name)]))
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
    )
    if ca_flag:
        builder = builder.add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
    return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


@pytest.fixture
def valid_csr() -> bytes:
    return _build_csr("test-node", "192.168.1.100")


@pytest.fixture
def csr_ca_flag() -> bytes:
    return _build_csr("test-node", "192.168.1.100", ca_flag=True)


@pytest.fixture
def csr_wrong_cn() -> bytes:
    return _build_csr("wrong-node", "192.168.1.100")


@pytest.fixture
def csr_no_san() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-node")]))
        .sign(key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
    )
