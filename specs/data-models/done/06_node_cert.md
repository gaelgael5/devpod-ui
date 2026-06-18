# 06 — Certificats X.509 nœuds

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | Certificat signé par la CA interne |
| Chemin | `/data/certs/nodes/{node_name}/server-cert.pem` |
| Fonction | `nodes/enroll.py :: _save_node_cert()` |
| Format | PEM |
| Écriture | Atomique : tempfile + `os.replace()` |

Généré lors de l'enrôlement d'un nœud. La CA reste en lecture seule (`/data/certs/ca/`). Le certificat signé est retourné au nœud qui l'installe dans son daemon Docker.

---

## Modèle Python (Pydantic v2)

Pas de modèle Pydantic dédié — piloté par `cryptography` dans `nodes/enroll.py`.
Modèle logique de la donnée persistée :

```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class NodeCertificate(BaseModel):
    """Représentation logique du certificat d'un nœud."""
    model_config = ConfigDict(extra="forbid")

    node_name: str       # DNS-safe ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$
    address: str         # IP ou hostname fourni lors de l'enrôlement (présent dans SAN)
    cert_pem: str        # Certificat X.509 signé, format PEM
    signed_at: datetime
    expires_at: datetime
```

Fonctions associées dans `nodes/enroll.py` :

```python
def sign_csr(
    csr_pem: bytes,
    expected_cn: str,
    expected_address: str,
    ca_cert_path: Path,
    ca_key_path: Path,
) -> tuple[bytes, bytes]:
    """Valide et signe le CSR. Retourne (cert_pem, ca_cert_pem)."""
    ...

async def enroll_node(token: str, csr_pem: str) -> dict[str, str]:
    """Consomme le token, signe le CSR, enregistre le nœud dans GlobalConfig."""
    ...
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE node_certificates (
    id          SERIAL PRIMARY KEY,
    -- node_name = CN du certificat = nom du host Docker enrôlé
    node_name   TEXT NOT NULL UNIQUE REFERENCES hosts(name) ON DELETE CASCADE,
    address     TEXT NOT NULL,          -- IP ou hostname (présent dans le SAN du cert)
    cert_pem    TEXT NOT NULL,          -- certificat X.509 PEM signé par la CA interne
    serial_number TEXT NOT NULL DEFAULT '',  -- numéro de série X.509 (hex) pour révocation
    signed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,   -- now() + 1825 jours (5 ans, §E-29)
    revoked_at  TIMESTAMPTZ             -- NULL = certificat valide
);

CREATE INDEX idx_node_certificates_expires ON node_certificates(expires_at)
    WHERE revoked_at IS NULL;
-- Permet de détecter les certificats proches de l'expiration.
```
