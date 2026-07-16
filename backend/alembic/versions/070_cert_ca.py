"""cert_ca : CA optionnel sur un certificat (bundle mTLS docker-tls).

Ajoute `ca_pem` (public, nullable) à `harpo_certificates` : une entrée `tls-*`
importée peut ainsi porter, en plus du cert client (`public_key`) et de la clé
privée, le certificat d'autorité (`ca.pem`) nécessaire au mTLS docker. Public
(un CA n'est pas un secret).

Revision ID: 070
Revises: 069
Create Date: 2026-07-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "070"
down_revision: str | None = "069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("harpo_certificates", sa.Column("ca_pem", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("harpo_certificates", "ca_pem")
