from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from portal.compose import compose_bootstrap as boot
from portal.compose.models import ComposeTemplate


def _stale_row(version: str) -> ComposeTemplate:
    """Ligne DB existante — extra_files vide, comme avant l'ajout du champ."""
    return ComposeTemplate(
        id="alloy-collector",
        name="Collecteur de logs (Alloy)",
        version=version,
        compose_content="services:\n  alloy:\n    image: old\n",
        source="builtin",
        extra_files={},
    )


@pytest.mark.asyncio
async def test_upsert_creates_template_when_missing(monkeypatch) -> None:
    """Aucune ligne existante → create_template avec le contenu courant."""
    monkeypatch.setattr(boot.cdb, "get_template", AsyncMock(return_value=None))
    create = AsyncMock()
    monkeypatch.setattr(boot.cdb, "create_template", create)
    update = AsyncMock()
    monkeypatch.setattr(boot.cdb, "update_template", update)

    await boot._upsert_alloy_collector(conn=object())  # conn non utilisé (db mockée)

    create.assert_awaited_once()
    update.assert_not_awaited()
    created_tpl = create.await_args.args[1]
    assert created_tpl.extra_files == {"config.alloy": boot._ALLOY_CONFIG}


@pytest.mark.asyncio
async def test_upsert_resyncs_stale_row_with_older_version(monkeypatch) -> None:
    """Ligne existante avec une version antérieure (ex. extra_files vide, bug
    corrigé) → update_template réécrit tout le contenu, extra_files inclus.

    Régression : c'est ce mécanisme qui, faute de bump de _ALLOY_VERSION lors
    de l'ajout d'extra_files, laissait des déploiements sans config.alloy sur
    disque → échec docker compose up (mount "not a directory").
    """
    monkeypatch.setattr(
        boot.cdb, "get_template", AsyncMock(return_value=_stale_row("older-version"))
    )
    create = AsyncMock()
    monkeypatch.setattr(boot.cdb, "create_template", create)
    update = AsyncMock()
    monkeypatch.setattr(boot.cdb, "update_template", update)

    await boot._upsert_alloy_collector(conn=object())

    update.assert_awaited_once()
    create.assert_not_awaited()
    updated_tpl = update.await_args.args[1]
    assert updated_tpl.extra_files == {"config.alloy": boot._ALLOY_CONFIG}
    assert updated_tpl.version == boot._ALLOY_VERSION


@pytest.mark.asyncio
async def test_upsert_noop_when_version_unchanged(monkeypatch) -> None:
    """Ligne existante déjà à jour (même version) → aucune écriture (idempotent)."""
    monkeypatch.setattr(
        boot.cdb, "get_template", AsyncMock(return_value=_stale_row(boot._ALLOY_VERSION))
    )
    create = AsyncMock()
    monkeypatch.setattr(boot.cdb, "create_template", create)
    update = AsyncMock()
    monkeypatch.setattr(boot.cdb, "update_template", update)

    await boot._upsert_alloy_collector(conn=object())

    create.assert_not_awaited()
    update.assert_not_awaited()
