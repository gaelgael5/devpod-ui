"""Tests de la primitive MCP logs_query (spec 31)."""

from __future__ import annotations

import json
import urllib.parse
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from portal.mcp.devpod_tools.errors import DevpodToolError
from portal.mcp.devpod_tools.logs_tools import (
    LogsQueryParams,
    _flatten_streams,
    _grafana_explore_url,
    _logs_query,
    build_logql,
)

# ---------------------------------------------------------------------------
# build_logql
# ---------------------------------------------------------------------------


def test_build_logql_raw_query_passthrough() -> None:
    p = LogsQueryParams(query="{job='test'}")
    assert build_logql(p) == "{job='test'}"


def test_build_logql_single_filter() -> None:
    p = LogsQueryParams(host="host-dev-01")
    assert build_logql(p) == '{host="host-dev-01"}'


def test_build_logql_multiple_filters() -> None:
    p = LogsQueryParams(project="rag", role="test")
    logql = build_logql(p)
    assert 'compose_project="rag"' in logql
    assert 'role="test"' in logql
    assert logql.startswith("{")


def test_build_logql_with_level() -> None:
    p = LogsQueryParams(project="rag", level="error")
    logql = build_logql(p)
    assert logql == '{compose_project="rag"} | json | level="error"'


def test_build_logql_no_selector_raises() -> None:
    p = LogsQueryParams(level="error")  # level seul n'est pas un sélecteur de stream
    with pytest.raises(ValueError, match="host/role/project/service/unit"):
        build_logql(p)


def test_build_logql_raw_query_wins_over_filters() -> None:
    p = LogsQueryParams(query="{custom='x'}", host="other")
    assert build_logql(p) == "{custom='x'}"


# ---------------------------------------------------------------------------
# _flatten_streams
# ---------------------------------------------------------------------------


def _loki_response(streams: list) -> dict:
    return {"data": {"resultType": "streams", "result": streams}}


def test_flatten_streams_empty() -> None:
    assert _flatten_streams(_loki_response([])) == []


def test_flatten_streams_single_line() -> None:
    # 1 nanosecond timestamp = 1000000000 ns = 1s depuis epoch
    ts_ns = str(1_000_000_000 * 1_000_000_000)  # 2001-09-09T01:46:40Z en ns
    streams = [
        {
            "stream": {"host": "h1", "role": "test"},
            "values": [[ts_ns, '{"msg":"hello"}']],
        }
    ]
    lines = _flatten_streams(_loki_response(streams))
    assert len(lines) == 1
    assert lines[0]["labels"] == {"host": "h1", "role": "test"}
    assert lines[0]["line"] == '{"msg":"hello"}'
    assert lines[0]["ts"].endswith("Z")


def test_flatten_streams_multiple_streams() -> None:
    ts_ns = str(1_700_000_000 * 1_000_000_000)
    streams = [
        {"stream": {"host": "h1"}, "values": [[ts_ns, "line1"], [ts_ns, "line2"]]},
        {"stream": {"host": "h2"}, "values": [[ts_ns, "line3"]]},
    ]
    lines = _flatten_streams(_loki_response(streams))
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# _grafana_explore_url
# ---------------------------------------------------------------------------


def test_grafana_explore_url_none_when_no_base() -> None:
    p = LogsQueryParams(host="h1")
    assert _grafana_explore_url(None, "{host='h1'}", p) is None


def test_grafana_explore_url_contains_logql() -> None:
    p = LogsQueryParams(host="h1", since="2h")
    url = _grafana_explore_url("https://grafana.example.com", '{host="h1"}', p)
    assert url is not None
    assert url.startswith("https://grafana.example.com/explore?orgId=1&left=")
    decoded = urllib.parse.unquote(url.split("left=")[1])
    obj = json.loads(decoded)
    assert obj["queries"][0]["expr"] == '{host="h1"}'
    assert obj["range"]["from"] == "now-2h"
    assert obj["range"]["to"] == "now"


def test_grafana_explore_url_absolute_range() -> None:
    p = LogsQueryParams(host="h1", start="2026-01-01T00:00:00Z", end="2026-01-02T00:00:00Z")
    url = _grafana_explore_url("https://g.example.com", '{host="h1"}', p)
    assert url is not None
    decoded = urllib.parse.unquote(url.split("left=")[1])
    obj = json.loads(decoded)
    assert obj["range"]["from"] == "2026-01-01T00:00:00Z"
    assert obj["range"]["to"] == "2026-01-02T00:00:00Z"


# ---------------------------------------------------------------------------
# _logs_query (intégration avec config mockée)
# ---------------------------------------------------------------------------


def _make_logs_config(
    enabled: bool = True,
    loki_query_url: str | None = "http://loki:3100",
    grafana_url: str | None = "http://grafana:3000",
    push_token: str | None = None,
) -> MagicMock:
    cfg = MagicMock()
    cfg.logs.enabled = enabled
    cfg.logs.loki_query_url = loki_query_url
    cfg.logs.grafana_url = grafana_url
    cfg.logs.push_token = push_token
    return cfg


