"""Spec 35b T4′ — orchestrateur de livraison des fichiers agents PAR ÉCRITURE
conteneur (canal T3), pour que `restart` suffise (jamais recreate).

Un seul chemin unifie les deux modes :
- `replace` (Claude) : le template rend le fichier complet, écrit tel quel ;
- `merge` (Codex/Gemini) : le template rend un fragment `portal-*`, fusionné dans
  le fichier existant du conteneur (réglages utilisateur préservés).

Les bords (DB agent_types, rotation de clefs, canal conteneur) sont mockés ; le
rendu Jinja et la fusion sont réels (déjà couverts par leurs propres tests).
"""

from __future__ import annotations

import pytest

from portal.agents import push
from portal.agents.keys import WorkspaceKey
from portal.agents.provisioning import AgentProvisionError
from portal.agents.push import push_agent_files

_CLAUDE_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "type": "http",
      "url": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

# Fragments possédés par le portail (préfixe portal- obligatoire côté merge).
# Codex = table inline TOML (`{ "k" = v }`) ; Gemini = objet JSON.
_CODEX_TEMPLATE = """\
{%- for s in servers %}
[mcp_servers.portal-{{ s.name }}]
url = {{ s.url | tojson }}
http_headers = { "Authorization" = {{ ("Bearer " ~ s.token) | tojson }} }
{% endfor -%}
"""

_GEMINI_TEMPLATE = """\
{"mcpServers": {
{%- for s in servers %}
  "portal-{{ s.name }}": {"httpUrl": {{ s.url | tojson }},
    "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}}{{ "," if not loop.last }}
{%- endfor %}
}}
"""


def _row(**kw: object) -> dict[str, object]:
    base = {
        "id": "claude",
        "template": _CLAUDE_TEMPLATE,
        "filename": ".mcp.json",
        "target_path": "{{ project_root }}/.mcp.json",
        "mode": "replace",
        "enabled": True,
    }
    base.update(kw)
    return base


class _Channel:
    """Fake du canal conteneur : capture les écritures, sert des lectures scriptées."""

    def __init__(self, existing: dict[str, str] | None = None, home: str = "/home/vscode") -> None:
        self.existing = existing or {}
        self.home = home
        self.writes: dict[str, str] = {}
        self.exec_calls: list[str] = []
        # Gate d'idempotence : par défaut aucune empreinte stockée → livraison.
        self.stored_hash: str | None = None
        self.files_present: bool = True

    async def read(self, login: str, ws_id: str, path: str, **_: object) -> str | None:
        return self.existing.get(path)

    async def write(self, login: str, ws_id: str, path: str, content: str, **_: object) -> None:
        self.writes[path] = content

    async def ws_exec(
        self, login: str, ws_id: str, command: str, timeout: float = 30.0
    ) -> tuple[int, str]:
        self.exec_calls.append(command)
        if "$HOME" in command:
            return 0, self.home
        return 0, ""


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    ch: _Channel,
    rows: list[dict[str, object]],
    recorded: list[tuple[str, str, str]] | None = None,
) -> None:
    async def _load(agents: list[str]) -> list[dict[str, object]]:
        return rows

    async def _rotate(login: str, ws_id: str) -> list[WorkspaceKey]:
        return [
            WorkspaceKey(
                apikey_id="k1", profile_id="p1", profile_name="Claude code", token="mcpk_TESTTOKEN"
            )
        ]

    async def _record(login: str, ws_id: str, fp: str) -> None:
        if recorded is not None:
            recorded.append((login, ws_id, fp))

    async def _exposed(login: str) -> list[tuple[str, str]]:
        return [("p1", "Claude code")]

    async def _stored(login: str, ws_id: str) -> str | None:
        return ch.stored_hash

    async def _present(login: str, ws_id: str, targets: list[str]) -> bool:
        return ch.files_present

    monkeypatch.setattr(push, "_load_requested_agent_types", _load)
    monkeypatch.setattr(push, "_rotate_keys", _rotate)
    monkeypatch.setattr(push, "_record_config_hash", _record)
    monkeypatch.setattr(push, "_exposed_profiles", _exposed)
    monkeypatch.setattr(push, "_stored_config_hash", _stored)
    monkeypatch.setattr(push, "_targets_present", _present)
    monkeypatch.setattr(push, "read_container_file", ch.read)
    monkeypatch.setattr(push, "write_container_file", ch.write)
    monkeypatch.setattr(push, "ws_exec", ch.ws_exec)


