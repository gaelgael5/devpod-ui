"""Services Docker lances au demarrage d'une machine, portes par son profil.

Un profil ne fige pas seulement les parametres de creation et les recettes a
poser : il declare aussi ce qui doit tourner. On reference des TEMPLATES
COMPOSE existants — ceux que « Lancer un service » deploie deja a la main —
plutot qu'une liste d'images brutes : le template porte son compose, ses
parametres types et sa version.

Ajout CONDITIONNEL : la table vient d'etre creee par la 106, mais rien ne
garantit l'ordre d'application sur une base deja deployee.

Revision ID: 107
Revises: 106
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "107"
down_revision: str | None = "106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _colonnes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns("machine_profiles")}


def upgrade() -> None:
    if "services" not in _colonnes():
        op.add_column(
            "machine_profiles",
            # [{template_id, deployment_id, params}] — ORDONNE : un collecteur
            # peut devoir demarrer avant ce qu'il observe.
            sa.Column("services", JSONB(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    if "services" in _colonnes():
        op.drop_column("machine_profiles", "services")
