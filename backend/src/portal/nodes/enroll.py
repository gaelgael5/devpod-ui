from __future__ import annotations

import contextlib
import ipaddress
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import HostConfig
from ..config.store import _data_root, load_global, save_global
from ..db.tokens import consume_token as consume_token_db

_log = structlog.get_logger(__name__)

# Noms de nœuds DNS-safe : 2-32 caractères, alphanum + tiret, sans tiret en tête/queue
_NODE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


# ─── CSR validation & signing ────────────────────────────────────────────────


class CsrValidationError(ValueError):
    """CSR invalide ou non conforme. §E-28."""


def _address_in_san(san: x509.SubjectAlternativeName, address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
        return any(isinstance(n, x509.IPAddress) and n.value == ip for n in san)
    except ValueError:
        return any(isinstance(n, x509.DNSName) and n.value == address for n in san)


def _validate_csr(
    csr: x509.CertificateSigningRequest,
    expected_cn: str,
    expected_address: str,
) -> None:
    """Valide CN, SAN et l'absence de CA:TRUE. §E-28."""
    if not csr.is_signature_valid:
        raise CsrValidationError("CSR has an invalid signature")
    cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    actual_cn = cn_attrs[0].value if cn_attrs else ""
    if actual_cn != expected_cn:
        raise CsrValidationError(f"CSR CN must be {expected_cn!r}, got {actual_cn!r}")

    try:
        bc = csr.extensions.get_extension_for_class(x509.BasicConstraints)
        if bc.value.ca:
            raise CsrValidationError("CSR must not have basicConstraints CA:TRUE")
    except x509.ExtensionNotFound:
        pass

    try:
        san_ext = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        if not _address_in_san(san_ext.value, expected_address):
            raise CsrValidationError(f"CSR SAN must contain {expected_address!r}")
    except x509.ExtensionNotFound:
        raise CsrValidationError(
            "CSR must have a SAN extension containing the expected address"
        ) from None


# §E-29 : validité 5 ans (1825 j). Renouvellement à prévoir avant expiration.
_CERT_VALIDITY_DAYS = 1825


def sign_csr(
    csr_pem: bytes,
    expected_cn: str,
    expected_address: str,
    ca_cert_path: Path,
    ca_key_path: Path,
) -> tuple[bytes, bytes]:
    """Valide et signe la CSR. Retourne (cert_pem, ca_cert_pem). §E-28, §E-29."""
    csr = x509.load_pem_x509_csr(csr_pem)
    _validate_csr(csr, expected_cn, expected_address)

    ca_cert_pem = ca_cert_path.read_bytes()
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)

    now = datetime.now(UTC)
    san_ext = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(san_ext.value, critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())  # type: ignore[arg-type]
    )
    return cert.public_bytes(serialization.Encoding.PEM), ca_cert_pem


# ─── Node registration ────────────────────────────────────────────────────────


def _safe_node_cert_path(node_name: str) -> Path:
    if not _NODE_NAME_RE.fullmatch(node_name):
        raise ValueError(f"node_name {node_name!r} is not DNS-safe")
    base = _data_root() / "certs" / "nodes"
    path = base / node_name / "server-cert.pem"
    if not path.is_relative_to(base):
        raise ValueError(f"node_name {node_name!r} escapes cert directory")
    return path


def _save_node_cert(node_name: str, cert_pem: bytes) -> None:
    cert_path = _safe_node_cert_path(node_name)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(cert_path.parent, 0o700)
    fd, tmp_path = tempfile.mkstemp(dir=cert_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(cert_pem)
        os.replace(tmp_path, cert_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


async def _register_host(node_name: str, address: str) -> None:
    """Ajoute le nœud dans global_config en DB."""
    cfg = load_global()
    if any(h.name == node_name for h in cfg.hosts):
        raise ValueError(f"Host {node_name!r} already registered — delete it first")
    cfg.hosts.append(
        HostConfig(
            name=node_name,
            default=False,
            type="docker-tls",
            docker_host=f"tcp://{address}:2376",
        )
    )
    await save_global(cfg)
    _log.info("node_host_registered", node_name=node_name, address=address)


async def enroll_node(token: str, csr_pem: str, conn: AsyncConnection) -> dict[str, str]:
    """Consomme le token, valide + signe la CSR, enregistre le nœud."""
    from ..db.node_certs import save_node_cert_db

    node_name, address = await consume_token_db(token, conn)
    _log.info("join_token_consumed", node_name=node_name)

    # Vérification fail-fast avant toute écriture (§E-28 + cohérence d'état)
    cfg = load_global()
    if any(h.name == node_name for h in cfg.hosts):
        raise ValueError(f"Host {node_name!r} already registered — delete it first")

    ca_cert_path = _data_root() / "certs" / "ca" / "ca.pem"
    ca_key_path = _data_root() / "certs" / "ca" / "ca-key.pem"
    cert_pem, ca_pem = sign_csr(
        csr_pem=csr_pem.encode(),
        expected_cn=node_name,
        expected_address=address,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )
    _save_node_cert(node_name, cert_pem)
    await _register_host(node_name, address)

    # Persistance en DB : extraction des métadonnées depuis le certificat signé
    cert_obj = x509.load_pem_x509_certificate(cert_pem)
    serial_hex = format(cert_obj.serial_number, "x")
    signed_at = cert_obj.not_valid_before_utc
    expires_at = cert_obj.not_valid_after_utc
    await save_node_cert_db(
        node_name=node_name,
        address=address,
        cert_pem=cert_pem.decode(),
        serial_number=serial_hex,
        signed_at=signed_at,
        expires_at=expires_at,
        conn=conn,
    )

    return {
        "cert_pem": cert_pem.decode(),
        "ca_pem": ca_pem.decode(),
        "node_name": node_name,
    }