async def _run(ch: _Channel, home: str | None = "/home/vscode") -> list[str]:
    return await push_agent_files(
        login="bob",
        ws_id="bob-app",
        ws_name="app",
        agents=["claude"],
        mcp_url="https://portal.example.org/mcp/",
        project_root="/workspaces/bob-app",
        home=home,
    )


# ── replace ───────────────────────────────────────────────────────────────


async def test_replace_writes_full_file_into_container(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _Channel()
    _wire(monkeypatch, ch, [_row()])

    written = await _run(ch)

    assert written == ["claude"]
    out = ch.writes["/workspaces/bob-app/.mcp.json"]
    assert "mcpk_TESTTOKEN" in out
    assert "https://portal.example.org/mcp/" in out
    assert '"claude-code"' in out  # slug de "Claude code"


async def test_push_records_config_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Après livraison, l'empreinte de config est enregistrée (base du resync idempotent)."""
    from portal.agents.sync_state import compute_agent_fingerprint

    ch = _Channel()
    recorded: list[tuple[str, str, str]] = []
    rows = [_row()]
    _wire(monkeypatch, ch, rows, recorded=recorded)

    await _run(ch)

    assert len(recorded) == 1
    login, ws_id, fp = recorded[0]
    assert (login, ws_id) == ("bob", "bob-app")
    assert fp == compute_agent_fingerprint(
        agent_rows=rows,
        profiles=[("p1", "Claude code")],
        mcp_url="https://portal.example.org/mcp/",
        project_root="/workspaces/bob-app",
        ws_name="app",
        owner="bob",
        ws_id="bob-app",
    )


# ── idempotence : ne pas rotationner quand rien ne change ────────────────────


def _expected_fp(rows: list[dict[str, object]]) -> str:
    from portal.agents.sync_state import compute_agent_fingerprint

    return compute_agent_fingerprint(
        agent_rows=rows,
        profiles=[("p1", "Claude code")],
        mcp_url="https://portal.example.org/mcp/",
        project_root="/workspaces/bob-app",
        ws_name="app",
        owner="bob",
        ws_id="bob-app",
    )


async def test_skips_when_hash_matches_and_files_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empreinte stockée == courante ET fichiers présents → aucun écrit, aucune rotation."""
    ch = _Channel()
    rows = [_row()]
    rotated: list[bool] = []

    async def _rotate_spy(login: str, ws_id: str):  # type: ignore[no-untyped-def]
        rotated.append(True)
        return []

    _wire(monkeypatch, ch, rows)
    monkeypatch.setattr(push, "_rotate_keys", _rotate_spy)
    ch.stored_hash = _expected_fp(rows)
    ch.files_present = True

    written = await _run(ch)

    assert written == []
    assert ch.writes == {}  # rien réécrit
    assert rotated == []  # clef JAMAIS rotationnée → l'agent garde son token


async def test_delivers_when_files_missing_even_if_hash_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conteneur recréé (fichiers absents) : on livre malgré l'empreinte identique."""
    ch = _Channel()
    rows = [_row()]
    _wire(monkeypatch, ch, rows)
    ch.stored_hash = _expected_fp(rows)
    ch.files_present = False

    written = await _run(ch)

    assert written == ["claude"]
    assert "mcpk_TESTTOKEN" in ch.writes["/workspaces/bob-app/.mcp.json"]


async def test_delivers_when_hash_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Config changée (empreinte différente) : livraison même si fichiers présents."""
    ch = _Channel()
    rows = [_row()]
    _wire(monkeypatch, ch, rows)
    ch.stored_hash = "stale-hash"
    ch.files_present = True

    written = await _run(ch)

    assert written == ["claude"]


async def test_replace_target_under_repo_adds_git_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _Channel()
    _wire(monkeypatch, ch, [_row()])

    await _run(ch)

    joined = "\n".join(ch.exec_calls)
    assert ".git/info/exclude" in joined
    assert "/.mcp.json" in joined


# ── merge ─────────────────────────────────────────────────────────────────


async def test_merge_preserves_user_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    target = "/home/vscode/.codex/config.toml"
    ch = _Channel(existing={target: '# mon réglage\n[tool]\nfoo = "bar"\n'})
    rows = [
        _row(
            id="codex",
            template=_CODEX_TEMPLATE,
            filename="config.toml",
            target_path="{{ home }}/.codex/config.toml",
            mode="merge",
        )
    ]
    _wire(monkeypatch, ch, rows)

    await _run(ch)

    out = ch.writes[target]
    assert 'foo = "bar"' in out  # réglage utilisateur intact
    assert "portal-claude-code" in out  # serveur du portail injecté
    assert "mcpk_TESTTOKEN" in out


async def test_merge_creates_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _Channel()  # aucun fichier existant → read renvoie None
    rows = [
        _row(
            id="codex",
            template=_CODEX_TEMPLATE,
            filename="config.toml",
            target_path="{{ home }}/.codex/config.toml",
            mode="merge",
        )
    ]
    _wire(monkeypatch, ch, rows)

    await _run(ch)

    assert "portal-claude-code" in ch.writes["/home/vscode/.codex/config.toml"]


async def test_target_outside_repo_skips_git_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _Channel()
    rows = [
        _row(
            id="gemini",
            template=_GEMINI_TEMPLATE,
            filename="settings.json",
            target_path="{{ home }}/.gemini/settings.json",
            mode="merge",
        )
    ]
    _wire(monkeypatch, ch, rows)

    await _run(ch)

    assert all(".git/info/exclude" not in c for c in ch.exec_calls)


# ── home résolu à chaud + robustesse ────────────────────────────────────────


async def test_home_resolved_via_ws_exec_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _Channel(home="/home/custom")
    rows = [
        _row(
            id="gemini",
            template=_GEMINI_TEMPLATE,
            filename="settings.json",
            target_path="{{ home }}/.gemini/settings.json",
            mode="merge",
        )
    ]
    _wire(monkeypatch, ch, rows)

    await _run(ch, home=None)  # doit résoudre $HOME dans le conteneur

    assert "/home/custom/.gemini/settings.json" in ch.writes


async def test_unknown_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _Channel()

    async def _load(agents: list[str]) -> list[dict[str, object]]:
        raise AgentProvisionError("type d'agent inconnu : 'nope'")

    async def _record(login: str, ws_id: str, fp: str) -> None:
        return None

    monkeypatch.setattr(push, "_load_requested_agent_types", _load)
    monkeypatch.setattr(push, "_rotate_keys", _noop_rotate)
    monkeypatch.setattr(push, "_record_config_hash", _record)
    monkeypatch.setattr(push, "read_container_file", ch.read)
    monkeypatch.setattr(push, "write_container_file", ch.write)
    monkeypatch.setattr(push, "ws_exec", ch.ws_exec)

    with pytest.raises(AgentProvisionError):
        await _run(ch)


async def test_missing_external_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _Channel()
    _wire(monkeypatch, ch, [_row()])

    with pytest.raises(AgentProvisionError):
        await push_agent_files(
            login="bob",
            ws_id="bob-app",
            ws_name="app",
            agents=["claude"],
            mcp_url="/mcp/",
            project_root="/workspaces/bob-app",
            home="/home/vscode",
        )


async def _noop_rotate(login: str, ws_id: str) -> list[WorkspaceKey]:
    return []
