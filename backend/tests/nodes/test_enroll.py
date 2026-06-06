from __future__ import annotations

from pathlib import Path

import pytest

from portal.nodes.enroll import CsrValidationError, enroll_node, generate_token, sign_csr


def test_valid_csr_is_signed(
    tmp_data_root: Path, ca_fixture: tuple[Path, Path], valid_csr: bytes
) -> None:
    ca_cert_path, ca_key_path = ca_fixture
    cert_pem, ca_pem = sign_csr(
        csr_pem=valid_csr,
        expected_cn="test-node",
        expected_address="192.168.1.100",
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
            expected_cn="test-node",
            expected_address="192.168.1.100",
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
            expected_cn="test-node",
            expected_address="192.168.1.100",
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
            expected_cn="test-node",
            expected_address="192.168.1.100",
            ca_cert_path=ca_cert_path,
            ca_key_path=ca_key_path,
        )


async def test_enroll_node_updates_config(
    global_config: Path, ca_fixture: tuple[Path, Path], valid_csr: bytes
) -> None:
    import yaml

    token = generate_token("test-node", "192.168.1.100")
    result = await enroll_node(token=token, csr_pem=valid_csr.decode())
    assert "cert_pem" in result
    assert "ca_pem" in result
    cfg_data = yaml.safe_load((global_config / "config.yaml").read_text(encoding="utf-8"))
    host_names = [h["name"] for h in cfg_data.get("hosts", [])]
    assert "test-node" in host_names


async def test_enroll_node_saves_cert_file(
    global_config: Path, ca_fixture: tuple[Path, Path], valid_csr: bytes
) -> None:
    token = generate_token("test-node", "192.168.1.100")
    await enroll_node(token=token, csr_pem=valid_csr.decode())
    cert_path = global_config / "certs" / "nodes" / "test-node" / "server-cert.pem"
    assert cert_path.exists()
    assert b"BEGIN CERTIFICATE" in cert_path.read_bytes()


async def test_enroll_node_duplicate_rejected(
    global_config: Path, ca_fixture: tuple[Path, Path], valid_csr: bytes
) -> None:
    token1 = generate_token("test-node", "192.168.1.100")
    await enroll_node(token=token1, csr_pem=valid_csr.decode())
    token2 = generate_token("test-node", "192.168.1.100")
    with pytest.raises(ValueError, match="already registered"):
        await enroll_node(token=token2, csr_pem=valid_csr.decode())


async def test_enroll_node_path_traversal_rejected(
    global_config: Path, ca_fixture: tuple[Path, Path]
) -> None:
    from portal.nodes.enroll import _safe_node_cert_path

    with pytest.raises(ValueError, match="DNS-safe"):
        _safe_node_cert_path("../ca")

    with pytest.raises(ValueError, match="DNS-safe"):
        _safe_node_cert_path("foo/bar")