@pytest.mark.asyncio
async def test_logs_query_disabled_raises() -> None:
    with (
        patch(
            "portal.mcp.devpod_tools.logs_tools.load_global",
            return_value=_make_logs_config(enabled=False),
        ),
        pytest.raises(DevpodToolError, match="logs.enabled=false"),
    ):
        await _logs_query(None, {"host": "h1"}, "user")


@pytest.mark.asyncio
async def test_logs_query_no_loki_url_raises() -> None:
    with (
        patch(
            "portal.mcp.devpod_tools.logs_tools.load_global",
            return_value=_make_logs_config(loki_query_url=None),
        ),
        pytest.raises(DevpodToolError, match="loki_query_url"),
    ):
        await _logs_query(None, {"host": "h1"}, "user")


@pytest.mark.asyncio
async def test_logs_query_no_selector_raises() -> None:
    with (
        patch(
            "portal.mcp.devpod_tools.logs_tools.load_global",
            return_value=_make_logs_config(),
        ),
        pytest.raises(DevpodToolError, match="host/role/project/service/unit"),
    ):
        await _logs_query(None, {"level": "error"}, "user")


@pytest.mark.asyncio
@respx.mock
async def test_logs_query_success() -> None:
    ts_ns = str(1_700_000_000 * 1_000_000_000)
    loki_body = {
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"host": "h1", "compose_project": "rag"},
                    "values": [[ts_ns, '{"level":"error","msg":"boom"}']],
                }
            ],
        }
    }
    respx.get("http://loki:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=loki_body)
    )

    with patch(
        "portal.mcp.devpod_tools.logs_tools.load_global",
        return_value=_make_logs_config(),
    ):
        result = await _logs_query(None, {"project": "rag", "level": "error"}, "user")

    assert result["count"] == 1
    assert result["truncated"] is False
    assert result["query"] == '{compose_project="rag"} | json | level="error"'
    assert result["lines"][0]["labels"]["compose_project"] == "rag"
    assert result["grafana_url"] is not None
    assert "grafana:3000" in result["grafana_url"]


@pytest.mark.asyncio
@respx.mock
async def test_logs_query_loki_unreachable_raises() -> None:
    respx.get("http://loki:3100/loki/api/v1/query_range").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with (
        patch(
            "portal.mcp.devpod_tools.logs_tools.load_global",
            return_value=_make_logs_config(),
        ),
        pytest.raises(DevpodToolError, match="logs_backend_unreachable"),
    ):
        await _logs_query(None, {"host": "h1"}, "user")


@pytest.mark.asyncio
@respx.mock
async def test_logs_query_loki_error_status_raises() -> None:
    respx.get("http://loki:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(400, text="parse error: unexpected token")
    )

    with (
        patch(
            "portal.mcp.devpod_tools.logs_tools.load_global",
            return_value=_make_logs_config(),
        ),
        pytest.raises(DevpodToolError, match="400"),
    ):
        await _logs_query(None, {"host": "h1"}, "user")


@pytest.mark.asyncio
@respx.mock
async def test_logs_query_empty_result_is_not_error() -> None:
    loki_body = {"data": {"resultType": "streams", "result": []}}
    respx.get("http://loki:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=loki_body)
    )

    with patch(
        "portal.mcp.devpod_tools.logs_tools.load_global",
        return_value=_make_logs_config(),
    ):
        result = await _logs_query(None, {"role": "test"}, "user")

    assert result["count"] == 0
    assert result["lines"] == []
    assert result["truncated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_logs_query_truncated_flag() -> None:
    ts_ns = str(1_700_000_000 * 1_000_000_000)
    # Retourner exactement `limit` lignes → truncated=True
    loki_body = {
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"host": "h1"},
                    "values": [[ts_ns, f"line{i}"] for i in range(3)],
                }
            ],
        }
    }
    respx.get("http://loki:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=loki_body)
    )

    with patch(
        "portal.mcp.devpod_tools.logs_tools.load_global",
        return_value=_make_logs_config(),
    ):
        result = await _logs_query(None, {"host": "h1", "limit": 3}, "user")

    assert result["count"] == 3
    assert result["truncated"] is True


@pytest.mark.asyncio
@respx.mock
async def test_logs_query_bearer_token_sent() -> None:
    loki_body = {"data": {"resultType": "streams", "result": []}}
    route = respx.get("http://loki:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=loki_body)
    )

    with patch(
        "portal.mcp.devpod_tools.logs_tools.load_global",
        return_value=_make_logs_config(push_token="mytoken"),
    ):
        await _logs_query(None, {"host": "h1"}, "user")

    assert route.called
    req = route.calls.last.request
    assert req.headers.get("authorization") == "Bearer mytoken"
