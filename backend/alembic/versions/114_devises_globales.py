"""Les devises acceptees deviennent globales, elles ne pendent plus d'un pays.

`country_currencies` liait chaque devise a un pays. Ce lien s'est revele faux :
ce que la plateforme sait ENCAISSER ne depend pas de l'endroit ou vit
l'acheteur. Deux pays de la zone euro n'ont pas chacun « leur » euro, et un
acheteur peut vouloir payer en dollars depuis la France.

La nouvelle table dit ce qu'elle modelise : les devises que l'application
accepte. L'index partiel garantit qu'exactement une porte le defaut — deux
rendraient indetermine le choix au moment de presenter un prix.

Les codes deja declares, quel que soit leur pays, sont repris ; le defaut
global est celui qui l'etait le plus souvent. Le referentiel du garde-fou a la
publication (`devises_actives`) suit ce changement sans que les offres bougent.

Revision ID: 114
Revises: 113
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "114"
down_revision: str | Sequence[str] | None = "113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "currencies",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_currency_default",
        "currencies",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "country_currencies" in tables:
        # Reprise : un code par devise rencontree, et le defaut global est celui
        # qui etait defaut dans le plus de pays. A egalite, l'ordre alphabetique
        # tranche — un tirage instable rendrait la migration non reproductible.
        op.execute(
            sa.text(
                """
                INSERT INTO currencies (code, enabled, is_default)
                SELECT cc.currency,
                       TRUE,
                       cc.currency = (
                           SELECT currency FROM country_currencies
                           GROUP BY currency
                           ORDER BY COUNT(*) FILTER (WHERE is_default) DESC, currency
                           LIMIT 1
                       )
                FROM country_currencies cc
                GROUP BY cc.currency
                """
            )
        )
        op.drop_table("country_currencies")


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "country_currencies" not in tables:
        op.create_table(
            "country_currencies",
            sa.Column(
                "country_code",
                sa.Text(),
                sa.ForeignKey("countries.code", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("currency", sa.Text(), primary_key=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        )
    if "currencies" in tables:
        op.drop_table("currencies")
