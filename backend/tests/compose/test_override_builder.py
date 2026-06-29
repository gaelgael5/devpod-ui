"""Tests pour portal.compose.override_builder."""
import yaml

from portal.compose.override_builder import LABEL_PREFIX, build_override

_COMPOSE = """
services:
  browser:
    image: chromium:1.0.0
    ports:
      - 3005:3000
  db:
    image: postgres:15
"""


def test_labels_on_all_services() -> None:
    override = build_override(
        _COMPOSE,
        deployment_id="dep-42",
        template_id="chromium-v1",
        owner_login="alice",
    )
    parsed = yaml.safe_load(override)
    for svc in ("browser", "db"):
        labels = parsed["services"][svc]["labels"]
        assert labels[f"{LABEL_PREFIX}.deployment_id"] == "dep-42"
        assert labels[f"{LABEL_PREFIX}.template_id"] == "chromium-v1"
        assert labels[f"{LABEL_PREFIX}.owner"] == "alice"


def test_returns_valid_yaml() -> None:
    override = build_override(
        _COMPOSE,
        deployment_id="x",
        template_id="y",
        owner_login="z",
    )
    parsed = yaml.safe_load(override)
    assert "services" in parsed


def test_empty_services_returns_empty_string() -> None:
    assert build_override("services: {}", deployment_id="x", template_id="y", owner_login="z") == ""


def test_bad_yaml_returns_empty_string() -> None:
    assert (
        build_override("not: valid: yaml: [", deployment_id="x", template_id="y", owner_login="z")
        == ""
    )


def test_contains_two_services() -> None:
    override = build_override(
        _COMPOSE,
        deployment_id="d",
        template_id="t",
        owner_login="u",
    )
    parsed = yaml.safe_load(override)
    assert set(parsed["services"].keys()) == {"browser", "db"}
