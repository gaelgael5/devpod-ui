"""Tests de sign_csr (validation CSR) et enroll_node (tokens + certs en DB)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.config.models import GlobalConfig
from portal.db.tokens import create_token
from portal.nodes.enroll import CsrValidationError, enroll_node, sign_csr

NODE = "test-node"
ADDR = "192.168.1.100"


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
