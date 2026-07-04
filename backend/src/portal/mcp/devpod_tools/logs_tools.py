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
    "job": "job",
}


class LogsQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    host: str | None = None
    role: str | None = None
    project: str | None = None
    service: str | None = None
    unit: str | None = None
    job: str | None = None
    level: str | None = None
    since: str = "1h"
    start: str | None = None
    end: str | None = None
    limit: int = Field(200, ge=1, le=5000)
    direction: Literal["forward", "backward"] = "backward"


def _escape_logql_string(value: str) -> str:
    """Échappe un littéral de chaîne LogQL (backslash puis guillemet, dans cet ordre —
    sinon un `"` initial se ferait ré-échapper par la substitution du backslash).

    Sans cet échappement, une valeur de filtre contenant un `"` casse le matcher et
    injecte du LogQL arbitraire dans la requête (bug 027)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_logql(p: LogsQueryParams) -> str:
    """Construit l'expression LogQL à partir des filtres structurés."""
    if p.query:
        return p.query
    sel = [
        f'{lbl}="{_escape_logql_string(getattr(p, key))}"'
        for key, lbl in _LABEL.items()
        if getattr(p, key)
    ]
    if not sel:
        raise ValueError(
            "logs_query: fournir une query LogQL ou au moins un filtre de label "
            "(host/role/project/service/unit/job)"
        )
    expr = "{" + ",".join(sel) + "}"
    if p.level:
        expr += f' | json | level="{_escape_logql_string(p.level)}"'
    return expr


def _flatten_streams(loki_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Aplatit les streams Loki en liste de {ts, labels, line}.

    Valide la forme de chaque entrée avant de la déballer : une réponse Loki
    malformée (entrée qui n'est pas une paire [ts, line], timestamp non
    numérique) lève DevpodToolError plutôt qu'un IndexError/ValueError brut qui
    échapperait au dispatch MCP (même défaut que le bug 017, bug 028).
    """
    data = loki_response.get("data")
    streams = data.get("result", []) if isinstance(data, dict) else []
    if not isinstance(streams, list):
        raise DevpodToolError(f"réponse Loki malformée : data.result inattendu {streams!r}")
    lines: list[dict[str, Any]] = []
    for stream in streams:
        if not isinstance(stream, dict):
            raise DevpodToolError(f"réponse Loki malformée : stream inattendu {stream!r}")
        labels: dict[str, str] = stream.get("stream", {})
        for entry in stream.get("values", []):
            if not isinstance(entry, list | tuple) or len(entry) != 2:
                raise DevpodToolError(f"réponse Loki malformée : entrée inattendue {entry!r}")
            ts_ns_str, line = entry
            try:
                ts_ms = int(ts_ns_str) // 1_000_000
            except (TypeError, ValueError) as exc:
                raise DevpodToolError(
                    f"réponse Loki malformée : timestamp invalide {ts_ns_str!r}"
                ) from exc
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

    try:
        lines = _flatten_streams(r.json())[: params.limit]
    except ValueError as exc:
        # r.json() lève json.JSONDecodeError (sous-classe de ValueError) si le
        # corps n'est pas du JSON valide — même traitement que les erreurs de
        # structure levées par _flatten_streams (bug 028).
        raise DevpodToolError(f"réponse Loki illisible : {exc}") from exc
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
