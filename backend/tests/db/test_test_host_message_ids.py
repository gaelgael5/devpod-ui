"""message_id des lignes proprietaires d'un host de test.

Rien en base n'empeche deux workspaces de posseder un host du meme nom — c'est
arrive : une suppression cote admin retirait le host de la config sans detacher
ses associations, et la machine suivante a porter ce nom en creait une seconde.
`scalar_one_or_none` levait alors `MultipleResultsFound` au beau milieu de la
suppression, le seul chemin qui aurait permis de nettoyer.
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import users, workspace_test_hosts
from portal.db.test_hosts import (
    assign_test_host,
    list_test_host_message_ids,
    remove_test_host,
    set_test_host_message_id,
)


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def _lien(
    conn: AsyncConnection,
    ws: str,
    host: str,
    *,
    message_id: int | None = None,
    shared_from: str | None = None,
) -> None:
    await conn.execute(
        insert(workspace_test_hosts).values(
            login="alice",
            workspace_name=ws,
            host_name=host,
            alias="test1",
            message_id=message_id,
            shared_from_workspace=shared_from,
        )
    )


async def test_aucun_lien_rend_une_liste_vide(db_conn: AsyncConnection) -> None:
    assert await list_test_host_message_ids("host-test-106-1", db_conn) == []


async def test_un_seul_proprietaire(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _lien(db_conn, "devpod", "host-test-106-1", message_id=42)

    assert await list_test_host_message_ids("host-test-106-1", db_conn) == [42]


async def test_deux_proprietaires_ne_font_plus_echouer(db_conn: AsyncConnection) -> None:
    """Le cas qui cassait la suppression : deux workspaces proprietaires du meme
    nom de host. Les deux messages doivent partir, pas une exception."""
    await _user(db_conn)
    await _lien(db_conn, "devpod", "host-test-106-1", message_id=42)
    await _lien(db_conn, "termix-mobile", "host-test-106-1", message_id=43)

    assert sorted(await list_test_host_message_ids("host-test-106-1", db_conn)) == [42, 43]


async def test_ignore_les_lignes_de_partage(db_conn: AsyncConnection) -> None:
    """Un partage n'est pas un proprietaire : son message appartient au workspace
    destinataire et se nettoie au retrait du partage."""
    await _user(db_conn)
    await _lien(db_conn, "devpod", "host-test-106-1", message_id=42)
    await _lien(db_conn, "autre-ws", "host-test-106-1", message_id=99, shared_from="devpod")

    assert await list_test_host_message_ids("host-test-106-1", db_conn) == [42]


async def test_ignore_les_lignes_sans_message(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _lien(db_conn, "devpod", "host-test-106-1", message_id=None)

    assert await list_test_host_message_ids("host-test-106-1", db_conn) == []


async def test_remove_test_host_emporte_toutes_les_lignes(db_conn: AsyncConnection) -> None:
    """C'est ce qui repare une base deja abimee : la suppression, une fois
    debloquee, efface les deux lignes d'un coup."""
    await _user(db_conn)
    await _lien(db_conn, "devpod", "host-test-106-1", message_id=42)
    await _lien(db_conn, "termix-mobile", "host-test-106-1", message_id=43)

    await remove_test_host("host-test-106-1", db_conn)

    assert await list_test_host_message_ids("host-test-106-1", db_conn) == []


async def test_le_chemin_nominal_reste_intact(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await assign_test_host("alice", "devpod", "host-test-107-1", "test1", db_conn)
    await set_test_host_message_id("host-test-107-1", 7, db_conn)

    assert await list_test_host_message_ids("host-test-107-1", db_conn) == [7]
