"""Profils de machine : parametres figes + recettes a poser, sous un slug.

Remplace le jeu unique `test_host_params` porte par le type d'hyperviseur — un
seul modele de machine possible par type. Un profil est nomme, choisi a la
creation, et porte les recettes a installer avec leurs parametres.

`hypervisor_type` est obligatoire : les parametres n'ont de sens que contre la
spec du script de ce type. Un profil « 8 Go / cpu host » ne veut rien dire hors
de Proxmox.

`machine_type` distingue test et ressources. Seul `test` est exploite a la
creation pour l'instant : la creation de machines de ressources n'existe pas
encore cote application, on cree la machine puis on saisit sa connexion.

Revision ID: 106
Revises: 105
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "106"
down_revision: str | None = "105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "machine_profiles",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("machine_type", sa.Text(), nullable=False, server_default="test"),
        sa.Column("hypervisor_type", sa.Text(), nullable=False),
        # Args du script de creation, tels que declares par la spec du type.
        sa.Column("params", JSONB(), nullable=False, server_default="{}"),
        # [{key, options}] — ORDONNE : une dependance se pose avant celle qui
        # l'utilise. D'ou un tableau JSON plutot qu'une table de liaison, ou
        # l'ordre demanderait une colonne de rang.
        sa.Column("recipes", JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # La liste des profils d'un type est lue a chaque ouverture du menu de
    # creation ; le filtre porte toujours sur ces deux colonnes.
    op.create_index(
        "ix_machine_profiles_type",
        "machine_profiles",
        ["machine_type", "hypervisor_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_machine_profiles_type", table_name="machine_profiles")
    op.drop_table("machine_profiles")
