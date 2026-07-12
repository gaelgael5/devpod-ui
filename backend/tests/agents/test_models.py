"""Spec 35 — validation des modèles de types d'agents."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.agents.models import AgentTypeCreate, AgentTypeUpdate


def _create(**overrides: object) -> AgentTypeCreate:
    base: dict[str, object] = {
        "id": "claude",
        "label": "Claude Code",
        "filename": ".mcp.json",
        "template": '{"mcpServers": {}}',
        "target_path": "{{ project_root }}/.mcp.json",
    }
    base.update(overrides)
    return AgentTypeCreate(**base)  # type: ignore[arg-type]


def test_create_nominal() -> None:
    m = _create()
    assert m.id == "claude"
    assert m.filename == ".mcp.json"


@pytest.mark.parametrize("bad_id", ["Claude", "a" * 41, "-x", "x-", "a_b", ""])
def test_id_slug_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        _create(id=bad_id)


@pytest.mark.parametrize(
    "bad_filename",
    ["", "..", "a/b", "/etc/passwd", "../x", ".mcp.json/", "a\\b", ".", " "],
)
def test_filename_rejected(bad_filename: str) -> None:
    with pytest.raises(ValidationError):
        _create(filename=bad_filename)


@pytest.mark.parametrize("ok_filename", [".mcp.json", "settings.json", "config.toml"])
def test_filename_accepted(ok_filename: str) -> None:
    assert _create(filename=ok_filename).filename == ok_filename


def test_label_template_target_required() -> None:
    with pytest.raises(ValidationError):
        _create(label="")
    with pytest.raises(ValidationError):
        _create(template="")
    with pytest.raises(ValidationError):
        _create(target_path="")


def test_target_path_traversal_rejected() -> None:
    with pytest.raises(ValidationError):
        _create(target_path="{{ home }}/../../etc/cron.d/x")


def test_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        _create(unknown="x")


def test_update_model() -> None:
    m = AgentTypeUpdate(
        label="Gemini CLI",
        filename="settings.json",
        template="{}",
        target_path="{{ home }}/.gemini/settings.json",
        enabled=False,
    )
    assert m.enabled is False
    with pytest.raises(ValidationError):
        AgentTypeUpdate(
            label="",
            filename="settings.json",
            template="{}",
            target_path="{{ home }}/.gemini/settings.json",
            enabled=True,
        )


# ── mode (spec 35b T7) ──────────────────────────────────────────────────────


def test_create_mode_defaults_to_replace() -> None:
    assert _create().mode == "replace"


def test_create_mode_merge_accepted() -> None:
    assert _create(mode="merge").mode == "merge"


def test_create_mode_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        _create(mode="hybrid")


def test_update_mode_optional_none_means_unchanged() -> None:
    m = AgentTypeUpdate(
        label="Codex",
        filename="config.toml",
        template="{}",
        target_path="{{ home }}/.codex/config.toml",
        enabled=True,
    )
    assert m.mode is None


def test_update_mode_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentTypeUpdate(
            label="Codex",
            filename="config.toml",
            template="{}",
            target_path="{{ home }}/.codex/config.toml",
            enabled=True,
            mode="hybrid",
        )
