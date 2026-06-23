from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from portal.mcp.client import call_backend_tool, fetch_primitives, hash_definition


def _demo_server() -> FastMCP:
    srv = FastMCP("demo")

    @srv.tool()
    def echo(text: str) -> str:
        """Echo le texte."""
        return text

    @srv.resource("demo://greeting")
    def greeting() -> str:
        return "hello"

    @srv.prompt()
    def hi(name: str) -> str:
        return f"Bonjour {name}"

    return srv


def test_hash_definition_stable_and_order_independent() -> None:
    a = hash_definition({"name": "x", "v": 1})
    b = hash_definition({"v": 1, "name": "x"})
    assert a == b
    assert a != hash_definition({"name": "x", "v": 2})


async def test_fetch_primitives_normalizes_all_kinds() -> None:
    # create_connected_server_and_client_session calls initialize() internally —
    # no explicit initialize() needed here.
    async with create_connected_server_and_client_session(_demo_server()) as session:
        prims = await fetch_primitives(session)

    kinds = {p["kind"] for p in prims}
    assert kinds == {"tool", "resource", "prompt"}
    tool = next(p for p in prims if p["kind"] == "tool")
    assert tool["original_name"] == "echo"
    assert isinstance(tool["definition"], dict) and tool["definition_hash"]
    # le hash correspond à la définition normalisée
    assert tool["definition_hash"] == hash_definition(tool["definition"])
    res = next(p for p in prims if p["kind"] == "resource")
    assert res["original_name"] == "demo://greeting"
    prompt = next(p for p in prims if p["kind"] == "prompt")
    assert prompt["original_name"] == "hi"


async def test_call_backend_tool() -> None:
    async with create_connected_server_and_client_session(_demo_server()) as session:
        result = await call_backend_tool(session, "echo", {"text": "ping"})
    assert result.isError is False
    # le contenu texte renvoyé contient "ping"
    assert any(getattr(c, "text", "") == "ping" for c in result.content)
