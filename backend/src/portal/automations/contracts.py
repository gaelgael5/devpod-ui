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


def servers(spec: dict[str, Any]) -> list[str]:
    """Liste des `servers[].url` absolus déclarés (base d'appel candidate pour l'IHM)."""
    out: list[str] = []
    raw = spec.get("servers")
    if isinstance(raw, list):
        for srv in raw:
            if isinstance(srv, dict):
                url = srv.get("url")
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    out.append(url.rstrip("/"))
    return out


def _operation_id(op: dict[str, Any], method: str, path: str) -> str:
    """operationId du spec, ou identifiant déterministe de repli."""
    op_id = op.get("operationId")
    if isinstance(op_id, str) and op_id:
        return op_id
    return f"{method.lower()} {path}"


def _resolve_ref(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Suit un `$ref` interne (#/components/schemas/X) une fois ; sinon retourne tel quel."""
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema
    node: Any = spec
    for part in ref[2:].split("/"):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return node if isinstance(node, dict) else {}


def _example_from_schema(spec: dict[str, Any], schema: dict[str, Any], depth: int = 0) -> Any:
    """Exemple minimal dérivé d'un JSON Schema OpenAPI (résolution $ref, garde de profondeur)."""
    if depth > 6 or not isinstance(schema, dict):
        return None
    schema = _resolve_ref(spec, schema)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if isinstance(schema.get("allOf"), list):
        merged: dict[str, Any] = {}
        for sub in schema["allOf"]:
            part = _example_from_schema(spec, sub, depth + 1)
            if isinstance(part, dict):
                merged.update(part)
        return merged
    t = schema.get("type")
    props = schema.get("properties")
    if t == "object" or isinstance(props, dict):
        obj: dict[str, Any] = {}
        for key, sub in (props or {}).items():
            if isinstance(sub, dict):
                obj[key] = _example_from_schema(spec, sub, depth + 1)
        return obj
    if t == "array":
        items = schema.get("items")
        return [_example_from_schema(spec, items, depth + 1)] if isinstance(items, dict) else []
    if t == "integer" or t == "number":
        return 0
    if t == "boolean":
        return False
    return ""


def _body_skeleton(spec: dict[str, Any], op: dict[str, Any]) -> Any:
    """Squelette JSON du corps de requête (application/json), ou None si pas de corps."""
    body = op.get("requestBody")
    if not isinstance(body, dict):
        return None
    body = _resolve_ref(spec, body)
    content = body.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict) or not isinstance(media.get("schema"), dict):
        return None
    return _example_from_schema(spec, media["schema"])


def _auth_headers(spec: dict[str, Any], op: dict[str, Any]) -> list[dict[str, str]]:
    """En-têtes d'auth requis par l'opération (dérivés des securitySchemes).

    http/bearer, oauth2 et openIdConnect → {header: Authorization,
    value_prefix: "Bearer "} (le jeton porteur, ex. l'apikey Termix `tmx_…`) ;
    apiKey in header → {header: <name>, value_prefix: ""}. Dédupliqué par header.
    """
    security = op.get("security")
    if security is None:
        security = spec.get("security")
    if not isinstance(security, list):
        return []
    comps = spec.get("components")
    schemes = comps.get("securitySchemes") if isinstance(comps, dict) else None
    if not isinstance(schemes, dict):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for req in security:
        if not isinstance(req, dict):
            continue
        for name in req:
            sch = schemes.get(name)
            if not isinstance(sch, dict):
                continue
            header = value_prefix = ""
            sch_type = sch.get("type")
            if sch_type == "http" and str(sch.get("scheme", "")).lower() == "bearer":
                header, value_prefix = "Authorization", "Bearer "
            elif sch_type in ("oauth2", "openIdConnect"):
                # Jeton porteur en Authorization: Bearer <token>.
                header, value_prefix = "Authorization", "Bearer "
            elif sch_type == "apiKey" and sch.get("in") == "header":
                hn = sch.get("name")
                if isinstance(hn, str):
                    header, value_prefix = hn, ""
            if header and header.lower() not in seen:
                seen.add(header.lower())
                out.append({"header": header, "value_prefix": value_prefix})
    return out


def list_operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Énumère les opérations : {operation_id, method, path, url, summary}.

    `url` = URL de base du contrat (`servers`) + path — valeur par défaut proposée
    à l'IHM pour préremplir la cible d'un automate.
    """
    ops: list[dict[str, Any]] = []
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return ops
    base = _base_url(spec)
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
                    "url": f"{base}{path}" if base else path,
                    "summary": op.get("summary") or op.get("description") or "",
                    "body_skeleton": _body_skeleton(spec, op),
                    "auth_headers": _auth_headers(spec, op),
                }
            )
    return ops


def resolve_operation(spec: dict[str, Any], operation_id: str) -> dict[str, str] | None:
    """Résout une opération → {operation_id, method, path, url}. None si introuvable.

    `url` = URL de base du contrat (`servers`) + path. Sert de valeur par défaut
    proposée ; l'automate persiste ensuite sa propre URL cible.
    """
    for op in list_operations(spec):
        if op["operation_id"] == operation_id:
            return {
                "operation_id": op["operation_id"],
                "method": op["method"],
                "path": op["path"],
                "url": op["url"],
            }
    return None
