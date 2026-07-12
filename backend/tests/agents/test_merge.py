"""Spec 35b — cœur de merge (fusion du connecteur MCP dans un fichier partagé).

Le portail ne possède que ses serveurs (préfixe `portal-`) : il les upsert sous la
clé de tête, purge ses serveurs périmés, et ne touche JAMAIS aux réglages
utilisateur (autres sections, serveurs sans préfixe, commentaires).
"""

from __future__ import annotations

import json
import tomllib

import pytest

from portal.agents.merge import MergeError, merge_config

# ── Fragments possédés par le portail (ce que rend le template en mode merge) ──

_TOML_FRAGMENT = (
    "[mcp_servers.portal-default]\n"
    'url = "https://portal.example.org/mcp/"\n'
    'http_headers = { "Authorization" = "Bearer mcpk_NEW" }\n'
)

_JSON_FRAGMENT = json.dumps(
    {
        "mcpServers": {
            "portal-default": {
                "httpUrl": "https://portal.example.org/mcp/",
                "headers": {"Authorization": "Bearer mcpk_NEW"},
            }
        }
    }
)


def _toml(existing: str | None, fragment: str = _TOML_FRAGMENT) -> str:
    return merge_config(existing, fragment, fmt="toml", servers_key="mcp_servers")


def _json(existing: str | None, fragment: str = _JSON_FRAGMENT) -> str:
    return merge_config(existing, fragment, fmt="json", servers_key="mcpServers")


# ── TOML (Codex) ──────────────────────────────────────────────────────────────


def test_toml_preserves_user_settings_and_injects() -> None:
    existing = '# ma config\n[model]\nname = "gpt-5"\n'
    out = _toml(existing)

    parsed = tomllib.loads(out)
    assert parsed["model"]["name"] == "gpt-5"
    assert parsed["mcp_servers"]["portal-default"]["url"] == "https://portal.example.org/mcp/"
    assert "# ma config" in out  # commentaire utilisateur préservé


def test_toml_prunes_stale_portal_and_keeps_user_server() -> None:
    existing = (
        "[mcp_servers.portal-old]\n"
        'url = "https://old/mcp/"\n'
        "[mcp_servers.mine]\n"
        'url = "https://mine/"\n'
    )
    parsed = tomllib.loads(_toml(existing))
    servers = parsed["mcp_servers"]
    assert "portal-old" not in servers  # ancien serveur portail purgé
    assert servers["mine"]["url"] == "https://mine/"  # serveur utilisateur intact
    assert servers["portal-default"]["url"] == "https://portal.example.org/mcp/"


# ── JSON (Gemini) ─────────────────────────────────────────────────────────────


def test_json_preserves_and_reconciles() -> None:
    existing = json.dumps(
        {
            "theme": "dark",
            "mcpServers": {"portal-old": {"httpUrl": "x"}, "mine": {"httpUrl": "y"}},
        }
    )
    parsed = json.loads(_json(existing))
    assert parsed["theme"] == "dark"
    servers = parsed["mcpServers"]
    assert "portal-old" not in servers
    assert servers["mine"]["httpUrl"] == "y"
    assert servers["portal-default"]["httpUrl"] == "https://portal.example.org/mcp/"


# ── Création / absence ────────────────────────────────────────────────────────


@pytest.mark.parametrize("existing", [None, "", "   "])
def test_absent_existing_creates_json(existing: str | None) -> None:
    parsed = json.loads(_json(existing))
    assert parsed["mcpServers"]["portal-default"]["httpUrl"] == "https://portal.example.org/mcp/"


@pytest.mark.parametrize("existing", [None, ""])
def test_absent_existing_creates_toml(existing: str | None) -> None:
    parsed = tomllib.loads(_toml(existing))
    assert parsed["mcp_servers"]["portal-default"]["url"] == "https://portal.example.org/mcp/"


# ── Robustesse ────────────────────────────────────────────────────────────────


def test_malformed_json_existing_raises() -> None:
    with pytest.raises(MergeError):
        _json('{ "theme": ')


def test_malformed_toml_existing_raises() -> None:
    with pytest.raises(MergeError):
        _toml("[model\nname = ")


def test_json_existing_not_object_raises() -> None:
    with pytest.raises(MergeError):
        _json("[1, 2, 3]")


def test_idempotent_json() -> None:
    once = _json(None)
    twice = _json(once)
    assert json.loads(once) == json.loads(twice)


def test_idempotent_toml() -> None:
    once = _toml(None)
    twice = _toml(once)
    assert tomllib.loads(once) == tomllib.loads(twice)


# ── Zéro serveur exposé : purge seule, réglages utilisateur intacts ───────────


def test_zero_servers_prunes_only_json() -> None:
    existing = json.dumps(
        {"theme": "dark", "mcpServers": {"portal-old": {"httpUrl": "x"}, "mine": {"httpUrl": "y"}}}
    )
    empty_fragment = json.dumps({"mcpServers": {}})
    parsed = json.loads(_json(existing, empty_fragment))
    assert parsed["theme"] == "dark"
    assert "portal-old" not in parsed["mcpServers"]
    assert parsed["mcpServers"]["mine"]["httpUrl"] == "y"


def test_zero_servers_empty_fragment_string_prunes() -> None:
    existing = json.dumps({"mcpServers": {"portal-old": {"httpUrl": "x"}}})
    parsed = json.loads(_json(existing, ""))
    # portail purgé, et comme mcpServers existait on le garde (vide).
    assert parsed["mcpServers"] == {}


# ── Garde-fou : un serveur de fragment sans préfixe est refusé ────────────────


def test_fragment_server_without_prefix_raises() -> None:
    bad = json.dumps({"mcpServers": {"sneaky": {"httpUrl": "z"}}})
    with pytest.raises(MergeError):
        _json(None, bad)
