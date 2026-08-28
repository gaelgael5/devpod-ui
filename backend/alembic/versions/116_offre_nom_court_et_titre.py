"""Le nom court se separe du titre traduit.

`offers.labels` melangeait deux choses :

- le **nom du produit** — « Standard », « Max » — qui vit dans les tableaux
  d'administration, les badges et les journaux. Le traduire n'a pas de sens ;
- le **titre montre au client**, qui lui doit exister dans chaque langue.

D'ou deux colonnes : `label` (texte court, non traduit) et `titles` (JSONB
traduit), aux cotes de `descriptions` qui ne bouge pas.

Reprise : le nom court est pris dans l'anglais s'il existe, sinon le francais,
sinon le slug — jamais vide, c'est ce qui s'affiche partout. Les traductions
existantes deviennent les titres.

Revision ID: 116
Revises: 115
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "116"
down_revision: str | Sequence[str] | None = "115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("offers", sa.Column("label", sa.Text(), nullable=False, server_default=""))
    op.alter_column("offers", "labels", new_column_name="titles")
    op.execute(
        sa.text(
            """
            UPDATE offers
               SET label = COALESCE(
                   NULLIF(titles->>'en', ''),
                   NULLIF(titles->>'fr', ''),
                   slug
               )
            """
        )
    )


def downgrade() -> None:
    op.alter_column("offers", "titles", new_column_name="labels")
    op.drop_column("offers", "label")
