"""Quel hyperviseur a monte cette machine.

Le seul lien disponible etait `hosts.proxmox_node` rapproche de
`hypervisors.pve_node` : un NOM compare a un NOM. `hypervisors.name` est unique,
`pve_node` ne l'est pas, et son defaut vaut `pve` — le nom d'hote par defaut
d'une installation Proxmox. Deux serveurs autonomes installes par defaut portent
donc le meme nom de noeud, et chacun se voit attribuer les machines de l'autre
sans que rien ne le signale.

L'information existe pourtant au moment ou la machine est montee : `Cible` porte
l'hyperviseur retenu et `provisioning_runs` en garde la trace. Elle etait
simplement jetee.

Meme semantique que `profile_slug` juste a cote : PROVENANCE, PAS CONTRAINTE.
Donc aucune cle etrangere vers `hypervisors.name` — supprimer ou renommer un
hyperviseur ne doit ni effacer des machines ni bloquer l'operation. La provenance
est un fait passe, elle ne se revise pas.

Vide = provenance inconnue : machine enrolee a la main, ou montee avant cette
colonne. Ni une erreur, ni un hyperviseur par defaut.

RETRO-REMPLISSAGE : uniquement depuis `provisioning_runs`, ou le lien est ECRIT.
On ne devine PAS depuis `proxmox_node`, meme quand un seul hyperviseur declare le
noeud : ce raisonnement est exactement l'ambiguite que cette colonne existe pour
supprimer, et un lien faux est pire qu'un lien absent. Le nombre de lignes
laissees vides est journalise.

Revision ID: 124
Revises: 123
Create Date: 2026-09-01
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "124"
down_revision: str | None = "123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("hypervisor", sa.Text(), nullable=False, server_default=""),
    )

    conn = op.get_bind()
    # Un provisioning peut avoir ete rejoue : on retient le plus recent qui a
    # abouti et qui nomme un hyperviseur.
    conn.execute(
        sa.text(
            """
            UPDATE hosts h
               SET hypervisor = r.hypervisor
              FROM (
                    SELECT DISTINCT ON (host_name) host_name, hypervisor
                      FROM provisioning_runs
                     WHERE host_name IS NOT NULL
                       AND hypervisor IS NOT NULL
                       AND hypervisor <> ''
                  ORDER BY host_name, created_at DESC
                   ) r
             WHERE h.name = r.host_name
            """
        )
    )
    restantes = conn.execute(
        sa.text("SELECT count(*) FROM hosts WHERE hypervisor = ''")
    ).scalar_one()
    _log.info(
        "migration 124 : %s machine(s) sans provenance d'hyperviseur — "
        "enrolees a la main ou montees avant cette colonne, laissees vides a dessein",
        restantes,
    )


def downgrade() -> None:
    op.drop_column("hosts", "hypervisor")
