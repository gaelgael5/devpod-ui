"""Tests de la couche DB node_certificates (Tour 10)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.node_certs import get_node_cert_db, revoke_node_cert_db, save_node_cert_db

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)
_EXPIRES = _NOW + timedelta(days=1825)
_CERT_PEM = "-----BEGIN CERTIFICATE-----\nfakedata==\n-----END CERTIFICATE-----\n"


async def test_save_and_get(db_conn: AsyncConnection) -> None:
    await save_node_cert_db(
        node_name="node01",
        address="192.168.1.10",
        cert_pem=_CERT_PEM,
        serial_number="deadbeef",
        signed_at=_NOW,
        expires_at=_EXPIRES,
        conn=db_conn,
    )
    result = await get_node_cert_db("node01", db_conn)
    assert result is not None
    assert result["node_name"] == "node01"
    assert result["address"] == "192.168.1.10"
    assert result["serial_number"] == "deadbeef"
    assert result["revoked_at"] is None


async def test_get_unknown_returns_none(db_conn: AsyncConnection) -> None:
    result = await get_node_cert_db("ghost-node", db_conn)
    assert result is None


async def test_revoke(db_conn: AsyncConnection) -> None:
    await save_node_cert_db(
        node_name="node02",
        address="192.168.1.11",
        cert_pem=_CERT_PEM,
        serial_number="cafebabe",
        signed_at=_NOW,
        expires_at=_EXPIRES,
        conn=db_conn,
    )
    await revoke_node_cert_db("node02", db_conn)
    result = await get_node_cert_db("node02", db_conn)
    assert result is not None
    assert result["revoked_at"] is not None
