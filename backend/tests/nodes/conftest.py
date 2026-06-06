from __future__ import annotations

import ipaddress as _ipmod
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
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
def _reset_token_locks() -> None:
    from portal.nodes import enroll

    enroll.clear_token_locks()


def _make_global_config(tmp_data_root: Path) -> None:
    config = {
        "version": "1",
        "server": {
            "listen": "0.0.0.0:8080",
            "base_domain": "dev.yoops.org",
            "external_url": "https://dev.yoops.org",
            "dev_mode": True,
            "log": {"level": "info", "format": "text", "output": ""},
        },
        "auth": {
            "oidc": {
                "issuer": "https://kc.test",
                "client_id": "portal",
                "client_secret": "",
                "scopes": ["openid"],
                "role_claim": "realm_access.roles",
                "admin_role": "admin",
                "user_role": "dev",
                "username_claim": "preferred_username",
            }
        },
        "secrets": {
            "backend": "inline",
            "harpocrate": {"url": "", "api_key": "", "base_path": "devpod"},
        },
        "devpod": {
            "binary": "devpod",
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": str(tmp_data_root / "certs" / "portal"),
        },
        "hosts": [],
        "caddy": {"admin_api": "http://caddy:2019"},
        "cloudflare_manager": {"url": "", "api_key": ""},
    }
    (tmp_data_root / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )


@pytest.fixture
def global_config(tmp_data_root: Path) -> Path:
    """Écrit un config.yaml minimal et retourne tmp_data_root."""
    _make_global_config(tmp_data_root)
    return tmp_data_root


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
