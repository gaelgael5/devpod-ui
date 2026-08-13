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
        if req.url.path == "/host/db/host":
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
    host_body = next(b for m, p, b in seen if p == "/host/db/host")
    assert host_body["credentialId"] == 42 and host_body["port"] == 2222
    share_body = next(b for m, p, b in seen if p.endswith("/share"))
    assert share_body == {"targets": [{"type": "role", "id": 5}], "permissionLevel": "connect"}


@pytest.mark.asyncio
async def test_delete_user_by_username() -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        seen.append((req.method, req.url.path, body))
        return httpx.Response(200, json={"message": "ok"})

    c = _client_with(handler)
    await c.delete_user(username="gaelgael5@gmail.com")
    await c.delete_user(user_id="RT23SEGfo")
    await c._client.aclose()  # type: ignore[union-attr]
    assert seen[0] == ("DELETE", "/users/delete-user", {"username": "gaelgael5@gmail.com"})
    assert seen[1] == ("DELETE", "/users/delete-user", {"userId": "RT23SEGfo"})


@pytest.mark.asyncio
async def test_create_apikey_for_user_and_delete() -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        seen.append((req.method, req.url.path, body))
        if req.url.path == "/users/api-keys" and req.method == "POST":
            return httpx.Response(200, json={"apiKey": {"id": "key-42"}, "token": "tmx_owner"})
        if req.url.path == "/users/api-keys/key-42" and req.method == "DELETE":
            return httpx.Response(200, json={"message": "ok"})
        return httpx.Response(404)

    c = _client_with(handler)
    key_id, token = await c.create_apikey_for_user("u-1", "portal", "2026-01-01T00:00:00Z")
    assert key_id == "key-42" and token == "tmx_owner"
    await c.delete_apikey(key_id)  # type: ignore[arg-type]
    await c._client.aclose()  # type: ignore[union-attr]

    post_body = next(b for m, p, b in seen if p == "/users/api-keys" and m == "POST")
    assert post_body == {"name": "portal", "userId": "u-1", "expiresAt": "2026-01-01T00:00:00Z"}
    assert ("DELETE", "/users/api-keys/key-42", {}) in seen


@pytest.mark.asyncio
async def test_create_user_local_and_conflict() -> None:
    seen: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        seen.append((req.url.path, body))
        # 1er appel : créé ; 2e (même username) : 409 déjà existant.
        already = sum(1 for p, _ in seen if p == "/users/admin-create") > 1
        return httpx.Response(409 if already else 200, json={"message": "ok"})

    c = _client_with(handler)
    assert await c.create_user("gael@x.org", "pw") is True
    assert await c.create_user("gael@x.org", "pw") is False  # 409 toléré
    await c._client.aclose()  # type: ignore[union-attr]
    body = seen[0][1]
    assert body == {"username": "gael@x.org", "password": "pw"}
    assert seen[0][0] == "/users/admin-create"


@pytest.mark.asyncio
async def test_find_user_id_and_share_to_user() -> None:
    seen: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        seen.append((req.url.path, body))
        if req.url.path == "/users/list":
            # Forme réelle Termix : userId est une chaîne, sous la clé "users".
            return httpx.Response(
                200,
                json={
                    "users": [
                        {"userId": "wG3UbK6OF8H1", "username": "sub-abc", "is_oidc": False},
                        {"userId": "RT23SEGfo", "username": "gael", "is_oidc": True},
                    ]
                },
            )
        if req.url.path == "/rbac/host/99/share":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    c = _client_with(handler)
    uid = await c.find_user_id("sub-abc")
    assert uid == "wG3UbK6OF8H1"
    assert await c.find_user_id("inconnu") is None
    await c.share_host_to_user(99, uid)  # type: ignore[arg-type]
    await c._client.aclose()  # type: ignore[union-attr]

    share_body = next(b for p, b in seen if p.endswith("/share"))
    assert share_body == {
        "targets": [{"type": "user", "id": "wG3UbK6OF8H1"}],
        "permissionLevel": "connect",
    }


@pytest.mark.asyncio
async def test_http_error_raises() -> None:
    c = _client_with(lambda req: httpx.Response(401, text="Missing authentication token"))
    with pytest.raises(RuntimeError, match="401"):
        await c.find_role_id("x")
    await c._client.aclose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_list_host_ids_contract_path() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert (req.method, req.url.path) == ("GET", "/host/db/host")
        return httpx.Response(200, json=[{"id": 7}, {"id": 9}, {"nope": 1}])

    c = _client_with(handler)
    assert await c.list_host_ids() == [7, 9]
    await c._client.aclose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_list_host_ids_inconclusive_on_error() -> None:
    # Route absente / forme inattendue → None (l'appelant ne conclut pas à la disparition).
    c = _client_with(lambda req: httpx.Response(404))
    assert await c.list_host_ids() is None
    await c._client.aclose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_deletes_tolerate_404() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(404)

    c = _client_with(handler)
    await c.delete_host(99)  # ne lève pas : déjà supprimé = succès
    await c.delete_credential(42)
    await c._client.aclose()  # type: ignore[union-attr]
    assert paths == ["/host/db/host/99", "/credentials/42"]
