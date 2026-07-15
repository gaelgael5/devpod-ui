"""Partage d'une VM de test vers d'autres workspaces — couche db.

Distinction propriétaire (shared_from NULL) / partage (shared_from = ws d'origine),
et les gardes de cycle de vie associées.
"""
from __future__ import annotations

import pytest

from portal.db.test_hosts import (
    assign_test_host,
    count_owned_test_hosts,
    host_full_info,
    is_owned_test_host,
    list_shared_targets,
    list_test_hosts_with_share,
    remove_test_host,
    set_shared_message_id,
    share_test_host,
    unshare_test_host,
    workspace_for_host,
)

pytestmark = pytest.mark.asyncio

LOGIN, OWNER_WS, TARGET_WS, HOST = "alice", "owner-ws", "other-ws", "host-test-120-1"


async def _seed_owner(conn) -> None:
    await assign_test_host(LOGIN, OWNER_WS, HOST, "test1", conn)


async def test_owner_row_vs_shared_row(db_conn) -> None:
    await _seed_owner(db_conn)
    await share_test_host(LOGIN, OWNER_WS, HOST, TARGET_WS, "test1", db_conn)

    # Propriétaire = ligne shared_from NULL ; le partage ne l'est pas.
    assert await is_owned_test_host(LOGIN, OWNER_WS, HOST, db_conn) is True
    assert await is_owned_test_host(LOGIN, TARGET_WS, HOST, db_conn) is False

    # Les fonctions « propriétaire » ignorent la ligne de partage.
    assert await workspace_for_host(HOST, db_conn) == (LOGIN, OWNER_WS)
    assert await host_full_info(HOST, db_conn) == (LOGIN, OWNER_WS, "test1")


async def test_count_owned_excludes_shared(db_conn) -> None:
    await _seed_owner(db_conn)
    # Une VM partagée-VERS owner-ws depuis un autre workspace ne compte pas.
    await share_test_host(LOGIN, "src-ws", "host-test-120-2", OWNER_WS, "test2", db_conn)
    assert await count_owned_test_hosts(LOGIN, OWNER_WS, db_conn) == 1


async def test_list_with_share_marks_shared_rows(db_conn) -> None:
    await _seed_owner(db_conn)
    await share_test_host(LOGIN, OWNER_WS, HOST, TARGET_WS, "test1", db_conn)

    owner_rows = await list_test_hosts_with_share(LOGIN, OWNER_WS, db_conn)
    assert owner_rows == [(HOST, "test1", None)]  # shared_from None = possédé

    target_rows = await list_test_hosts_with_share(LOGIN, TARGET_WS, db_conn)
    assert target_rows == [(HOST, "test1", OWNER_WS)]  # marqué partagé-depuis owner


async def test_share_unshare_roundtrip(db_conn) -> None:
    await _seed_owner(db_conn)
    await share_test_host(LOGIN, OWNER_WS, HOST, TARGET_WS, "test3", db_conn)
    await set_shared_message_id(LOGIN, HOST, TARGET_WS, 4242, db_conn)

    targets = await list_shared_targets(LOGIN, HOST, db_conn)
    assert targets == [(TARGET_WS, "test3", 4242)]

    # unshare retourne (alias, message_id) pour le nettoyage, puis supprime la ligne.
    assert await unshare_test_host(LOGIN, HOST, TARGET_WS, db_conn) == ("test3", 4242)
    assert await list_shared_targets(LOGIN, HOST, db_conn) == []
    # La ligne propriétaire survit au dé-partage.
    assert await is_owned_test_host(LOGIN, OWNER_WS, HOST, db_conn) is True


async def test_unshare_never_touches_owner(db_conn) -> None:
    await _seed_owner(db_conn)
    # Pas de partage → rien à retirer, et la ligne propriétaire reste intacte.
    assert await unshare_test_host(LOGIN, HOST, OWNER_WS, db_conn) is None
    assert await is_owned_test_host(LOGIN, OWNER_WS, HOST, db_conn) is True


async def test_remove_host_drops_owner_and_shares(db_conn) -> None:
    await _seed_owner(db_conn)
    await share_test_host(LOGIN, OWNER_WS, HOST, TARGET_WS, "test1", db_conn)
    await remove_test_host(HOST, db_conn)
    assert await list_test_hosts_with_share(LOGIN, OWNER_WS, db_conn) == []
    assert await list_test_hosts_with_share(LOGIN, TARGET_WS, db_conn) == []
