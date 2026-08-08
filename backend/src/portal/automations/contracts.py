"""Contrats OpenAPI : import (URL, anti-SSRF), parsing, énumération d'opérations.

Un contrat décrit les opérations appelables par un automate. On importe le spec
(JSON ou YAML), on en extrait la version et la liste des opérations, et on résout
une opération (method + URL de base issue de `servers` + path) comme cible d'appel.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog
import yaml
from fastapi import HTTPException

from ..routes._ssrf import pinned_get

_log = structlog.get_logger(__name__)

# Verbes HTTP reconnus dans un Path Item OpenAPI.
_HTTP_METHODS = ("get", "put", "post", "delete", "patch", "options", "head", "trace")

# Borne de lecture d'un spec importé (anti-abus d'URL fournie par l'admin).
_SPEC_MAX_BYTES = 5 * 1024 * 1024


def parse_spec(raw: str) -> dict[str, Any]:
    """Parse un spec OpenAPI (JSON d'abord, YAML en repli). Lève 422 si invalide."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise HTTPException(
                status_code=422, detail=f"Spec ni JSON ni YAML valide : {exc}"
            ) from exc
    if not isinstance(parsed, dict) or "paths" not in parsed:
        raise HTTPException(status_code=422, detail="Spec OpenAPI invalide (clé 'paths' absente)")
    return parsed


async def fetch_spec(url: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Récupère et parse un spec OpenAPI depuis une URL (GET épinglé anti-SSRF)."""

    async def _run(c: httpx.AsyncClient) -> dict[str, Any]:
        resp = await pinned_get(c, url, timeout=10.0, max_bytes=_SPEC_MAX_BYTES)
        if resp.status_code != httpx.codes.OK:
            raise HTTPException(
                status_code=422, detail=f"Import du contrat : HTTP {resp.status_code} sur {url}"
            )
        return parse_spec(resp.text)

    if client is not None:
        return await _run(client)
    async with httpx.AsyncClient() as owned:
        return await _run(owned)


def extract_version(spec: dict[str, Any]) -> str:
    """`info.version` du spec (chaîne vide si absent)."""
    info = spec.get("info")
    if isinstance(info, dict):
        version = info.get("version")
        if isinstance(version, str):
            return version
    return ""


def _base_url(spec: dict[str, Any]) -> str:
    """URL de base : premier `servers[].url` absolu, sinon chaîne vide."""
    servers = spec.get("servers")
    if isinstance(servers, list):
        for srv in servers:
            if isinstance(srv, dict):
                url = srv.get("url")
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    return url.rstrip("/")
    return ""


def _operation_id(op: dict[str, Any], method: str, path: str) -> str:
    """operationId du spec, ou identifiant déterministe de repli."""
    op_id = op.get("operationId")
    if isinstance(op_id, str) and op_id:
        return op_id
    return f"{method.lower()} {path}"


def list_operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Énumère les opérations : {operation_id, method, path, summary}."""
    ops: list[dict[str, Any]] = []
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return ops
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            ops.append(
                {
                    "operation_id": _operation_id(op, method, path),
                    "method": method.upper(),
                    "path": path,
                    "summary": op.get("summary") or op.get("description") or "",
                }
            )
    return ops


def resolve_operation(spec: dict[str, Any], operation_id: str) -> dict[str, str] | None:
    """Résout une opération → {operation_id, method, path, url}. None si introuvable.

    `url` = URL de base du contrat (`servers`) + path. Sert de valeur par défaut
    proposée ; l'automate persiste ensuite sa propre URL cible.
    """
    base = _base_url(spec)
    for op in list_operations(spec):
        if op["operation_id"] == operation_id:
            return {
                "operation_id": op["operation_id"],
                "method": op["method"],
                "path": op["path"],
                "url": f"{base}{op['path']}" if base else op["path"],
            }
    return None
