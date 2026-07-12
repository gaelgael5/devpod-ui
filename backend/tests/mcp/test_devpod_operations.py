from __future__ import annotations

import asyncio

import pytest

from portal.mcp.devpod_tools import operations


@pytest.fixture(autouse=True)
def _root(monkeypatch, tmp_path):
    monkeypatch.setattr(operations, "_data_root", lambda: tmp_path)


@pytest.mark.asyncio
async def test_get_list_create_update_deport_io_via_to_thread(monkeypatch) -> None:
    """Bug 025 : glob()/read_text()/yaml.safe_load/os.replace sont bloquants — ils
    doivent passer par asyncio.to_thread, jamais s'exécuter directement dans
    l'event loop d'un handler MCP async."""
    calls: list[object] = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(operations.asyncio, "to_thread", spy_to_thread)

    op = await operations.create_operation("workspace_create", "dev", "alice")
    await operations.get_operation(op["operation_id"])
    await operations.list_operations("alice")
    await operations.update_operation(op["operation_id"], state="done")

    assert operations._write_atomic in calls
    assert operations._get_operation_sync in calls
    assert operations._list_operations_sync in calls


@pytest.mark.asyncio
async def test_create_then_get():
    op = await operations.create_operation("workspace_create", "dev", "alice")
    assert op["state"] == "pending"
    assert op["kind"] == "workspace_create"
    assert op["workspace"] == "dev"
    assert op["owner_login"] == "alice"
    assert len(op["operation_id"]) == 32
    fetched = await operations.get_operation(op["operation_id"])
    assert fetched == op


@pytest.mark.asyncio
async def test_update_operation():
    op = await operations.create_operation("workspace_delete", "dev", "alice")
    upd = await operations.update_operation(
        op["operation_id"], state="done", result={"deleted": True}
    )
    assert upd["state"] == "done"
    assert upd["result"] == {"deleted": True}
    assert upd["updated_at"] >= op["created_at"]


@pytest.mark.asyncio
async def test_list_filters_by_owner_and_workspace():
    await operations.create_operation("workspace_create", "dev", "alice")
    await operations.create_operation("workspace_create", "proj", "alice")
    await operations.create_operation("workspace_create", "dev", "bob")
    rows = await operations.list_operations("alice")
    assert {r["workspace"] for r in rows} == {"dev", "proj"}
    rows_dev = await operations.list_operations("alice", workspace="dev")
    assert [r["workspace"] for r in rows_dev] == ["dev"]


@pytest.mark.asyncio
async def test_get_unknown_returns_none():
    assert await operations.get_operation("0" * 32) is None


@pytest.mark.asyncio
async def test_invalid_operation_id_rejected():
    with pytest.raises(operations.DevpodToolError):
        await operations.get_operation("../etc/passwd")


@pytest.mark.asyncio
async def test_update_unknown_raises():
    with pytest.raises(operations.DevpodToolError):
        await operations.update_operation("0" * 32, state="done")


@pytest.mark.asyncio
async def test_run_operation_now_success():
    op = await operations.create_operation("workspace_create", "dev", "alice")

    async def work():
        return {"workspace": "dev", "status": "running"}

    await operations.run_operation_now(op["operation_id"], work)
    final = await operations.get_operation(op["operation_id"])
    assert final["state"] == "done"
    assert final["result"] == {"workspace": "dev", "status": "running"}
    assert final["progress"] == 100


@pytest.mark.asyncio
async def test_run_operation_now_failure():
    op = await operations.create_operation("workspace_delete", "dev", "alice")

    async def work():
        raise ValueError("boom")

    await operations.run_operation_now(op["operation_id"], work)
    final = await operations.get_operation(op["operation_id"])
    assert final["state"] == "failed"
    assert "boom" in final["error"]


@pytest.mark.asyncio
async def test_launch_operation_returns_id_and_runs():
    done = {}

    async def work():
        done["ran"] = True
        return {"ok": True}

    oid = await operations.launch_operation("workspace_create", "dev", "alice", work)
    assert len(oid) == 32
    # laisse la task de fond s'exécuter
    for _ in range(50):
        op = await operations.get_operation(oid)
        if op["state"] == "done":
            break
        await asyncio.sleep(0.01)
    assert done.get("ran") is True
    final = await operations.get_operation(oid)
    assert final["result"] == {"ok": True}


@pytest.mark.asyncio
async def test_operations_get_isolated_by_owner():
    from portal.mcp import devpod_tools

    op = await operations.create_operation("workspace_create", "dev", "alice")
    res = await devpod_tools._operations_get(None, {"operation_id": op["operation_id"]}, "alice")
    assert res["state"] == "pending"
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._operations_get(None, {"operation_id": op["operation_id"]}, "bob")


@pytest.mark.asyncio
async def test_operations_list_for_owner():
    from portal.mcp import devpod_tools

    await operations.create_operation("workspace_create", "dev", "alice")
    res = await devpod_tools._operations_list(None, {}, "alice")
    assert len(res) == 1
