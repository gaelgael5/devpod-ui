# M4 — Node Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à un admin d'enrôler des nœuds Docker via join token + signature CSR, produisant des daemons Docker configurés mTLS et pilotables par le portail.

**Architecture:** Deux endpoints FastAPI sous `/admin/nodes/` — l'un (auth session admin) émet des tokens usage-unique hashés avec TTL, l'autre (auth Bearer join token) accepte une CSR PEM, valide CN/SAN/no-CA-flag, signe avec la CA du portail, met à jour config.yaml atomiquement et sauvegarde le cert. Un script bash (`scripts/install-node.sh`) tourne sur le nœud : installe Docker, force NTP, génère une clé privée locale + CSR, appelle l'endpoint d'enrôlement, configure le daemon mTLS avec un drop-in systemd, et verrouille le pare-feu.

**Tech Stack:** Python `cryptography>=42.0`, `secrets.token_urlsafe`, `hashlib.sha256`, `asyncio.Lock`, `tempfile` + `os.replace` (écritures atomiques), Bash + OpenSSL + curl + jq (script install).

**Contraintes critiques :**
- §E-27 : token aléatoire, stocké hashé, usage unique, TTL court
- §E-28 : valider CN/SAN/pas CA:TRUE avant signature
- §E-29 : validité 1825 jours (5 ans), documenter la date
- §A-1 : drop-in systemd pour neutraliser `-H fd://`
- §A-2 : SAN = IP ET hostname du nœud
- §A-3 : NTP AVANT génération du cert
- §A-4 : mTLS — daemon n'accepte que clients porteurs d'un cert signé par la CA
- §A-5 : port 2376 uniquement depuis l'IP du portail

**Note :** `ca/ca.pem` et `ca/ca-key.pem` sont créés en M5. Les tests M4 utilisent une CA fixture générée in-memory.

---

## Fichiers

```
Créer  backend/src/portal/nodes/__init__.py
Créer  backend/src/portal/nodes/enroll.py
Créer  backend/src/portal/routes/nodes.py
Modif  backend/src/portal/app.py
Modif  backend/pyproject.toml
Créer  backend/tests/nodes/__init__.py
Créer  backend/tests/nodes/conftest.py
Créer  backend/tests/nodes/test_token.py
Créer  backend/tests/nodes/test_enroll.py
Créer  backend/tests/routes/test_nodes.py
Créer  scripts/install-node.sh
```

---

### Task 0 : Ajouter la dépendance `cryptography`

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1 : Ajouter `cryptography>=42.0`**

Dans `backend/pyproject.toml`, sous `[project]` → `dependencies` :

```toml
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "structlog>=24.0",
    "fastapi[standard]>=0.111",
    "authlib>=1.3",
    "joserfc>=1.7",
    "itsdangerous>=2.1",
    "cryptography>=42.0",
]
```

- [ ] **Step 2 : Synchroniser**

```bash
cd backend && uv sync
```

Attendu : résolution sans erreur, `cryptography` présent dans l'env.

- [ ] **Step 3 : Vérifier l'import**

```bash
cd backend && uv run python -c "from cryptography import x509; print('ok')"
```

Attendu : `ok`

- [ ] **Step 4 : Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore: ajoute cryptography pour signature CSR (M4)"
```

---

### Task 1 : Gestion des join tokens (`nodes/enroll.py` — partie tokens)

**Files:**
- Create: `backend/src/portal/nodes/__init__.py`
- Create: `backend/src/portal/nodes/enroll.py` (fonctions token uniquement)
- Create: `backend/tests/nodes/__init__.py`
- Create: `backend/tests/nodes/conftest.py`
- Create: `backend/tests/nodes/test_token.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `backend/tests/nodes/__init__.py` (vide).

Créer `backend/tests/nodes/conftest.py` :

```python
from __future__ import annotations

from pathlib import Path

import pytest


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
```

Créer `backend/tests/nodes/test_token.py` :

