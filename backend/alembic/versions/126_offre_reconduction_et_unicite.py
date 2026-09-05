"""Ce qu'il advient d'un forfait a son terme, et combien de fois on peut le prendre.

Tout forfait est BORNE — `duration_days` l'exige deja. Restaient deux questions
qu'aucune colonne ne portait, et que la page d'engagement doit pourtant savoir
repondre avant qu'un client s'engage :

- **`tacite_reconduction`** : au terme, le forfait repart-il, ou s'arrete-t-il ?
  Defaut FAUX. Reconduire par defaut prelegerait quelqu'un qui n'a rien demande,
  et un defaut qui coute de l'argent au client n'est pas un defaut acceptable.

- **`une_par_compte`** : ce forfait peut-il etre repris par le meme compte ?
  Defaut FAUX, c'est-a-dire repetable — prendre deux fois le meme forfait payant
  est legitime, et rien ne justifie de l'interdire.

`une_par_compte` remplace la regle qu'on s'appretait a coder en dur pour l'offre
de bienvenue. Un PARAMETRE plutot qu'une exception sur `is_free` : c'est une
decision commerciale, elle appartient a celui qui redige l'offre, et le jour ou
un forfait payant doit lui aussi etre unique, rien n'est a reecrire.

Les deux defauts a faux laissent le catalogue existant strictement inchange.

Revision ID: 126
Revises: 125
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "126"
down_revision: str | None = "125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offers",
        sa.Column("tacite_reconduction", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "offers",
        sa.Column("une_par_compte", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("offers", "une_par_compte")
    op.drop_column("offers", "tacite_reconduction")
