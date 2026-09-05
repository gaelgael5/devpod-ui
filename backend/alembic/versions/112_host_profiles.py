"""Profils de host : ce qu'un forfait provisionne.

Trois niveaux, chacun avec sa responsabilite :

- le **type d'hyperviseur** declare les VARIABLES qui existent (label, slug,
  type) — il vit dans la configuration, pas ici ;
- le **profil de machine** fige les parametres du script de creation ;
- le **profil de host**, cette table, choisit un profil de machine et VALUE ces
  variables. Dont `capacity_workspaces` : le profil de machine sait construire
  la VM, il ne sait pas combien de workspaces elle tient sans planter. Seul
  l'exploitant le sait, et c'est ici qu'il le dit.

Pas de cle etrangere vers `machine_profiles` : l'existence est validee a
l'enregistrement, et une reference devenue pendante reste lisible — meme choix
que `hosts.profile_slug`.

Revision ID: 112
Revises: 111
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "112"
down_revision: str | None = "111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "host_profiles" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "host_profiles",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("machine_profile", sa.Text(), nullable=False),
        # {slug de variable: valeur}, en texte — la declaration porte le type.
        sa.Column("variables", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_host_profiles_machine", "host_profiles", ["machine_profile"])


def downgrade() -> None:
    if "host_profiles" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("host_profiles")
