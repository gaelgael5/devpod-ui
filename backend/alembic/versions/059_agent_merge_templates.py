"""Spec 35b T8 — templates Codex/Gemini en fragment possédé (mode merge).

Les templates 057 rendaient le fichier COMPLET (mode replace) : mapper Codex ou
Gemini écrasait la config existante du workspace (modèle, sandbox, télémétrie…).
Le mode `merge` (058) exige un template en **fragment possédé** : un mini-document
dont la clé de tête (`mcp_servers` TOML, `mcpServers` JSON) ne porte QUE les
serveurs du portail, préfixés `portal-` — contrat vérifié par le cœur de merge
(`agents/merge.py`), qui upsert/purge les `portal-*` sans toucher au reste.

Codex/Gemini restent désactivés : réactivation en fin de chantier (T9), après
vérification bout-en-bout.

Revision ID: 059
Revises: 058
Create Date: 2026-07-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "059"
down_revision: str | None = "058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fragment TOML : uniquement les tables [mcp_servers.portal-*] du portail.
_CODEX_FRAGMENT = """\
{%- for s in servers %}
[mcp_servers.portal-{{ s.name }}]
url = {{ s.url | tojson }}
http_headers = { "Authorization" = {{ ("Bearer " ~ s.token) | tojson }} }
{% endfor -%}
"""

# Fragment JSON : clé de tête mcpServers, entrées préfixées portal-.
_GEMINI_FRAGMENT = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ ("portal-" ~ s.name) | tojson }}: {
      "httpUrl": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

# Templates 057 (rendu complet) — restaurés au downgrade.
_CODEX_057 = """\
{%- for s in servers %}
[mcp_servers.{{ s.name }}]
url = {{ s.url | tojson }}
http_headers = { "Authorization" = {{ ("Bearer " ~ s.token) | tojson }} }
{% endfor -%}
"""

_GEMINI_057 = """\
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


def _set_templates(codex: str, gemini: str) -> None:
    op.execute(
        sa.text("UPDATE agent_type SET template = :tpl WHERE id = 'codex'").bindparams(tpl=codex)
    )
    op.execute(
        sa.text("UPDATE agent_type SET template = :tpl WHERE id = 'gemini'").bindparams(tpl=gemini)
    )


def upgrade() -> None:
    _set_templates(_CODEX_FRAGMENT, _GEMINI_FRAGMENT)


def downgrade() -> None:
    _set_templates(_CODEX_057, _GEMINI_057)
