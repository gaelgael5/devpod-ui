"""Tests de sign_csr (validation CSR) et enroll_node (tokens + certs en DB)."""
from __future__ import annotations

import hashlib
import ipaddress
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from portal.db.global_config import load_global_db, set_cached_global
from portal.db.node_certs import get_node_cert_db
from portal.db.tables import node_join_tokens
from portal.db.tokens import create_token
from portal.nodes.enroll import CsrValidationError, enroll_node, sign_csr

NODE = "test-node"
ADDR = "192.168.1.100"


def _empty_cfg() -> object:
    """GlobalConfig bootstrap minimale (mêmes champs requis que store.load_global)."""
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig

    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
    )


async def _fake_consume_ok(token: str, conn: object) -> tuple[str, str]:
    return NODE, ADDR


async def _fake_noop_save_global(cfg: object, conn: object) -> None:
    return None


async def _fake_noop_save_cert(**kwargs: object) -> None:
    return None


async def _token_used(conn: AsyncConnection, token: str) -> bool:
    """Retourne le flag ``used`` du join token (source de vérité DB)."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = (
        await conn.execute(
            select(node_join_tokens).where(
                node_join_tokens.c.token_hash == token_hash
            )
        )
    ).mappings().one()
    return bool(row["used"])


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


async def test_enroll_node_updates_config(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    db_conn: AsyncConnection,
) -> None:
    token = await create_token(NODE, ADDR, db_conn)
    result, cfg = await enroll_node(
        token=token, csr_pem=valid_csr.decode(), conn=db_conn
    )
    assert "cert_pem" in result
    assert "ca_pem" in result
    # La config retournée (destinée au cache post-commit) porte le nouveau host,
    # et il est bien écrit sur la MÊME transaction (relu depuis db_conn).
    assert NODE in [h.name for h in cfg.hosts]
    reread = await load_global_db(db_conn)
    assert reread is not None
    assert NODE in [h.name for h in reread.hosts]


async def test_enroll_node_saves_cert_file(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    db_conn: AsyncConnection,
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
    db_engine: AsyncEngine,
) -> None:
    """Un 2e enrôlement du même nœud est rejeté (fail-fast dup check via cache).

    Le cache est rafraîchi après le 1er COMMIT (comme le fait la route), de sorte
    que le fail-fast ``load_global()`` du 2e enrôlement voit le host existant.
    """
    async with db_engine.begin() as conn:
        token1 = await create_token(NODE, ADDR, conn)
        _, cfg = await enroll_node(token=token1, csr_pem=valid_csr.decode(), conn=conn)
    set_cached_global(cfg)  # cohérent avec routes/nodes.py après COMMIT

    async with db_engine.begin() as conn:
        token2 = await create_token(NODE, ADDR, conn)
        with pytest.raises(ValueError, match="already registered"):
            await enroll_node(token=token2, csr_pem=valid_csr.decode(), conn=conn)


# ─── §014 : atomicité token + host + cert-row sur une seule transaction ───────


async def test_enroll_node_commits_token_host_cert_atomically(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    db_engine: AsyncEngine,
) -> None:
    """Chemin nominal : token consommé + host + ligne cert committés ensemble."""
    async with db_engine.begin() as conn:
        token = await create_token(NODE, ADDR, conn)
    async with db_engine.begin() as conn:
        result, _cfg = await enroll_node(
            token=token, csr_pem=valid_csr.decode(), conn=conn
        )
    assert result["node_name"] == NODE

    # Après COMMIT : tout est présent et cohérent.
    async with db_engine.connect() as conn:
        assert await _token_used(conn, token) is True
        cfg_db = await load_global_db(conn)
        assert cfg_db is not None
        assert NODE in [h.name for h in cfg_db.hosts]
        assert await get_node_cert_db(NODE, conn) is not None
        await conn.rollback()


async def test_enroll_node_rolls_back_all_on_cert_row_failure(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    db_engine: AsyncEngine,
) -> None:
    """§014 : si l'écriture de la ligne cert échoue, TOUT rollback ensemble.

    Régression garde-fou : avant le fix, ``save_global`` committait le host sur
    sa propre transaction ; le rollback de la transaction externe rendait le
    token réutilisable ALORS que le host restait committé (split-brain). Ici on
    force l'échec de la dernière écriture DB et on vérifie qu'aucun effet de bord
    ne persiste : token NON consommé, host NON enregistré, pas de ligne cert.
    """
    async with db_engine.begin() as conn:
        token = await create_token(NODE, ADDR, conn)

    with (
        patch(
            "portal.db.node_certs.save_node_cert_db",
            side_effect=RuntimeError("db down"),
        ),
        pytest.raises(RuntimeError, match="db down"),
    ):
        async with db_engine.begin() as conn:
            await enroll_node(token=token, csr_pem=valid_csr.decode(), conn=conn)

    async with db_engine.connect() as conn:
        # Token PAS consommé → toujours réutilisable dans sa TTL (état cohérent :
        # rien n'a eu lieu), et surtout AUCUN host committé en parallèle.
        assert await _token_used(conn, token) is False
        cfg_db = await load_global_db(conn)
        assert cfg_db is None or NODE not in [h.name for h in cfg_db.hosts]
        assert await get_node_cert_db(NODE, conn) is None
        await conn.rollback()

    # L'échec survient AVANT l'écriture disque (placée en dernier) → pas d'orphelin.
    cert_path = tmp_data_root / "certs" / "nodes" / NODE / "server-cert.pem"
    assert not cert_path.exists()


async def test_enroll_node_uses_single_connection_for_all_writes(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§014 — vérif locale (sans Postgres) : consommation du token, enregistrement
    du host et écriture de la ligne cert reçoivent TOUS la même ``conn``.

    C'est l'invariant d'atomicité : aucune écriture n'ouvre de transaction
    séparée. Avant le fix, ``_register_host`` appelait ``save_global`` qui ouvrait
    sa propre transaction — le host n'aurait pas reçu ``sentinel_conn``. Le test
    échoue donc sur l'ancien code et passe sur le nouveau. Il vérifie aussi que
    l'écriture disque est bien effectuée en dernier.
    """
    from unittest.mock import MagicMock

    sentinel_conn = MagicMock(name="conn")
    seen: dict[str, object] = {}

    async def _fake_consume(token: str, conn: object) -> tuple[str, str]:
        seen["token"] = conn
        return NODE, ADDR

    async def _fake_save_global(cfg: object, conn: object) -> None:
        seen["host"] = conn

    async def _fake_save_cert(**kwargs: object) -> None:
        seen["cert"] = kwargs["conn"]

    disk = MagicMock()
    monkeypatch.setattr("portal.nodes.enroll.consume_token_db", _fake_consume)
    monkeypatch.setattr("portal.nodes.enroll.load_global", _empty_cfg)
    monkeypatch.setattr("portal.db.global_config.save_global_db", _fake_save_global)
    monkeypatch.setattr("portal.db.node_certs.save_node_cert_db", _fake_save_cert)
    monkeypatch.setattr("portal.nodes.enroll._save_node_cert", disk)

    result, _cfg = await enroll_node(
        token="tok", csr_pem=valid_csr.decode(), conn=sentinel_conn
    )

    assert seen["token"] is sentinel_conn
    assert seen["host"] is sentinel_conn
    assert seen["cert"] is sentinel_conn
    assert result["node_name"] == NODE
    disk.assert_called_once()  # écriture disque effectuée en dernier