```python
from __future__ import annotations

from pathlib import Path

import pytest

from portal.nodes.enroll import consume_token, generate_token


def test_generate_token_returns_nonempty_string(tmp_data_root: Path) -> None:
    token = generate_token("pve2-docker", "192.168.1.50")
    assert len(token) >= 32


async def test_consume_token_returns_node_info(tmp_data_root: Path) -> None:
    token = generate_token("pve2-docker", "192.168.1.50")
    node_name, address = await consume_token(token)
    assert node_name == "pve2-docker"
    assert address == "192.168.1.50"


async def test_consume_token_reuse_raises(tmp_data_root: Path) -> None:
    token = generate_token("pve2-docker", "192.168.1.50")
    await consume_token(token)
    with pytest.raises(ValueError, match="already used"):
        await consume_token(token)


async def test_consume_token_expired_raises(
    tmp_data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import portal.nodes.enroll as enroll_mod
    monkeypatch.setattr(enroll_mod, "_TOKEN_TTL_SECONDS", -1)
    token = generate_token("pve2-docker", "192.168.1.50")
    with pytest.raises(ValueError, match="expired"):
        await consume_token(token)


async def test_consume_unknown_token_raises(tmp_data_root: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        await consume_token("nonexistent-token-that-does-not-exist")
```

- [ ] **Step 2 : Lancer les tests — doivent échouer**

```bash
cd backend && uv run pytest tests/nodes/test_token.py -v
```

Attendu : `ModuleNotFoundError` (portal.nodes.enroll introuvable).

- [ ] **Step 3 : Créer `nodes/__init__.py`**

Créer `backend/src/portal/nodes/__init__.py` (fichier vide).

- [ ] **Step 4 : Implémenter la gestion des tokens dans `nodes/enroll.py`**

Créer `backend/src/portal/nodes/enroll.py` :

```python
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from ..config.store import _data_root

_log = structlog.get_logger(__name__)

# §E-27 : TTL court pour les tokens de join
_TOKEN_TTL_SECONDS = 3600  # 1h

_token_locks: dict[str, asyncio.Lock] = {}


def clear_token_locks() -> None:
    _token_locks.clear()


def _token_dir() -> Path:
    return _data_root() / "tokens"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token_path(token: str) -> Path:
    return _token_dir() / f"{_token_hash(token)}.json"


def _get_token_lock(token: str) -> asyncio.Lock:
    return _token_locks.setdefault(_token_hash(token), asyncio.Lock())


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def generate_token(node_name: str, address: str) -> str:
    """Génère un token aléatoire et le stocke hashé avec TTL. §E-27."""
    token = secrets.token_urlsafe(32)
    data: dict[str, Any] = {
        "node_name": node_name,
        "address": address,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(seconds=_TOKEN_TTL_SECONDS)
        ).isoformat(),
        "used": False,
    }
    _atomic_write_json(_token_path(token), data)
    _log.info("join_token_generated", node_name=node_name)
    return token


async def consume_token(token: str) -> tuple[str, str]:
    """Valide et consomme un join token. Retourne (node_name, address). §E-27."""
    async with _get_token_lock(token):
        path = _token_path(token)
        if not path.exists():
            raise ValueError("Token not found or already used")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("used"):
            raise ValueError("Token already used")
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            raise ValueError("Token expired")
        data["used"] = True
        _atomic_write_json(path, data)
        _log.info("join_token_consumed", node_name=data["node_name"])
        return data["node_name"], data["address"]
```

- [ ] **Step 5 : Lancer les tests — doivent passer**

```bash
cd backend && uv run pytest tests/nodes/test_token.py -v
```

Attendu : 5 passed.

- [ ] **Step 6 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/nodes/ tests/nodes/ && uv run ruff format --check src/portal/nodes/ tests/nodes/ && uv run mypy src/
```

Attendu : aucune erreur.

- [ ] **Step 7 : Commit**

```bash
git add backend/src/portal/nodes/ backend/tests/nodes/
git commit -m "feat(M4): join tokens à usage unique hashés avec TTL (§E-27)"
```

---

### Task 2 : Validation CSR, signature et enregistrement du nœud

**Files:**
- Modify: `backend/src/portal/nodes/enroll.py` (ajouter les fonctions crypto + register)
- Modify: `backend/tests/nodes/conftest.py` (ajouter fixtures CA + CSR)
- Create: `backend/tests/nodes/test_enroll.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Compléter `backend/tests/nodes/conftest.py` — ajouter après les fixtures existantes :

