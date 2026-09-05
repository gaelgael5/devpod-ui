"""Oubli des déploiements d'un nœud détruit.

Une VM de test supprimée emporte ses conteneurs, mais ses lignes de déploiement
survivaient en base. Elles ressortaient telles quelles sur la machine suivante
qui portait le même nom : l'utilisateur y voyait des services « en cours
d'exécution » qui n'existaient plus — trois sur `host-test-106-1`, dont un seul
réel.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncConnection

from portal.compose import db
from portal.compose.models import ComposeDeployment, ComposeTemplate


async def _template(conn: AsyncConnection, tpl_id: str = "alloy-collector") -> None:
    await db.create_template(
        conn,
        ComposeTemplate(
            id=tpl_id,
            name=tpl_id,
            description="",
            tags=[],
            version="1",
            compose_content="services:\n  x:\n    image: busybox\n",
            parameters=[],
            source="builtin",
        ),
    )


async def _deploiement(
    conn: AsyncConnection, name: str, node_id: str, tpl_id: str = "alloy-collector"
) -> str:
    uid = str(uuid.uuid4())
    await db.create_deployment(
        conn,
        ComposeDeployment(
            uid=uid,
            id=name,
            template_id=tpl_id,
            template_version="1",
            node_id=node_id,
            owner_login="alice",
            status="running",
        ),
    )
    return uid


async def test_purge_supprime_les_lignes_du_noeud(db_conn: AsyncConnection) -> None:
    await _template(db_conn)
    await _deploiement(db_conn, "alloy-devpod", "host-test-106-1")
    await _deploiement(db_conn, "chromium", "host-test-106-1")

    assert await db.delete_deployments_for_node(db_conn, "host-test-106-1") == 2
    assert await db.list_deployments_for_node(db_conn, "host-test-106-1") == []


async def test_purge_ne_touche_pas_les_autres_noeuds(db_conn: AsyncConnection) -> None:
    """Les nœuds partagent des noms de déploiement : filtrer sur le seul nom
    emporterait les services d'une machine encore vivante."""
    await _template(db_conn)
    await _deploiement(db_conn, "alloy-collector", "host-test-106-1")
    garde = await _deploiement(db_conn, "alloy-collector", "host-test-107-1")

    await db.delete_deployments_for_node(db_conn, "host-test-106-1")

    restants = await db.list_deployments_for_node(db_conn, "host-test-107-1")
    assert [d.uid for d in restants] == [garde]


async def test_purge_d_un_noeud_sans_deploiement_ne_fait_rien(db_conn: AsyncConnection) -> None:
    assert await db.delete_deployments_for_node(db_conn, "host-test-999-9") == 0


async def test_le_nom_se_libere_pour_la_machine_suivante(db_conn: AsyncConnection) -> None:
    """Le garde-fou d'idempotence de l'auto-start cherche un déploiement par
    nom + nœud. Tant que la ligne fantôme reste, une machine recréee sous le
    même nom voit un service qu'elle n'héberge pas."""
    await _template(db_conn)
    await _deploiement(db_conn, "alloy-collector", "host-test-106-1")

    await db.delete_deployments_for_node(db_conn, "host-test-106-1")

    assert (
        await db.get_deployment_by_name_node(db_conn, "alloy-collector", "host-test-106-1")
    ) is None
