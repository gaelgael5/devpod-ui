from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def _make_app(tmp_path: Path):
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["SCRIPTS_DIR"] = str(tmp_path / "scripts")
    mod._settings = None
    from portal.app import create_app

    return create_app()


def test_install_node_script_served(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "install-node.sh").write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/install-node.sh")
    assert resp.status_code == 200
    assert "bash" in resp.text


def test_install_node_script_missing_returns_404(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/install-node.sh")
    assert resp.status_code == 404


def test_health_returns_ok(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
