"""Spec 35 — types d'agents supplémentaires (Codex CLI, Gemini CLI, Cursor,
Cline, Devin Desktop).

Formats vérifiés par recherche documentaire dédiée (juillet 2026) :
- Codex CLI (~/.codex/config.toml) : table `[mcp_servers.<id>]`, clés `url` +
  `http_headers`. Ce fichier est le config **partagé** de Codex (modèle,
  sandbox, approval mode…), pas dédié au MCP comme .mcp.json — le mapping
  remplace tout le fichier et donc tout réglage Codex existant du workspace.
  Limite acceptée sciemment (même mécanisme que le seed Claude, migration 056).
- Gemini CLI (~/.gemini/settings.json) : `mcpServers.<id>.httpUrl` — **pas**
  `url`, qui route vers le transport SSE legacy côté client. Fichier également
  partagé (télémétrie, modèle…), même limite que Codex ci-dessus.
- Cursor (.cursor/mcp.json, racine du projet) : `mcpServers.<id>.url`, fichier
  dédié au MCP (comme .mcp.json de Claude) — pas de risque d'écrasement.
- Cline (~/.cline/data/settings/cline_mcp_settings.json) : `type` doit valoir
  `"streamableHttp"` explicitement (l'absence du champ retombe sur SSE
  legacy). Fichier dédié au MCP.
- Devin Desktop (~/.codeium/windsurf/mcp_config.json) : `mcpServers.<id>.serverUrl`,
  pas de champ `type`. Windsurf/Cascade a été rebrandé « Devin Desktop » et
  Cascade discontinué le 2026-07-01 ; le chemin de config est inchangé.
  Fichier dédié au MCP.

Revision ID: 057
Revises: 056
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "057"
down_revision: str | None = "056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODEX_TEMPLATE = """\
{%- for s in servers %}
[mcp_servers.{{ s.name }}]
url = {{ s.url | tojson }}
http_headers = { "Authorization" = {{ ("Bearer " ~ s.token) | tojson }} }
{% endfor -%}
"""

_GEMINI_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "httpUrl": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

_CURSOR_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "url": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

_CLINE_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "type": "streamableHttp",
      "url": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}},
      "disabled": false
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

_DEVIN_DESKTOP_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "serverUrl": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

_NEW_AGENT_TYPES = [
    {
        "id": "codex",
        "label": "Codex CLI",
        "filename": "config.toml",
        "template": _CODEX_TEMPLATE,
        "target_path": "{{ home }}/.codex/config.toml",
    },
    {
        "id": "gemini",
        "label": "Gemini CLI",
        "filename": "settings.json",
        "template": _GEMINI_TEMPLATE,
        "target_path": "{{ home }}/.gemini/settings.json",
    },
    {
        "id": "cursor",
        "label": "Cursor",
        "filename": "mcp.json",
        "template": _CURSOR_TEMPLATE,
        "target_path": "{{ project_root }}/.cursor/mcp.json",
    },
    {
        "id": "cline",
        "label": "Cline",
        "filename": "cline_mcp_settings.json",
        "template": _CLINE_TEMPLATE,
        "target_path": "{{ home }}/.cline/data/settings/cline_mcp_settings.json",
    },
    {
        "id": "devin-desktop",
        "label": "Devin Desktop (Windsurf)",
        "filename": "mcp_config.json",
        "template": _DEVIN_DESKTOP_TEMPLATE,
        "target_path": "{{ home }}/.codeium/windsurf/mcp_config.json",
    },
]


def upgrade() -> None:
    agent_type = sa.table(
        "agent_type",
        sa.column("id", sa.Text),
        sa.column("label", sa.Text),
        sa.column("filename", sa.Text),
        sa.column("template", sa.Text),
        sa.column("target_path", sa.Text),
    )
    op.bulk_insert(agent_type, _NEW_AGENT_TYPES)


def downgrade() -> None:
    ids = [a["id"] for a in _NEW_AGENT_TYPES]
    op.execute(
        sa.text("DELETE FROM agent_type WHERE id = ANY(:ids)").bindparams(
            sa.bindparam("ids", value=ids, type_=sa.ARRAY(sa.Text()))
        )
    )
