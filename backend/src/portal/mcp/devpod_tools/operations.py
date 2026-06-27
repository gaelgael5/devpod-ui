"""Suivi des opérations asynchrones (spec 25 §B).

Un fichier YAML par opération sous /data/operations/. Écriture atomique
(tempfile + os.replace). Source de vérité = filesystem (pas de DB).
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from ...config.store import _data_root
from .errors import DevpodToolError

_OP_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_op_tasks: set[asyncio.Task[None]] = set()


def _operations_root() -> Path:
    root = _data_root() / "operations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _op_path(operation_id: str) -> Path:
    if not _OP_ID_RE.fullmatch(operation_id):
        raise DevpodToolError(f"operation_id invalide: {operation_id!r}")
    return _operations_root() / f"{operation_id}.yaml"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def create_operation(kind: str, workspace: str, owner_login: str) -> dict[str, Any]:
    now = _now()
    op: dict[str, Any] = {
        "operation_id": uuid.uuid4().hex,
        "kind": kind,
        "workspace": workspace,
        "owner_login": owner_login,
        "state": "pending",
        "progress": 0,
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    _write_atomic(_op_path(op["operation_id"]), op)
    return op


def get_operation(operation_id: str) -> dict[str, Any] | None:
    path = _op_path(operation_id)
    if not path.exists():
        return None
    result = yaml.safe_load(path.read_text(encoding="utf-8"))
    return result if isinstance(result, dict) else None


def update_operation(operation_id: str, **fields: Any) -> dict[str, Any]:
    op = get_operation(operation_id)
    if op is None:
        raise DevpodToolError(f"opération inconnue: {operation_id}")
    op.update(fields)
    op["updated_at"] = _now()
    _write_atomic(_op_path(operation_id), op)
    return op


def list_operations(owner_login: str, workspace: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _operations_root().glob("*.yaml"):
        op = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(op, dict) or op.get("owner_login") != owner_login:
            continue
        if workspace is not None and op.get("workspace") != workspace:
            continue
        rows.append(op)
    rows.sort(key=lambda o: o.get("created_at", ""))
    return rows


async def run_operation_now(operation_id: str, work: Callable[[], Awaitable[Any]]) -> None:
    update_operation(operation_id, state="running")
    try:
        result = await work()
        update_operation(operation_id, state="done", progress=100, result=result)
    except Exception as exc:
        update_operation(operation_id, state="failed", error=f"{type(exc).__name__}: {exc}")


def launch_operation(
    kind: str, workspace: str, owner_login: str, work: Callable[[], Awaitable[Any]]
) -> str:
    op = create_operation(kind, workspace, owner_login)
    oid = cast(str, op["operation_id"])
    task = asyncio.create_task(run_operation_now(oid, work))
    _op_tasks.add(task)
    task.add_done_callback(_op_tasks.discard)
    return oid
