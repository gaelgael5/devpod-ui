"""Recalcule mcp_tool_catalog.definition_hash avec la canonicalisation des tableaux-ensembles.

hash_definition trie désormais les tableaux `required`/`enum`/`type` (ordre non
significatif) avant de hasher, pour qu'un serveur qui les renvoie dans un ordre
instable ne re-quarantine pas un outil inchangé (spec 23). Sans cette migration, le
premier resync après déploiement verrait TOUS les hash diverger de l'existant et
quarantinerait tout une fois. On recalcule donc les hash stockés depuis la définition
déjà en base — la quarantaine (`quarantined`) n'est PAS touchée.

Revision ID: 076
Revises: 075
Create Date: 2026-07-20
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "076"
down_revision: str | None = "075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copie autonome de la logique de portal.mcp.client (une migration ne doit pas
# dépendre du code applicatif, qui peut évoluer indépendamment).
_SET_ARRAY_KEYS = frozenset({"required", "enum", "type"})


def _canonicalize(node: Any, parent_key: str | None = None) -> Any:
    if isinstance(node, dict):
        return {k: _canonicalize(v, k) for k, v in node.items()}
    if isinstance(node, list):
        items = [_canonicalize(v) for v in node]
        if parent_key in _SET_ARRAY_KEYS:
            return sorted(items, key=lambda e: json.dumps(e, sort_keys=True, ensure_ascii=False))
        return items
    return node


def _hash_definition(definition: dict[str, Any]) -> str:
    canonical = json.dumps(
        _canonicalize(definition), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT backend_id, kind, original_name, definition FROM mcp_tool_catalog")
    ).fetchall()
    for backend_id, kind, original_name, definition in rows:
        # definition est stocké en JSONB → asyncpg/psycopg le rend déjà en dict.
        new_hash = _hash_definition(
            definition if isinstance(definition, dict) else json.loads(definition)
        )
        conn.execute(
            sa.text(
                "UPDATE mcp_tool_catalog SET definition_hash = :h "
                "WHERE backend_id = :b AND kind = :k AND original_name = :n"
            ),
            {"h": new_hash, "b": backend_id, "k": kind, "n": original_name},
        )


def downgrade() -> None:
    # Recalcul de hash : pas de downgrade utile (l'ancienne canonicalisation est
    # dérivable mais sans intérêt — la colonne se resynchronise seule au prochain probe).
    pass
