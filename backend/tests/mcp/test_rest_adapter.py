"""Tranche 1 — moteur pur de l'adaptateur REST→MCP (transport `rest`).

Ces tests cadrent le mapping déclaratif d'un outil MCP vers un appel HTTP REST :
construction de la requête, injection du secret backend dans corps/query/header,
traduction de la réponse en CallToolResult, et rédaction du secret dans toute
sortie d'erreur (l'API distante peut ré-échoyer le corps envoyé — cf. le 422 du
backend rag).
"""

from __future__ import annotations

import json

import httpx
import pytest

from portal.mcp.connections import BackendUnavailable
from portal.mcp.rest_adapter import (
    RestToolSpec,
    build_call,
    execute_rest_tool,
    translate_response,
)


def _rag_spec() -> RestToolSpec:
    return RestToolSpec(
        method="POST",
        path="/mcp",
        body_args=["query", "workspace", "top_k", "min_score"],
        secret_field="api_key",
        secret_in="body",
    )


class TestBuildCall:
    def test_rag_post_body_and_secret_in_body(self) -> None:
        call = build_call(
            "http://192.168.10.195",
            _rag_spec(),
            {"query": "hello", "workspace": "kb", "top_k": 5},
            secret="SEKRET",
        )
        assert call.method == "POST"
        assert call.url == "http://192.168.10.195/mcp"
        assert call.json_body == {
            "query": "hello",
            "workspace": "kb",
            "top_k": 5,
            "api_key": "SEKRET",
        }
        assert call.params == {}
        assert "SEKRET" not in str(call.headers)

    def test_secret_in_query(self) -> None:
        spec = RestToolSpec(
            method="GET", path="/search", query_args=["q"], secret_field="key", secret_in="query"
        )
        call = build_call("http://h", spec, {"q": "x"}, secret="S")
        assert call.params == {"q": "x", "key": "S"}
        assert call.json_body is None

    def test_secret_in_header(self) -> None:
        spec = RestToolSpec(method="GET", path="/s", secret_field="X-Api-Key", secret_in="header")
        call = build_call("http://h", spec, {}, secret="S")
        assert call.headers == {"X-Api-Key": "S"}

    def test_path_templating_is_url_quoted(self) -> None:
        spec = RestToolSpec(method="GET", path="/ws/{workspace}/doc", path_args=["workspace"])
        call = build_call("http://h/", spec, {"workspace": "a b/c"}, secret=None)
        assert call.url == "http://h/ws/a%20b%2Fc/doc"

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            RestToolSpec(method="POST", nope=1)  # type: ignore[call-arg]


class TestTranslateResponse:
    def test_success_passthrough(self) -> None:
        res = translate_response(RestToolSpec(), 200, '{"a":1}', {"a": 1}, secret=None)
        assert res.isError is False
        assert '"a": 1' in res.content[0].text  # type: ignore[union-attr]

    def test_result_path_extraction(self) -> None:
        spec = RestToolSpec(result_path="data.hits")
        res = translate_response(spec, 200, "{}", {"data": {"hits": [1, 2]}}, secret=None)
        assert json.loads(res.content[0].text) == [1, 2]  # type: ignore[union-attr]

    def test_error_status_is_error_and_secret_redacted(self) -> None:
        # L'API renvoie une 422 qui ré-échoue le corps, secret compris.
        body = {"detail": "bad", "input": {"api_key": "SEKRET"}}
        res = translate_response(RestToolSpec(), 422, "", body, secret="SEKRET")
        assert res.isError is True
        assert "SEKRET" not in res.content[0].text  # type: ignore[union-attr]
        assert "***" in res.content[0].text  # type: ignore[union-attr]


class TestExecuteRestTool:
    @pytest.mark.asyncio
    async def test_ok_call(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/mcp"
            return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            res = await execute_rest_tool(
                "http://h",
                _rag_spec(),
                {"query": "q", "workspace": "w"},
                secret="S",
                client=client,
            )
        assert res.isError is False
        assert '"ok": true' in res.content[0].text  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_error_echo_never_leaks_secret(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"input": {"api_key": "S"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            res = await execute_rest_tool(
                "http://h",
                _rag_spec(),
                {"query": "q"},
                secret="S",
                client=client,
            )
        assert res.isError is True
        assert "S" not in res.content[0].text or "***" in res.content[0].text  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_connection_error_becomes_backend_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BackendUnavailable):
                await execute_rest_tool(
                    "http://h",
                    _rag_spec(),
                    {"query": "q"},
                    secret="S",
                    client=client,
                )
