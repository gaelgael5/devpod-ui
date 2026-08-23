"""Découplage de la création VM de test : job en tâche de fond + endpoint de progression.

Le provisioning ne doit PAS être lié à la requête : on vérifie le cycle de vie du
job (accumulation/statut), l'endpoint de progression (auth propriétaire, 404), et la
purge des jobs terminés. Sans DB → tourne en local.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_user
from portal.routes import test_vm
from portal.routes.test_vm import _CreateJob
from portal.routes.test_vm import router as test_vm_router


def _client(login: str = "alice") -> TestClient:
    app = FastAPI()
    app.include_router(test_vm_router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login=login, roles=["dev"])
    return TestClient(app)


def test_create_job_accumulates_and_finishes() -> None:
    job = _CreateJob(login="alice")
    assert job.status == "running" and job.finished_at is None
    job.write(b"hello ")
    job.write(b"world")
    assert job.text() == "hello world"
    job.finish("ok")
    assert job.status == "ok" and job.finished_at is not None


def test_progress_unknown_job_404() -> None:
    test_vm._create_jobs.clear()
    resp = _client().get("/me/workspaces/ws1/test-vm/create/nope")
    assert resp.status_code == 404


def test_progress_returns_status_and_log() -> None:
    test_vm._create_jobs.clear()
    job = _CreateJob(login="alice")
    job.write(b"line1\n")
    job.finish("ok")
    test_vm._create_jobs["job-1"] = job
    resp = _client("alice").get("/me/workspaces/ws1/test-vm/create/job-1")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "log": "line1\n"}


def test_progress_wrong_owner_is_404() -> None:
    test_vm._create_jobs.clear()
    test_vm._create_jobs["job-2"] = _CreateJob(login="bob")
    resp = _client("alice").get("/me/workspaces/ws1/test-vm/create/job-2")
    assert resp.status_code == 404  # isolation par propriétaire


def test_purge_keeps_running_and_recent_drops_old() -> None:
    test_vm._create_jobs.clear()
    running = _CreateJob(login="a")  # en cours → gardé
    recent = _CreateJob(login="a")
    recent.finish("ok")  # terminé récemment → gardé
    old = _CreateJob(login="a")
    old.finish("ok")
    old.finished_at = datetime.now(UTC) - timedelta(seconds=test_vm._JOB_RETENTION_S + 10)
    test_vm._create_jobs.update({"r": running, "n": recent, "o": old})
    test_vm._purge_finished_jobs()
    assert set(test_vm._create_jobs) == {"r", "n"}