async def test_enroll_node_does_not_mutate_live_cache_before_commit(
    tmp_data_root: Path,
    ca_fixture: tuple[Path, Path],
    valid_csr: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§014 / bug 034 — vérif locale (sans Postgres) : ``enroll_node`` ne mute PAS
    l'objet renvoyé par ``load_global`` (le cache RAM vivant).

    ``load_global()`` renvoie ``get_cached_global()`` — l'objet caché VIVANT, pas
    une copie. Si ``_register_host`` faisait ``cfg.hosts.append(...)`` sur cet
    objet, le cache serait pollué AVANT le COMMIT et resterait pollué sur rollback
    (host fantôme absent de la DB). ``enroll_node`` doit travailler sur une copie ;
    le cache n'est rafraîchi que par la route après COMMIT. On vérifie ici que le
    cfg vivant reste vide et que le cfg retourné (destiné à set_cached_global)
    porte bien le host.
    """
    from unittest.mock import MagicMock

    live = _empty_cfg()
    monkeypatch.setattr("portal.nodes.enroll.consume_token_db", _fake_consume_ok)
    monkeypatch.setattr("portal.nodes.enroll.load_global", lambda: live)
    monkeypatch.setattr(
        "portal.db.global_config.save_global_db", _fake_noop_save_global
    )
    monkeypatch.setattr("portal.db.node_certs.save_node_cert_db", _fake_noop_save_cert)
    monkeypatch.setattr("portal.nodes.enroll._save_node_cert", MagicMock())

    _result, returned_cfg = await enroll_node(
        token="tok", csr_pem=valid_csr.decode(), conn=MagicMock()
    )

    # Le cache vivant n'a PAS été muté par l'enrôlement…
    assert [h.name for h in live.hosts] == []
    # …mais la copie retournée (pour set_cached_global post-COMMIT) porte le host.
    assert [h.name for h in returned_cfg.hosts] == [NODE]
    assert returned_cfg is not live


def test_enroll_node_path_traversal_rejected(tmp_data_root: Path) -> None:
    from portal.nodes.enroll import _safe_node_cert_path

    with pytest.raises(ValueError, match="DNS-safe"):
        _safe_node_cert_path("../ca")

    with pytest.raises(ValueError, match="DNS-safe"):
        _safe_node_cert_path("foo/bar")
