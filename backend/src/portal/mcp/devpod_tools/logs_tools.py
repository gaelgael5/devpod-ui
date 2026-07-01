"""Primitive MCP `logs_query` — interrogation de l'agrégateur Loki (spec 31)."""

from __future__ import annotations

import datetime
import json
import urllib.parse
from typing import Any, Literal

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ...config.store import load_global
from .errors import DevpodToolError

_log = structlog.get_logger(__name__)

# Mapping paramètre MCP → label Loki réel (spec 30 §3.1 / spec 31 §4)
_LABEL: dict[str, str] = {
    "host": "host",
    "role": "role",
    "project": "compose_project",
    "service": "compose_service",
    "unit": "unit",
}


class LogsQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    host: str | None = None
    role: str | None = None
    project: str | None = None
    service: str | None = None
    unit: str | None = None
    level: str | None = None
    since: str = "1h"
    start: str | None = None
    end: str | None = None
    limit: int = Field(200, ge=1, le=5000)
    direction: Literal["forward", "backward"] = "backward"


def build_logql(p: LogsQueryParams) -> str:
    """Construit l'expression LogQL à partir des filtres structurés."""
    if p.query:
        return p.query
    sel = [f'{lbl}="{getattr(p, key)}"' for key, lbl in _LABEL.items() if getattr(p, key)]
    if not sel:
        raise ValueError(
            "logs_query: fournir une query LogQL ou au moins un filtre de label "
            "(host/role/project/service/unit)"
        )
    expr = "{" + ",".join(sel) + "}"
    if p.level:
        expr += f' | json | level="{p.level}"'
    return expr


def _flatten_streams(loki_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Aplatit les streams Loki en liste de {ts, labels, line}."""
    streams = loki_response.get("data", {}).get("result", [])
    lines: list[dict[str, Any]] = []
    for stream in streams:
        labels: dict[str, str] = stream.get("stream", {})
        for entry in stream.get("values", []):
            ts_ns_str, line = entry[0], entry[1]
            ts_ms = int(ts_ns_str) // 1_000_000
            dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.UTC)
            lines.append(
                {
                    "ts": dt.isoformat().replace("+00:00", "Z"),
                    "labels": labels,
                    "line": line,
                }
            )
    return lines


def _grafana_explore_url(grafana_url: str | None, logql: str, p: LogsQueryParams) -> str | None:
    """Construit un deep-link Grafana Explore pré-rempli avec la requête et la plage."""
    if not grafana_url:
        return None
    if p.start and p.end:
        range_from, range_to = p.start, p.end
    else:
        range_from = f"now-{p.since}"
        range_to = "now"
    left = json.dumps(
        {
            "datasource": "Loki",
            "queries": [{"refId": "A", "expr": logql}],
            "range": {"from": range_from, "to": range_to},
        },
        separators=(",", ":"),
    )
    base = grafana_url.rstrip("/")
    return f"{base}/explore?orgId=1&left={urllib.parse.quote(left, safe='')}"


async def _logs_query(
    conn: AsyncConnection,
    arguments: dict[str, Any],
    owner_login: str,
) -> dict[str, Any]:
    cfg = load_global()
    if not cfg.logs.enabled:
        raise DevpodToolError("logs_query non disponible (logs.enabled=false)")
    if not cfg.logs.loki_query_url:
        raise DevpodToolError("logs_query non disponible (loki_query_url non configuré)")

    try:
        params = LogsQueryParams.model_validate(arguments)
    except Exception as exc:
        raise DevpodToolError(str(exc)) from exc

    try:
        logql = build_logql(params)
    except ValueError as exc:
        raise DevpodToolError(str(exc)) from exc

    query_params: dict[str, Any] = {
        "query": logql,
        "limit": params.limit,
        "direction": params.direction,
    }
    if params.start and params.end:
        query_params["start"] = params.start
        query_params["end"] = params.end
    else:
        query_params["since"] = params.since

    headers: dict[str, str] = {}
    if cfg.logs.push_token:
        headers["Authorization"] = f"Bearer {cfg.logs.push_token}"

    url = f"{cfg.logs.loki_query_url.rstrip('/')}/loki/api/v1/query_range"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=query_params, headers=headers)
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        _log.warning(
            "loki_query_error",
            url=url,
            status=exc.response.status_code,
            body=body,
        )
        raise DevpodToolError(f"Loki a retourné {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        _log.warning("logs_backend_unreachable", url=url, error=str(exc))
        raise DevpodToolError(f"logs_backend_unreachable: {url} ({exc})") from exc

    lines = _flatten_streams(r.json())[: params.limit]
    return {
        "query": logql,
        "range": {
            "start": params.start,
            "end": params.end,
            "since": None if params.start else params.since,
        },
        "count": len(lines),
        "truncated": len(lines) == params.limit,
        "lines": lines,
        "grafana_url": _grafana_explore_url(cfg.logs.grafana_url, logql, params),
    }


LOGS_IMPLS: dict[str, Any] = {
    "logs_query": _logs_query,
}
