from __future__ import annotations

import httpx
import pytest

from portal.secrets.backends.harpocrate import HarpocrateBackend


def _backend(handler) -> HarpocrateBackend:
    return HarpocrateBackend(
        url="https://harpocrate.example.com",
        api_key="test-key",
        base_path="devpod",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_get_returns_value():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": "my_secret"})

    assert _backend(handler).get("devpod/ns/git/token") == "my_secret"


def test_get_raises_key_error_on_404():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(KeyError, match="not found"):
        _backend(handler).get("devpod/ns/git/missing")


def test_get_sends_api_key_header():
    received: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        received.update(dict(req.headers))
        return httpx.Response(200, json={"value": "v"})

    HarpocrateBackend(
        url="https://harpocrate.example.com",
        api_key="my-secret-key",
        base_path="devpod",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).get("devpod/ns/key")

    assert received.get("x-api-key") == "my-secret-key"


def test_get_raises_on_http_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(httpx.HTTPStatusError):
        _backend(handler).get("devpod/ns/key")
