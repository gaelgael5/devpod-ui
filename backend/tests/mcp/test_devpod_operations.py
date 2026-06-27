from __future__ import annotations

import asyncio

import pytest

from portal.mcp.devpod_tools import operations


@pytest.fixture(autouse=True)
def _root(monkeypatch, tmp_path):
    monkeypatch.setattr(operations, "_data_root", lambda: tmp_path)


def test_create_then_get():
    op = operations.create_operation("workspace_create", "dev", "alice")
    assert op["state"] == "pending"
    assert op["kind"] == "workspace_create"
    assert op["workspace"] == "dev"
    assert op["owner_login"] == "alice"
    assert len(op["operation_id"]) == 32
    fetched = operations.get_operation(op["operation_id"])
    assert fetched == op


def test_update_operation():
    op = operations.create_operation("workspace_delete", "dev", "alice")
    upd = operations.update_operation(op["operation_id"], state="done", result={"deleted": True})
    assert upd["state"] == "done"
    assert upd["result"] == {"deleted": True}
    assert upd["updated_at"] >= op["created_at"]


def test_list_filters_by_owner_and_workspace():
    operations.create_operation("workspace_create", "dev", "alice")
    operations.create_operation("workspace_create", "proj", "alice")
    operations.create_operation("workspace_create", "dev", "bob")
    rows = operations.list_operations("alice")
    assert {r["workspace"] for r in rows} == {"dev", "proj"}
    rows_dev = operations.list_operations("alice", workspace="dev")
    assert [r["workspace"] for r in rows_dev] == ["dev"]


def test_get_unknown_returns_none():
    assert operations.get_operation("0" * 32) is None


def test_invalid_operation_id_rejected():
    with pytest.raises(operations.DevpodToolError):
        operations.get_operation("../etc/passwd")


def test_update_unknown_raises():
    with pytest.raises(operations.DevpodToolError):
        operations.update_operation("0" * 32, state="done")


@pytest.mark.asyncio
async def test_run_operation_now_success():
    op = operations.create_operation("workspace_create", "dev", "alice")
    async def work():
        return {"workspace": "dev", "status": "running"}
    await operations.run_operation_now(op["operation_id"], work)
    final = operations.get_operation(op["operation_id"])
    assert final["state"] == "done"
    assert final["result"] == {"workspace": "dev", "status": "running"}
    assert final["progress"] == 100


@pytest.mark.asyncio
async def test_run_operation_now_failure():
    op = operations.create_operation("workspace_delete", "dev", "alice")
    async def work():
        raise ValueError("boom")
    await operations.run_operation_now(op["operation_id"], work)
    final = operations.get_operation(op["operation_id"])
    assert final["state"] == "failed"
    assert "boom" in final["error"]


@pytest.mark.asyncio
async def test_launch_operation_returns_id_and_runs():
    done = {}
    async def work():
        done["ran"] = True
        return {"ok": True}
    oid = operations.launch_operation("workspace_create", "dev", "alice", work)
    assert len(oid) == 32
    # laisse la task de fond s'exécuter
    for _ in range(50):
        if operations.get_operation(oid)["state"] == "done":
            break
        await asyncio.sleep(0.01)
    assert done.get("ran") is True
    assert operations.get_operation(oid)["result"] == {"ok": True}
