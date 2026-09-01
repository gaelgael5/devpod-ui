"""La capacite d'accueil n'existe plus qu'a un endroit : la machine.

La migration 117 a deplace la capacite sur `hosts` et a explique pourquoi : une
machine mutualisee n'a pas de proprietaire, et un noeud enrole a la main n'a
aucun profil d'ou deriver sa capacite. Elle a laisse derriere elle la colonne
d'origine sur `host_ownership` — une copie sans lecteur, qui attendait que
quelqu'un la remplisse pour se mettre a diverger du fait.

Elle part. `host_ownership` decrit une PROPRIETE : qui possede la machine, et
sous quel forfait. `offer_max_workspaces` y reste, lui : c'est le quota du
forfait au moment du provisionnement, une donnee commerciale figee, qui n'a
aucune raison de vivre sur la machine.

`HostOwnership` (pydantic) garde son champ `capacity_workspaces` : c'est un objet
de calcul, pas une ligne de table, et son appelant l'alimentera depuis
`hosts.capacity_workspaces` — la ou le fait vit desormais.

Aucun code ne lisait ni n'ecrivait cette colonne au moment de la retirer.

Revision ID: 125
Revises: 124
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "125"
down_revision: str | None = "124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_ownership_capacity", "host_ownership", type_="check")
    op.drop_column("host_ownership", "capacity_workspaces")


def downgrade() -> None:
    # La colonne revient VIDE : la capacite vit sur `hosts` depuis la migration
    # 117, et la recopier ici recreerait exactement la divergence qu'on supprime.
    op.add_column(
        "host_ownership",
        sa.Column("capacity_workspaces", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_ownership_capacity",
        "host_ownership",
        "capacity_workspaces IS NULL OR capacity_workspaces >= 0",
    )
