from __future__ import annotations

import ipaddress
import re

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..config.store import load_global
from ..db.engine import get_conn
from ..db.tokens import create_token
from ..nodes.enroll import CsrValidationError, enroll_node

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
            raise ValueError(f"node_name '{v}' must match ^[a-z0-9][a-z0-9-]{{0,30}}[a-z0-9]$")
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
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Génère un join token à usage unique pour enrôler un nœud. §E-27."""
    token = await create_token(node_name=req.node_name, address=req.address, conn=conn)
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
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Enrôlement : auth Bearer join token (pas de session OIDC). §E-27, §E-28."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization[len("Bearer ") :]
    try:
        result = await enroll_node(token=token, csr_pem=req.csr, conn=conn)
    except CsrValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        _log.error("enroll_ca_unavailable", error=str(exc))
        raise HTTPException(status_code=500, detail="CA not available") from exc
    return result