```python
import ipaddress as _ipmod

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from datetime import datetime, timedelta, timezone


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
    """Génère une CA auto-signée de test dans tmp_data_root/ca/."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.now(timezone.utc)
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
    ca_dir = tmp_data_root / "ca"
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
```

Créer `backend/tests/nodes/test_enroll.py` :

```python
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
```

- [ ] **Step 2 : Lancer les tests — doivent échouer**

```bash
cd backend && uv run pytest tests/nodes/test_enroll.py -v
```

Attendu : `ImportError` (CsrValidationError, sign_csr, enroll_node manquants).

- [ ] **Step 3 : Ajouter les fonctions crypto et register dans `nodes/enroll.py`**

Ajouter à la fin de `backend/src/portal/nodes/enroll.py` (après les fonctions token) :

```python
# ─── CSR validation & signing ────────────────────────────────────────────────

import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from ..config.models import HostConfig
from ..config.store import load_global, save_global


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
            raise CsrValidationError(
                f"CSR SAN must contain {expected_address!r}"
            )
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

    now = datetime.now(timezone.utc)
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
        .sign(ca_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM), ca_cert_pem


# ─── Node registration ────────────────────────────────────────────────────────


def _safe_node_cert_path(node_name: str) -> Path:
    base = _data_root() / "certs" / "nodes"
    path = base / node_name / "server-cert.pem"
    if not path.is_relative_to(base):
        raise ValueError(f"node_name {node_name!r} escapes cert directory")
    return path


def _save_node_cert(node_name: str, cert_pem: bytes) -> None:
    cert_path = _safe_node_cert_path(node_name)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=cert_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(cert_pem)
        os.replace(tmp_path, cert_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _register_host(node_name: str, address: str) -> None:
    """Ajoute le nœud dans config.yaml global — écriture atomique."""
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
    save_global(cfg)
    _log.info("node_host_registered", node_name=node_name, address=address)


async def enroll_node(token: str, csr_pem: str) -> dict[str, str]:
    """Consomme le token, valide + signe la CSR, enregistre le nœud."""
    node_name, address = await consume_token(token)
    ca_cert_path = _data_root() / "ca" / "ca.pem"
    ca_key_path = _data_root() / "ca" / "ca-key.pem"
    cert_pem, ca_pem = sign_csr(
        csr_pem=csr_pem.encode(),
        expected_cn=node_name,
        expected_address=address,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )
    _save_node_cert(node_name, cert_pem)
    _register_host(node_name, address)
    return {
        "cert_pem": cert_pem.decode(),
        "ca_pem": ca_pem.decode(),
        "node_name": node_name,
    }
```

**Important :** ajouter les imports manquants en tête de fichier (ils doivent rejoindre les imports existants — pas dupliqués) :

```python
# À ajouter dans le bloc d'imports existant :
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from ..config.models import HostConfig
from ..config.store import load_global, save_global
```

- [ ] **Step 4 : Lancer les tests — doivent passer**

```bash
cd backend && uv run pytest tests/nodes/ -v
```

Attendu : tous les tests passent (token + enroll).

- [ ] **Step 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/nodes/ tests/nodes/ && uv run ruff format --check src/portal/nodes/ tests/nodes/ && uv run mypy src/
```

Attendu : aucune erreur.

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/nodes/enroll.py backend/tests/nodes/
git commit -m "feat(M4): validation CSR + signature + enregistrement nœud (§E-28, §E-29)"
```

---

### Task 3 : Endpoints API (`routes/nodes.py`)

**Files:**
- Create: `backend/src/portal/routes/nodes.py`
- Modify: `backend/src/portal/app.py`
- Create: `backend/tests/routes/test_nodes.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `backend/tests/routes/test_nodes.py` :

```python
from __future__ import annotations

