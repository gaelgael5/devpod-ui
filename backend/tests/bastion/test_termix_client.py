"""Client Termix : payloads + parsing d'id (httpx mocké via MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from portal.bastion.termix_client import TermixClient, _extract_id


def test_extract_id_variants() -> None:
    assert _extract_id({"id": 7}) == 7
    assert _extract_id({"hostId": "12"}) == 12
    assert _extract_id({"credentialId": 3}) == 3
    assert _extract_id({"nope": 1}) is None
    assert _extract_id([1, 2]) is None


def _client_with(handler: object) -> TermixClient:
    c = TermixClient("https://termix.yoops.org", "tmx_secret")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return c


@pytest.mark.asyncio
async def test_create_credential_and_host_and_share() -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        seen.append((req.method, req.url.path, body))
        assert req.headers["authorization"] == "Bearer tmx_secret"
        if req.url.path == "/credentials":
            return httpx.Response(201, json={"id": 42})
        if req.url.path == "/host":
            return httpx.Response(201, json={"id": 99})
        if req.url.path == "/rbac/roles":
            return httpx.Response(200, json=[{"id": 5, "name": "devpod-users"}])
        if req.url.path == "/rbac/host/99/share":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    c = _client_with(handler)
    cred = await c.create_credential("ws-admin-doc", "root", "PRIVKEY")
    host = await c.create_host("admin-doc", "192.168.10.164", 2222, "root", cred)  # type: ignore[arg-type]
    role = await c.find_role_id("devpod-users")
    await c.share_host_to_role(host, role)  # type: ignore[arg-type]
    await c._client.aclose()  # type: ignore[union-attr]

    assert cred == 42 and host == 99 and role == 5
    cred_body = next(b for m, p, b in seen if p == "/credentials")
    assert cred_body == {
        "name": "ws-admin-doc",
        "authType": "key",
        "username": "root",
        "key": "PRIVKEY",
    }
    host_body = next(b for m, p, b in seen if p == "/host")
    assert host_body["credentialId"] == 42 and host_body["port"] == 2222
    share_body = next(b for m, p, b in seen if p.endswith("/share"))
    assert share_body == {"targets": [{"type": "role", "id": 5}], "permissionLevel": "connect"}


@pytest.mark.asyncio
async def test_http_error_raises() -> None:
    c = _client_with(lambda req: httpx.Response(401, text="Missing authentication token"))
    with pytest.raises(RuntimeError, match="401"):
        await c.find_role_id("x")
    await c._client.aclose()  # type: ignore[union-attr]
