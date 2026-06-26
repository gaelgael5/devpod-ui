from __future__ import annotations

import httpx
import pytest
import respx

ADMIN_API = "http://caddy:2019"
VERIFY_URI = "https://dev.yoops.org/auth/caddy/verify"


@pytest.mark.asyncio
async def test_upsert_route_patch_success() -> None:
    """upsert_route() fait d'abord un PATCH ; si 200, pas de POST."""
    from portal.exposure.caddy import CaddyClient

    with respx.mock(assert_all_called=True) as rsps:
        rsps.patch(f"{ADMIN_API}/id/ws-alice-myapp").mock(return_value=httpx.Response(200))
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            await caddy.upsert_route(
                route_id="ws-alice-myapp",
                match_host="ws-alice-myapp.dev.yoops.org",
                upstream="192.168.1.50:41000",
            )


@pytest.mark.asyncio
async def test_upsert_route_patch_404_falls_back_to_post() -> None:
    """upsert_route() fait un POST si le PATCH retourne 404."""
    from portal.exposure.caddy import CaddyClient

    with respx.mock(assert_all_called=True) as rsps:
        rsps.patch(f"{ADMIN_API}/id/ws-alice-myapp").mock(return_value=httpx.Response(404))
        rsps.post(f"{ADMIN_API}/config/apps/http/servers/srv0/routes").mock(
            return_value=httpx.Response(200)
        )
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            await caddy.upsert_route(
                route_id="ws-alice-myapp",
                match_host="ws-alice-myapp.dev.yoops.org",
                upstream="192.168.1.50:41000",
            )


@pytest.mark.asyncio
async def test_upsert_route_json_structure() -> None:
    """La route envoyée a forward_auth AVANT reverse_proxy, avec les bons champs."""
    import json

    from portal.exposure.caddy import CaddyClient

    captured_body: dict = {}

    def capture_patch(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(200)

    with respx.mock:
        respx.patch(f"{ADMIN_API}/id/ws-alice-myapp").mock(side_effect=capture_patch)
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            await caddy.upsert_route(
                route_id="ws-alice-myapp",
                match_host="ws-alice-myapp.dev.yoops.org",
                upstream="192.168.1.50:41000",
            )

    # Vérifier la structure : 'forward_auth' n'existe PAS comme handler Caddy JSON ;
    # il se traduit en un subroute(reverse_proxy auth + reverse_proxy workspace).
    assert captured_body["@id"] == "ws-alice-myapp"
    assert captured_body["match"] == [{"host": ["ws-alice-myapp.dev.yoops.org"]}]
    assert captured_body["terminal"] is True
    handlers = captured_body["handle"]
    assert len(handlers) == 1
    assert handlers[0]["handler"] == "subroute"
    inner = handlers[0]["routes"][0]["handle"]
    assert len(inner) == 2
    # 1) Auth (fail-closed §F-33) : reverse_proxy vers le verify_uri, AVANT le proxy ws.
    auth = inner[0]
    assert auth["handler"] == "reverse_proxy"
    assert auth["upstreams"] == [{"dial": "dev.yoops.org"}]  # netloc du verify_uri
    assert auth["rewrite"] == {"method": "GET", "uri": "/auth/caddy/verify"}
    assert "handle_response" in auth  # non-2xx → réponse d'auth renvoyée telle quelle
    # 2) reverse_proxy workspace
    ws = inner[1]
    assert ws["handler"] == "reverse_proxy"
    assert ws["upstreams"] == [{"dial": "192.168.1.50:41000"}]
    # Aucun handler "forward_auth" nulle part (cause du 500 Caddy)
    import json as _json

    assert '"forward_auth"' not in _json.dumps(captured_body)


@pytest.mark.asyncio
async def test_remove_route_success() -> None:
    """remove_route() fait un DELETE et accepte 200."""
    from portal.exposure.caddy import CaddyClient

    with respx.mock(assert_all_called=True) as rsps:
        rsps.delete(f"{ADMIN_API}/id/ws-alice-myapp").mock(return_value=httpx.Response(200))
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            await caddy.remove_route("ws-alice-myapp")


@pytest.mark.asyncio
async def test_remove_route_404_is_ok() -> None:
    """remove_route() ne lève pas d'exception si la route n'existe pas (404)."""
    from portal.exposure.caddy import CaddyClient

    with respx.mock(assert_all_called=True) as rsps:
        rsps.delete(f"{ADMIN_API}/id/ws-alice-myapp").mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            # Ne doit pas lever d'exception
            await caddy.remove_route("ws-alice-myapp")


@pytest.mark.asyncio
async def test_remove_route_500_raises() -> None:
    """remove_route() lève une exception pour les erreurs serveur (5xx)."""
    from portal.exposure.caddy import CaddyClient

    with respx.mock:
        respx.delete(f"{ADMIN_API}/id/ws-alice-myapp").mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            with pytest.raises(httpx.HTTPStatusError):
                await caddy.remove_route("ws-alice-myapp")


@pytest.mark.asyncio
async def test_upsert_route_patch_500_raises() -> None:
    """upsert_route() lève une HTTPStatusError si le PATCH retourne 500."""
    from portal.exposure.caddy import CaddyClient

    with respx.mock:
        respx.patch(f"{ADMIN_API}/id/ws-alice-myapp").mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            with pytest.raises(httpx.HTTPStatusError):
                await caddy.upsert_route(
                    route_id="ws-alice-myapp",
                    match_host="ws-alice-myapp.dev.yoops.org",
                    upstream="192.168.1.50:41000",
                )


@pytest.mark.asyncio
async def test_upsert_route_post_500_raises() -> None:
    """upsert_route() lève une HTTPStatusError si le POST (après PATCH 404) retourne 500."""
    from portal.exposure.caddy import CaddyClient

    with respx.mock(assert_all_called=True) as rsps:
        rsps.patch(f"{ADMIN_API}/id/ws-alice-myapp").mock(return_value=httpx.Response(404))
        rsps.post(f"{ADMIN_API}/config/apps/http/servers/srv0/routes").mock(
            return_value=httpx.Response(500)
        )
        async with httpx.AsyncClient() as client:
            caddy = CaddyClient(
                admin_api=ADMIN_API,
                http_client=client,
                verify_uri=VERIFY_URI,
            )
            with pytest.raises(httpx.HTTPStatusError):
                await caddy.upsert_route(
                    route_id="ws-alice-myapp",
                    match_host="ws-alice-myapp.dev.yoops.org",
                    upstream="192.168.1.50:41000",
                )