import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
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
    now = datetime.now(timezone.utc)
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
    ca_dir = tmp_path / "ca"
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
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.IPv4Address(address)),
                x509.DNSName(node_name),
            ]),
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

    return create_app()  # pas de require_admin override → 403


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
        # Premier enrôlement
        resp1 = client.post(
            "/admin/nodes/enroll",
            json={"csr": csr},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.status_code == 200
        # Réutilisation du même token → 401
        resp2 = client.post(
            "/admin/nodes/enroll",
            json={"csr": csr},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 401
```

- [ ] **Step 2 : Lancer les tests — doivent échouer**

```bash
cd backend && uv run pytest tests/routes/test_nodes.py -v
```

Attendu : `ImportError` ou 404 (routes non enregistrées).

- [ ] **Step 3 : Créer `routes/nodes.py`**

Créer `backend/src/portal/routes/nodes.py` :

```python
from __future__ import annotations

import ipaddress
import re

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

from ..auth.rbac import UserInfo, require_admin
from ..config.store import load_global
from ..nodes.enroll import CsrValidationError, enroll_node, generate_token

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["nodes"])

_NODE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
)


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_name: str
    address: str

    @field_validator("node_name")
    @classmethod
    def validate_node_name(cls, v: str) -> str:
        if not _NODE_NAME_RE.fullmatch(v):
            raise ValueError(
                f"node_name '{v}' must match ^[a-z0-9][a-z0-9-]{{0,30}}[a-z0-9]$"
            )
        return v

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        if _HOSTNAME_RE.fullmatch(v):
            return v
        raise ValueError(f"address '{v}' is not a valid IP address or hostname")


class EnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csr: str


@router.post("/nodes/token", status_code=201)
async def create_join_token(
    req: TokenRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, str]:
    """Génère un join token à usage unique pour enrôler un nœud. §E-27."""
    token = generate_token(node_name=req.node_name, address=req.address)
    cfg = load_global()
    ext = cfg.server.external_url
    install_cmd = (
        f"curl -sSL {ext}/install-node.sh | bash -s -- "
        f"--portal {ext} --token {token} "
        f"--node-name {req.node_name} --address {req.address}"
    )
    _log.info("join_token_created", node_name=req.node_name, by=user.login)
    return {"token": token, "expires_in": "3600s", "install_cmd": install_cmd}


