"""users.identity : identité portable propagée aux services MCP (on-behalf-of).

GUID éditable par l'utilisateur dans son profil. Sert d'acteur propagé (x-portal-actor)
quand il est renseigné ; sinon on retombe sur le sub OIDC (get_user_actor). Indispensable
pour les comptes LOCAUX (sans sub) : ils peuvent se donner un identifiant portable aligné
sur les services. UNIQUE (anti-collision / anti-usurpation), nullable (Postgres autorise
plusieurs NULL).

Revision ID: 078
Revises: 077
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "078"
down_revision: str | None = "077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("identity", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_users_identity", "users", ["identity"])


def downgrade() -> None:
    op.drop_constraint("uq_users_identity", "users", type_="unique")
    op.drop_column("users", "identity")
