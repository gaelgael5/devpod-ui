from __future__ import annotations

from datetime import timedelta
from typing import cast

from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    Prompt,
    Resource,
    ServerCapabilities,
    Tool,
)
from pydantic import AnyUrl

from portal.mcp.client import (
    advertised_kinds,
    call_backend_tool,
    fetch_primitives,
    get_backend_prompt,
    hash_definition,
    read_backend_resource,
)


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


class _PagedSession:
    """Backend qui pagine ses trois familles via `nextCursor`.

    Reproduit le contrat MCP : `list_*` renvoie une page + un curseur ; un client
    conforme doit suivre le curseur jusqu'à épuisement. Enregistre les curseurs
    reçus pour vérifier qu'ils ont bien été suivis.
    """

    def __init__(self) -> None:
        self.tool_cursors: list[str | None] = []
        self.resource_cursors: list[str | None] = []
        self.prompt_cursors: list[str | None] = []

    def get_server_capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(tools={}, resources={}, prompts={})

    async def list_tools(
        self, cursor: str | None = None, *, params: object | None = None
    ) -> ListToolsResult:
        self.tool_cursors.append(cursor)
        if cursor is None:
            return ListToolsResult(
                tools=[
                    Tool(name="a", inputSchema={"type": "object"}),
                    Tool(name="b", inputSchema={"type": "object"}),
                ],
                nextCursor="tools-p2",
            )
        if cursor == "tools-p2":
            return ListToolsResult(
                tools=[Tool(name="c", inputSchema={"type": "object"})], nextCursor=None
            )
        raise AssertionError(f"curseur tools inattendu: {cursor}")

    async def list_resources(
        self, cursor: str | None = None, *, params: object | None = None
    ) -> ListResourcesResult:
        self.resource_cursors.append(cursor)
        if cursor is None:
            return ListResourcesResult(
                resources=[Resource(uri=AnyUrl("res://one"), name="one")],
                nextCursor="res-p2",
            )
        if cursor == "res-p2":
            return ListResourcesResult(
                resources=[Resource(uri=AnyUrl("res://two"), name="two")], nextCursor=None
            )
        raise AssertionError(f"curseur resources inattendu: {cursor}")

    async def list_prompts(
        self, cursor: str | None = None, *, params: object | None = None
    ) -> ListPromptsResult:
        self.prompt_cursors.append(cursor)
        if cursor is None:
            return ListPromptsResult(prompts=[Prompt(name="p1")], nextCursor="prompts-p2")
        if cursor == "prompts-p2":
            return ListPromptsResult(prompts=[Prompt(name="p2")], nextCursor=None)
        raise AssertionError(f"curseur prompts inattendu: {cursor}")


async def test_fetch_primitives_follows_pagination() -> None:
    """fetch_primitives suit `nextCursor` : aucune primitive de page 2+ n'est perdue.

    Régression du bug registre fédéré partiel (docflow create_document /
    set_document_parent) : sans pagination, seule la page 1 était capturée et le
    prune effaçait la queue du catalogue.
    """
    session = _PagedSession()
    prims = await fetch_primitives(cast(ClientSession, session))

    tools = {p["original_name"] for p in prims if p["kind"] == "tool"}
    resources = {p["original_name"] for p in prims if p["kind"] == "resource"}
    prompts = {p["original_name"] for p in prims if p["kind"] == "prompt"}
    assert tools == {"a", "b", "c"}
    assert resources == {"res://one", "res://two"}
    assert prompts == {"p1", "p2"}
    # Le curseur a bien été suivi (page 1 puis page 2) pour chaque famille.
    assert session.tool_cursors == [None, "tools-p2"]
    assert session.resource_cursors == [None, "res-p2"]
    assert session.prompt_cursors == [None, "prompts-p2"]


async def test_call_backend_tool() -> None:
    async with create_connected_server_and_client_session(_demo_server()) as session:
        result = await call_backend_tool(session, "echo", {"text": "ping"})
    assert result.isError is False
    # le contenu texte renvoyé contient "ping"
    assert any(getattr(c, "text", "") == "ping" for c in result.content)


async def test_call_backend_tool_honors_read_timeout() -> None:
    # read_timeout_seconds est transmis au SDK ; un appel nominal sous le délai réussit.
    async with create_connected_server_and_client_session(_demo_server()) as session:
        result = await call_backend_tool(
            session, "echo", {"text": "ping"}, read_timeout_seconds=timedelta(seconds=5)
        )
    assert result.isError is False
    assert any(getattr(c, "text", "") == "ping" for c in result.content)


def test_advertised_kinds_none_caps() -> None:
    assert advertised_kinds(None) == ()


def test_advertised_kinds_maps_only_present_families() -> None:
    # On construit les capabilities à la main : un serveur réel qui ne supporte
    # pas une famille omet la capability correspondante (None). FastMCP, lui,
    # annonce toujours les trois — il ne peut donc pas représenter ce cas.
    assert advertised_kinds(ServerCapabilities(tools={})) == ("tool",)
    assert advertised_kinds(ServerCapabilities(prompts={})) == ("prompt",)
    assert advertised_kinds(ServerCapabilities()) == ()
    assert advertised_kinds(ServerCapabilities(tools={}, resources={}, prompts={})) == (
        "tool",
        "resource",
        "prompt",
    )


def _server_with_resource_and_prompt() -> FastMCP:
    srv = FastMCP("demo")

    @srv.resource("resource://greeting")
    def greeting() -> str:
        return "hello"

    @srv.prompt()
    def welcome(who: str) -> str:
        return f"Welcome {who}"

    return srv


async def test_read_backend_resource() -> None:
    async with create_connected_server_and_client_session(
        _server_with_resource_and_prompt()
    ) as session:
        result = await read_backend_resource(session, AnyUrl("resource://greeting"))
    assert result.contents[0].text == "hello"


async def test_get_backend_prompt() -> None:
    async with create_connected_server_and_client_session(
        _server_with_resource_and_prompt()
    ) as session:
        result = await get_backend_prompt(session, "welcome", {"who": "Bob"})
    assert "Bob" in result.messages[0].content.text
