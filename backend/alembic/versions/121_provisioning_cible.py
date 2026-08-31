"""Le gabarit retenu par un provisioning, et le verdict « impossible ».

`billing.provisioning` savait dire QUOI faire — ouvrir une VM dediee, ouvrir un
host mutualise — mais pas AVEC QUOI : le noeud etait une constante (`pve`) et
rien ne disait quel gabarit monter. Il vient desormais de la chaine que
l'administrateur a construite :

    profil de host (de l'offre) -> profil de machine -> type -> hyperviseur

Les trois maillons sont recopies dans le registre, et pas seulement le dernier :
le jour ou l'on se demande pourquoi telle machine a ete montee ainsi, la reponse
doit se lire dans la trace plutot que se reconstituer depuis une configuration
qui a change depuis. NULL pour les actions qui ne montent rien — `rien` et
`assigner_host`, dont le gabarit a ete choisi le jour ou la machine d'accueil a
ete montee.

`impossible` est un verdict a part entiere : il fallait monter une machine et
aucun gabarit ne s'est resolu. Surtout pas `rien`, qui signifie « il n'y avait
rien a faire » — le client, lui, a paye. C'est exactement l'ecart que cette
table existe pour rendre listable.

Aucune reprise de donnees : les lignes existantes gardent leurs colonnes de
cible a NULL, ce qui est leur verite — elles ont ete decidees quand le noeud
etait une constante.

Revision ID: 121
Revises: 120
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "121"
down_revision: str | Sequence[str] | None = "120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ANCIENNE = (
    "action IN ('rien','assigner_host','creer_host_mutualise','creer_vm_dediee')"
)
_NOUVELLE = (
    "action IN ('rien','assigner_host','creer_host_mutualise',"
    "'creer_vm_dediee','impossible')"
)


def upgrade() -> None:
    for colonne in ("host_profile", "machine_profile", "hypervisor"):
        op.add_column("provisioning_runs", sa.Column(colonne, sa.Text(), nullable=True))
    op.drop_constraint("ck_provisioning_action", "provisioning_runs", type_="check")
    op.create_check_constraint("ck_provisioning_action", "provisioning_runs", _NOUVELLE)


def downgrade() -> None:
    # Les verdicts `impossible` ne rentrent pas dans l'ancienne contrainte : les
    # retirer AVANT de la reposer, sinon la migration inverse echoue sur des
    # donnees pourtant legitimes.
    op.execute("DELETE FROM provisioning_runs WHERE action = 'impossible'")
    op.drop_constraint("ck_provisioning_action", "provisioning_runs", type_="check")
    op.create_check_constraint("ck_provisioning_action", "provisioning_runs", _ANCIENNE)
    for colonne in ("hypervisor", "machine_profile", "host_profile"):
        op.drop_column("provisioning_runs", colonne)
