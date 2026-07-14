"""Service de placement : install npx + vérification de hash post-install.

ws_exec et les primitives DB sont mockés — la logique testée : commandes
émises (source/skill/agent corrects, shell-quotées), verdict verified vs
unverified, retombée du grant en pending sur dérive, retrait best-effort.
"""
from __future__ import annotations

import pytest

import portal.skills.placement as mod

GRANT = {
    "id": 3,
    "user_subject": "sub-alice",
    "skill_id": "github/awesome-copilot/git-commit",
    "approved_hash": "sha256:aaa",
    "statut": "granted",
}


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, exec_results: list[tuple[int, str]]):
        self.exec_calls: list[str] = []
        self.db_calls: list[tuple] = []
        results = iter(exec_results)

        async def fake_ws_exec(login, ws_id, command, timeout=30.0):
            self.exec_calls.append(command)
            return next(results)

        async def fake_create(grant_id, ws_id, conn):
            self.db_calls.append(("create", grant_id, ws_id))
            return {"id": 11, "grant_id": grant_id, "workspace_id": ws_id}, True

        async def fake_placed(pid, h, conn):
            self.db_calls.append(("placed", pid, h))
            return True

        async def fake_verified(pid, ok, conn):
            self.db_calls.append(("verified", pid, ok))
            return True

        async def fake_pending(gid, conn):
            self.db_calls.append(("pending", gid))
            return True

        async def fake_delete(pid, conn):
            self.db_calls.append(("delete", pid))
            return True

        monkeypatch.setattr(mod, "ws_exec", fake_ws_exec)
        monkeypatch.setattr(mod, "create_or_get_placement", fake_create)
        monkeypatch.setattr(mod, "set_placement_placed", fake_placed)
        monkeypatch.setattr(mod, "set_placement_verified", fake_verified)
        monkeypatch.setattr(mod, "mark_grant_pending", fake_pending)
        monkeypatch.setattr(mod, "delete_placement", fake_delete)


@pytest.mark.asyncio
async def test_place_verified_on_hash_match(monkeypatch):
    h = Harness(monkeypatch, [(0, "Done!"), (0, "aaa  /workspaces/x/.claude/…")])
    # installed sha256:aaa == approved sha256:aaa
    result = await mod.place_skill("alice", "alice-ws", GRANT, conn=None)
    assert result["statut"] == "verified"
    install_cmd = h.exec_calls[0]
    assert "npx --yes skills add github/awesome-copilot --skill git-commit" in install_cmd
    assert "--agent claude-code" in install_cmd and "--copy" in install_cmd
    assert ("verified", 11, True) in h.db_calls
    assert all(c[0] != "pending" for c in h.db_calls)  # pas de retombée


@pytest.mark.asyncio
async def test_place_unverified_on_drift_marks_grant_pending(monkeypatch):
    h = Harness(monkeypatch, [(0, "Done!"), (0, "bbb  /workspaces/…")])
    result = await mod.place_skill("alice", "alice-ws", GRANT, conn=None)
    assert result["statut"] == "unverified"
    assert ("verified", 11, False) in h.db_calls
    # Dérive (HEAD non épinglé) → le grant retombe pending (re-validation).
    assert ("pending", 3) in h.db_calls


@pytest.mark.asyncio
async def test_place_install_failure_raises(monkeypatch):
    h = Harness(monkeypatch, [(1, "npm ERR! boom")])
    with pytest.raises(mod.PlacementError):
        await mod.place_skill("alice", "alice-ws", GRANT, conn=None)
    # Rien n'a été marqué placed/verified.
    assert all(c[0] in ("create",) for c in h.db_calls)


@pytest.mark.asyncio
async def test_remove_deletes_placement_even_if_rm_fails(monkeypatch):
    h = Harness(monkeypatch, [(1, "rm: cannot remove")])
    await mod.remove_skill("alice", "alice-ws", GRANT["skill_id"], 11, conn=None)
    assert h.exec_calls[0].startswith("rm -rf /workspaces/alice-ws/.claude/skills/git-commit")
    assert ("delete", 11) in h.db_calls