@router.post("/nodes/enroll")
async def enroll_node_endpoint(
    req: EnrollRequest,
    authorization: str = Header(...),
) -> dict[str, str]:
    """Enrôlement : auth Bearer join token (pas de session OIDC). §E-27, §E-28."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization[len("Bearer "):]
    try:
        result = await enroll_node(token=token, csr_pem=req.csr)
    except CsrValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        _log.error("enroll_ca_unavailable", error=str(exc))
        raise HTTPException(status_code=500, detail="CA not available") from exc
    return result
```

- [ ] **Step 4 : Enregistrer le router dans `app.py`**

Dans `backend/src/portal/app.py`, ajouter l'import :

```python
from .routes.nodes import router as nodes_router
```

Et dans `create_app()`, ajouter après `app.include_router(admin_router, prefix="/admin")` :

```python
app.include_router(nodes_router, prefix="/admin")
```

- [ ] **Step 5 : Lancer les tests — doivent passer**

```bash
cd backend && uv run pytest tests/routes/test_nodes.py tests/nodes/ -v
```

Attendu : tous les tests passent.

- [ ] **Step 6 : Tous les tests du projet**

```bash
cd backend && uv run pytest -v
```

Attendu : tous les tests passent (aucune régression).

- [ ] **Step 7 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/
```

Attendu : aucune erreur.

- [ ] **Step 8 : Commit**

```bash
git add backend/src/portal/routes/nodes.py backend/src/portal/app.py backend/tests/routes/test_nodes.py
git commit -m "feat(M4): endpoints POST /admin/nodes/token et /admin/nodes/enroll"
```

---

### Task 4 : `scripts/install-node.sh`

**Files:**
- Create: `scripts/install-node.sh`

- [ ] **Step 1 : Créer le script**

Créer `scripts/install-node.sh` :

```bash
#!/usr/bin/env bash
# install-node.sh — Enrôle un nœud Docker dans le portail workspace
# Usage : curl -sSL https://dev.yoops.org/install-node.sh | bash -s -- \
#           --portal URL --token TOKEN --node-name NAME --address ADDR
#
# Pièges implémentés : §A-1 (systemd drop-in), §A-2 (SAN), §A-3 (NTP avant cert),
#                      §A-4 (mTLS), §A-5 (pare-feu)
set -euo pipefail

PORTAL=""
TOKEN=""
NODE_NAME=""
ADDRESS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --portal)    PORTAL="$2";    shift 2 ;;
        --token)     TOKEN="$2";     shift 2 ;;
        --node-name) NODE_NAME="$2"; shift 2 ;;
        --address)   ADDRESS="$2";   shift 2 ;;
        *) echo "Argument inconnu : $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$PORTAL" || -z "$TOKEN" || -z "$NODE_NAME" || -z "$ADDRESS" ]]; then
    echo "Usage : $0 --portal URL --token TOKEN --node-name NAME --address ADDR" >&2
    exit 1
fi

TLS_DIR=/etc/docker/tls
mkdir -p "$TLS_DIR"

echo "==> Vérification des outils requis..."
for cmd in curl jq openssl timedatectl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR : $cmd est requis mais introuvable. Installez-le d'abord." >&2
        exit 1
    fi
done

# 1. Installation de Docker (idempotente)
echo "==> Installation Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
else
    echo "    Docker déjà installé : $(docker --version)"
fi

# 2. Forcer NTP AVANT la génération du cert (§A-3)
# Un cert généré avec une horloge dérivée sera rejeté immédiatement.
echo "==> Synchronisation NTP..."
timedatectl set-ntp true
sleep 3  # laisse ntpd se synchroniser
timedatectl status | grep -E "NTP|synchronized" || true

# 3. Générer la clé privée — elle ne quitte JAMAIS le nœud (§A-2, principe)
echo "==> Génération de la clé privée serveur..."
if [[ ! -f "$TLS_DIR/server-key.pem" ]]; then
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \
        -out "$TLS_DIR/server-key.pem"
fi
chmod 600 "$TLS_DIR/server-key.pem"

# 4. Générer la CSR avec CN=NODE_NAME et SAN=IP+DNS (§A-2)
echo "==> Génération de la CSR avec SAN..."
OPENSSL_CONF=$(mktemp)
CSR_FILE=$(mktemp --suffix=.csr.pem)
trap 'rm -f "$OPENSSL_CONF" "$CSR_FILE"' EXIT

cat > "$OPENSSL_CONF" <<CONF
[req]
req_extensions   = v3_req
distinguished_name = dn
prompt           = no

[dn]
CN = ${NODE_NAME}

[v3_req]
subjectAltName = @san

[san]
CONF

# Détecter IP vs hostname pour le SAN (§A-2)
if [[ "$ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf 'IP.1 = %s\n' "$ADDRESS" >> "$OPENSSL_CONF"
else
    printf 'DNS.1 = %s\n' "$ADDRESS" >> "$OPENSSL_CONF"
fi
printf 'DNS.2 = %s\n' "$NODE_NAME" >> "$OPENSSL_CONF"

openssl req -new \
    -key "$TLS_DIR/server-key.pem" \
    -out "$CSR_FILE" \
    -config "$OPENSSL_CONF"

# 5. Appeler l'endpoint d'enrôlement
echo "==> Enrôlement auprès du portail..."
CSR_PEM=$(cat "$CSR_FILE")
RESPONSE=$(curl -sSf -X POST \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg csr "$CSR_PEM" '{"csr": $csr}')" \
    "${PORTAL}/admin/nodes/enroll")

# 6. Sauvegarder le cert et la CA
echo "$RESPONSE" | jq -r '.cert_pem' > "$TLS_DIR/server-cert.pem"
echo "$RESPONSE" | jq -r '.ca_pem'   > "$TLS_DIR/ca.pem"
echo "    Cert sauvegardé dans $TLS_DIR/"

# 7. Écrire daemon.json (§A-4 mTLS)
echo "==> Configuration daemon Docker mTLS..."
cat > /etc/docker/daemon.json <<DAEMON
{
  "hosts":      ["tcp://0.0.0.0:2376", "unix:///var/run/docker.sock"],
  "tls":        true,
  "tlsverify":  true,
  "tlscacert":  "${TLS_DIR}/ca.pem",
  "tlscert":    "${TLS_DIR}/server-cert.pem",
  "tlskey":     "${TLS_DIR}/server-key.pem"
}
DAEMON

# 8. Drop-in systemd pour neutraliser -H fd:// (§A-1 — LE piège qui bloque le restart)
# Sans ce drop-in, daemon.json + systemd provoque :
#   "unable to configure the Docker daemon ... conflicting options"
echo "==> Drop-in systemd (neutralise -H fd://)..."
OVERRIDE_DIR=/etc/systemd/system/docker.service.d
mkdir -p "$OVERRIDE_DIR"
cat > "$OVERRIDE_DIR/override.conf" <<OVERRIDE
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd
OVERRIDE
systemctl daemon-reload

# 9. Pare-feu : port 2376 uniquement depuis l'IP du portail (§A-5)
echo "==> Configuration du pare-feu..."
PORTAL_HOST=$(echo "$PORTAL" | sed 's|https\?://||;s|[:/].*||')
PORTAL_IP=$(getent hosts "$PORTAL_HOST" 2>/dev/null | awk '{print $1}' | head -1 || true)
if [[ -z "$PORTAL_IP" ]]; then
    echo "    ATTENTION : impossible de résoudre $PORTAL_HOST." >&2
    echo "    Restreignez manuellement le port 2376 à l'IP du portail." >&2
elif command -v ufw &>/dev/null; then
    ufw allow from "$PORTAL_IP" to any port 2376 comment "docker-tls portal" || true
    echo "    ufw : port 2376 autorisé depuis $PORTAL_IP"
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent \
        --add-rich-rule="rule family=ipv4 source address=${PORTAL_IP} port port=2376 protocol=tcp accept" || true
    firewall-cmd --reload
    echo "    firewalld : port 2376 autorisé depuis $PORTAL_IP"
else
    echo "    ATTENTION : aucun outil pare-feu détecté (ufw/firewall-cmd)." >&2
    echo "    Restreignez manuellement le port 2376 à $PORTAL_IP." >&2
fi

# 10. Redémarrer Docker avec la config mTLS
echo "==> Redémarrage Docker..."
systemctl restart docker

# 11. Vérification locale
sleep 2
if ss -tlnp 2>/dev/null | grep -q ':2376'; then
    echo "==> OK : daemon Docker mTLS en écoute sur le port 2376"
else
    echo "==> ERREUR : Docker n'écoute pas sur le port 2376." >&2
    echo "    Diagnostiquer : journalctl -u docker --no-pager -n 50" >&2
    exit 1
fi

echo ""
echo "Nœud ${NODE_NAME} enrôlé avec succès."
echo "Testez depuis le portail avec : devpod up --provider docker ..."
echo "Cert valide 1825 jours (§E-29). Renouvellement à prévoir avant expiration."
```

- [ ] **Step 2 : Rendre le script exécutable**

```bash
chmod +x scripts/install-node.sh
```

- [ ] **Step 3 : Vérifier la syntaxe bash**

```bash
bash -n scripts/install-node.sh && echo "Syntaxe OK"
```

Attendu : `Syntaxe OK`

- [ ] **Step 4 : Vérifier que shellcheck ne trouve pas d'erreurs bloquantes**

```bash
shellcheck scripts/install-node.sh || true
```

Corriger tout SC2 ou SC1 signalé.

- [ ] **Step 5 : Suite de tests complète**

```bash
cd backend && uv run pytest -v
```

Attendu : tous les tests passent (aucune régression).

- [ ] **Step 6 : Commit**

```bash
git add scripts/install-node.sh
git commit -m "feat(M4): script install-node.sh idempotent avec mTLS + pare-feu (§A-1..§A-5)"
```

---

## Vérification finale

- [ ] `uv run pytest -v` — tous les tests verts
- [ ] `uv run ruff check src/ tests/` — aucune erreur lint
- [ ] `uv run mypy src/` — aucune erreur de types
- [ ] `bash -n scripts/install-node.sh` — syntaxe bash OK
- [ ] Aucun secret dans `git diff` (tokens, clés)
- [ ] Le token d'enrôlement est bien stocké hashé (vérifier `_data_root()/tokens/*.json` en test)
- [ ] La réutilisation d'un token retourne bien 401

## Repli documenté

Si la gestion CA s'avère trop lourde en intégration (M5 absent), le provider `ssh` (script crée user `devpod` + groupe `docker` + `authorized_keys`) est l'alternative. **Ne pas l'implémenter ici** — l'utiliser seulement si le provider docker-tls est bloquant après M5.
