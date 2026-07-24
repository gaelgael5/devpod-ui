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


# ---------------------------------------------------------------------------
# Image de base portée par le profil
# ---------------------------------------------------------------------------


def test_write_devcontainer_uses_profile_image(tmp_data_root: Path, global_cfg) -> None:
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(
        slug="py",
        scope="shared",
        name="Python Dev",
        image="mcr.microsoft.com/devcontainers/python:3.12",
    )
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    assert content["image"] == "mcr.microsoft.com/devcontainers/python:3.12"


def test_write_devcontainer_default_image_without_profile_image(
    tmp_data_root: Path, global_cfg
) -> None:
    """Profil sans image (ou pas de profil) → image par défaut du portail."""
    from portal.devpod.service import _DEFAULT_IMAGE, DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    dc_path = svc._write_devcontainer("alice", "alice-myapp")
    assert json.loads(dc_path.read_text(encoding="utf-8"))["image"] == _DEFAULT_IMAGE

    profile = Profile(slug="py", scope="user", name="Sans image")
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    assert json.loads(dc_path.read_text(encoding="utf-8"))["image"] == _DEFAULT_IMAGE


# ---------------------------------------------------------------------------
# Spec 35 — fragments agents (mount ro + postCreate)
# ---------------------------------------------------------------------------


def test_write_devcontainer_agent_mounts_and_post_create(tmp_data_root: Path, global_cfg) -> None:
    from portal.devpod.service import DevPodService

    mount = (
        "source=/home/u/.devpod-portal/agent-config/alice-myapp,"
        "target=/opt/agent-config,type=bind,readonly"
    )
    link = 'ln -sfn "/opt/agent-config/claude/.mcp.json" "/workspaces/alice-myapp/.mcp.json"'
    svc = DevPodService(global_cfg=global_cfg)
    dc_path = svc._write_devcontainer(
        "alice",
        "alice-myapp",
        extra_mounts=[mount],
        extra_post_create=[link],
    )
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    assert content["mounts"] == [mount]
    assert content["postCreateCommand"].startswith("ln -sfn")


def test_write_devcontainer_agent_post_create_appended_after_clones(
    tmp_data_root: Path, global_cfg
) -> None:
    from portal.config.models import SourceSpec
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg)
    dc_path = svc._write_devcontainer(
        "alice",
        "alice-myapp",
        extra_sources=[SourceSpec(url="https://github.com/org/lib.git")],
        extra_post_create=["ln -sfn a b"],
    )
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    pc = content["postCreateCommand"]
    # Le clone est durci (credential.helper vide) mais reste avant le symlink agent.
    assert "clone" in pc
    assert pc.index("clone") < pc.index("ln -sfn a b")
