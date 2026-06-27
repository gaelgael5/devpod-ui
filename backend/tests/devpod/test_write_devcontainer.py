from __future__ import annotations

import json
from pathlib import Path


def test_write_devcontainer_without_profile_has_no_customizations(
    tmp_data_root: Path, global_cfg
) -> None:
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg)
    dc_path = svc._write_devcontainer("alice", "alice-myapp")
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    assert "customizations" not in content


def test_write_devcontainer_with_profile_injects_extensions(
    tmp_data_root: Path, global_cfg
) -> None:
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(
        slug="py",
        scope="user",
        name="Python Dev",
        extensions=["ms-python.python", "ms-python.debugpy"],
        settings={"editor.fontSize": 14},
    )
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    vscode = content["customizations"]["vscode"]
    assert "ms-python.python" in vscode["extensions"]
    assert "ms-python.debugpy" in vscode["extensions"]
    assert vscode["settings"]["editor.fontSize"] == 14


def test_write_devcontainer_profile_settings_override_existing(
    tmp_data_root: Path, global_cfg
) -> None:
    """Settings du profil sont prioritaires (fusion superficielle)."""
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(
        slug="py",
        scope="user",
        name="Python Dev",
        extensions=[],
        settings={"editor.fontSize": 16, "python.defaultInterpreterPath": "/usr/bin/python3"},
    )
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    assert content["customizations"]["vscode"]["settings"]["editor.fontSize"] == 16


def test_write_devcontainer_profile_extensions_deduplicated(
    tmp_data_root: Path, global_cfg
) -> None:
    """Les doublons dans extensions sont éliminés (dict.fromkeys)."""
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(
        slug="py",
        scope="user",
        name="Python Dev",
        extensions=["ms-python.python", "ms-python.python"],
        settings={},
    )
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    exts = content["customizations"]["vscode"]["extensions"]
    assert exts.count("ms-python.python") == 1


def test_write_devcontainer_empty_profile_no_customizations_block(
    tmp_data_root: Path, global_cfg
) -> None:
    """Profil sans extensions ni settings → pas de bloc customizations."""
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(slug="empty", scope="user", name="Empty", extensions=[], settings={})
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    assert "customizations" not in content
