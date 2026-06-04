from __future__ import annotations

import ipaddress
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


def _write_global_config(tmp_path: Path) -> None:
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
            "client_cert_path": "/data/certs/portal",
        },
        "hosts": [],
        "caddy": {"admin_api": "http://caddy:2019"},
        "cloudflare_manager": {"url": "", "api_key": ""},
    }
    (tmp_path / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )


def _setup_ca(tmp_path: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

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
    ca_dir = tmp_path / "certs" / "ca"
    ca_dir.mkdir(parents=True, exist_ok=True)
    (ca_dir / "ca.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    key_path = ca_dir / "ca-key.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)


def _make_valid_csr(node_name: str, address: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, node_name)]))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.IPv4Address(address)),
                    x509.DNSName(node_name),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def _make_admin_app(tmp_path: Path):
    import portal.settings as mod
    from portal.nodes import enroll as enroll_mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    enroll_mod.clear_token_locks()

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    return app


def _make_no_auth_app(tmp_path: Path):
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None

    from portal.app import create_app

    return create_app()


def test_create_token_requires_admin(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_no_auth_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/nodes/token",
            json={"node_name": "pve2-docker", "address": "192.168.1.50"},
        )
    assert resp.status_code == 403


def test_create_token_invalid_name_rejected(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/nodes/token",
            json={"node_name": "../../etc", "address": "192.168.1.50"},
        )
    assert resp.status_code == 422


def test_create_token_returns_token_and_install_cmd(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/nodes/token",
            json={"node_name": "pve2-docker", "address": "192.168.1.50"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert "token" in data
    assert len(data["token"]) >= 32
    assert "install_cmd" in data
    assert "pve2-docker" in data["install_cmd"]
    assert "192.168.1.50" in data["install_cmd"]


def test_enroll_missing_auth_header_returns_422(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)
    csr = _make_valid_csr("pve2-docker", "192.168.1.50")
    with TestClient(app) as client:
        resp = client.post("/admin/nodes/enroll", json={"csr": csr})
    assert resp.status_code == 422  # Authorization header manquant → FastAPI 422


def test_enroll_invalid_token_returns_401(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    _setup_ca(tmp_path)
    app = _make_admin_app(tmp_path)
    csr = _make_valid_csr("pve2-docker", "192.168.1.50")
    with TestClient(app) as client:
        resp = client.post(
            "/admin/nodes/enroll",
            json={"csr": csr},
            headers={"Authorization": "Bearer invalid-token-xyz"},
        )
    assert resp.status_code == 401


def test_enroll_valid_flow_returns_certs_and_updates_config(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    _setup_ca(tmp_path)
    app = _make_admin_app(tmp_path)
    csr = _make_valid_csr("pve2-docker", "192.168.1.50")
    with TestClient(app) as client:
        resp_token = client.post(
            "/admin/nodes/token",
            json={"node_name": "pve2-docker", "address": "192.168.1.50"},
        )
        assert resp_token.status_code == 201
        token = resp_token.json()["token"]

        resp_enroll = client.post(
            "/admin/nodes/enroll",
            json={"csr": csr},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp_enroll.status_code == 200
    data = resp_enroll.json()
    assert "cert_pem" in data
    assert "ca_pem" in data
    assert "BEGIN CERTIFICATE" in data["cert_pem"]
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert any(h["name"] == "pve2-docker" for h in cfg["hosts"])


def test_enroll_token_reuse_returns_401(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    _setup_ca(tmp_path)
    app = _make_admin_app(tmp_path)
    csr = _make_valid_csr("pve2-docker", "192.168.1.50")
    with TestClient(app) as client:
        resp_token = client.post(
            "/admin/nodes/token",
            json={"node_name": "pve2-docker", "address": "192.168.1.50"},
        )
        token = resp_token.json()["token"]
        resp1 = client.post(
            "/admin/nodes/enroll",
            json={"csr": csr},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.status_code == 200
        resp2 = client.post(
            "/admin/nodes/enroll",
            json={"csr": csr},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 401
