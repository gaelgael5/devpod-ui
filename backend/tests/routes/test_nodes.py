"""Tests des routes /admin/nodes/* : join token + enrôlement via le flux DB.

Le flux fichier (config.yaml) a été remplacé par la persistance PostgreSQL :
tokens via portal.db.tokens (SELECT FOR UPDATE), config via global_config (cache
RAM). Les patterns fixtures viennent de tests/nodes/ (CA, CSR, patched save_global).
"""
from __future__ import annotations

import ipaddress
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.middleware.sessions import SessionMiddleware

from portal.config.models import GlobalConfig

NODE = "pve2-docker"
ADDR = "192.168.1.50"


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_global_cache() -> Iterator[None]:
    """Invalide le cache RAM de la GlobalConfig avant et après chaque test.

    enroll_node et la route token lisent la config via load_global() (cache DB) :
    sans invalidation, un test précédent fausserait l'isolation.
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


def _make_valid_csr(node_name: str, address: str) -> str:
    """CSR conforme : CN = node_name, SAN = IP + DNS (mêmes règles que install-node.sh)."""
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


def _build_app(db_conn: AsyncConnection, *, admin: bool) -> FastAPI:
    """App minimale avec le seul routeur nodes — évite le lifespan complet.

    SessionMiddleware est requis : require_admin lit request.session (401 si vide).
    """
    from portal.auth.rbac import UserInfo, require_admin
    from portal.db.engine import get_conn
    from portal.routes.nodes import router as nodes_router

    app = FastAPI()
    app.include_router(nodes_router, prefix="/admin")
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-32chars-minimum!!")
    app.dependency_overrides[get_conn] = lambda: db_conn
    if admin:
        app.dependency_overrides[require_admin] = lambda: UserInfo(
            login="admin", roles=["admin"]
        )
    return app


@pytest.fixture
async def admin_client(db_conn: AsyncConnection) -> AsyncGenerator[AsyncClient, None]:
    app = _build_app(db_conn, admin=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def anon_client(db_conn: AsyncConnection) -> AsyncGenerator[AsyncClient, None]:
    app = _build_app(db_conn, admin=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ─── POST /admin/nodes/token ──────────────────────────────────────────────────


async def test_create_token_requires_admin(anon_client: AsyncClient) -> None:
    resp = await anon_client.post(
        "/admin/nodes/token", json={"node_name": NODE, "address": ADDR}
    )
    assert resp.status_code == 401


async def test_create_token_invalid_name_rejected(admin_client: AsyncClient) -> None:
    # validation regex stricte avant tout usage en chemin / --id / hostname
    resp = await admin_client.post(
        "/admin/nodes/token", json={"node_name": "../../etc", "address": ADDR}
    )
    assert resp.status_code == 422


async def test_create_token_returns_token_and_install_cmd(
    admin_client: AsyncClient, db_conn: AsyncConnection
) -> None:
    resp = await admin_client.post(
        "/admin/nodes/token", json={"node_name": NODE, "address": ADDR}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["token"]) >= 32
    assert NODE in data["install_cmd"]
    assert ADDR in data["install_cmd"]

    # le token est bien persisté (hashé) en DB : consommable une fois
    from portal.db.tokens import consume_token

    assert await consume_token(data["token"], db_conn) == (NODE, ADDR)


# ─── POST /admin/nodes/enroll ─────────────────────────────────────────────────


async def test_enroll_missing_auth_header_returns_422(admin_client: AsyncClient) -> None:
    csr = _make_valid_csr(NODE, ADDR)
    resp = await admin_client.post("/admin/nodes/enroll", json={"csr": csr})
    assert resp.status_code == 422  # Header Authorization manquant → FastAPI 422


async def test_enroll_invalid_token_returns_401(admin_client: AsyncClient) -> None:
    csr = _make_valid_csr(NODE, ADDR)
    resp = await admin_client.post(
        "/admin/nodes/enroll",
        json={"csr": csr},
        headers={"Authorization": "Bearer invalid-token-xyz"},
    )
    assert resp.status_code == 401


async def test_enroll_valid_flow_returns_certs_and_updates_config(
    admin_client: AsyncClient,
    db_conn: AsyncConnection,
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    patched_save_global: None,
) -> None:
    csr = _make_valid_csr(NODE, ADDR)
    resp_token = await admin_client.post(
        "/admin/nodes/token", json={"node_name": NODE, "address": ADDR}
    )
    assert resp_token.status_code == 201
    token = resp_token.json()["token"]

    resp_enroll = await admin_client.post(
        "/admin/nodes/enroll",
        json={"csr": csr},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_enroll.status_code == 200
    data = resp_enroll.json()
    assert "BEGIN CERTIFICATE" in data["cert_pem"]
    assert "BEGIN CERTIFICATE" in data["ca_pem"]

    # le nœud est enregistré dans la GlobalConfig en DB (remplace config.yaml)
    from portal.db.global_config import load_global_db

    cfg = await load_global_db(db_conn)
    assert cfg is not None
    assert NODE in [h.name for h in cfg.hosts]

    # le certificat serveur est écrit sous /data/certs/nodes/<node>/
    cert_path = tmp_data_root / "certs" / "nodes" / NODE / "server-cert.pem"
    assert cert_path.exists()


async def test_enroll_token_reuse_returns_401(
    admin_client: AsyncClient,
    db_conn: AsyncConnection,
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    patched_save_global: None,
) -> None:
    csr = _make_valid_csr(NODE, ADDR)
    resp_token = await admin_client.post(
        "/admin/nodes/token", json={"node_name": NODE, "address": ADDR}
    )
    token = resp_token.json()["token"]

    resp1 = await admin_client.post(
        "/admin/nodes/enroll",
        json={"csr": csr},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200

    # usage unique : le token consommé est refusé (SELECT FOR UPDATE + used=True)
    resp2 = await admin_client.post(
        "/admin/nodes/enroll",
        json={"csr": csr},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 401
