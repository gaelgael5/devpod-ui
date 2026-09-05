"""La capacite d'accueil et la provenance vivent sur la MACHINE.

Trois colonnes sur `hosts`, et une reponse a trois manques distincts :

- `profile_slug` etait deja declare sur `HostConfig`, documente comme la trace
  du profil ayant monte la machine — mais jamais persiste : les mappers le
  jetaient, la colonne n'existait pas. Le champ valait donc "" partout.
- `capacity_workspaces` etait recopie sur la ligne de PROPRIETE. Or une machine
  mutualisee n'a pas de proprietaire, et un noeud enrole a la main n'a aucun
  profil d'ou deriver sa capacite. La capacite est un fait de la machine : elle
  se range avec la machine. Le profil de host en fournit la valeur par defaut au
  provisionnement, il ne la gouverne pas — editer un profil ne redimensionne
  aucune VM deja montee.
- `accepts_mutualise` dit quelles machines le pool peut remplir. Faux par
  defaut : ouvrir un noeud aux workspaces d'autrui est un acte delibere, jamais
  un effet de bord d'une migration.

Revision ID: 117
Revises: 116
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "117"
down_revision: str | Sequence[str] | None = "116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("profile_slug", sa.Text(), nullable=False, server_default=""),
    )
    # NULL assume : « non renseigne » n'est ni zero (qui interdirait tout
    # workspace) ni l'infini (qui ferait planter la machine).
    op.add_column("hosts", sa.Column("capacity_workspaces", sa.Integer(), nullable=True))
    op.add_column(
        "hosts",
        sa.Column("accepts_mutualise", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_check_constraint(
        "ck_host_capacity",
        "hosts",
        "capacity_workspaces IS NULL OR capacity_workspaces >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_host_capacity", "hosts", type_="check")
    op.drop_column("hosts", "accepts_mutualise")
    op.drop_column("hosts", "capacity_workspaces")
    op.drop_column("hosts", "profile_slug")
