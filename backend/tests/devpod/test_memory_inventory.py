"""Inventaire mémoire : ce qui sera ramené au plafond, sans jamais rien toucher.

Test de logique pure — les I/O (config globale, config user, statuts en base)
sont substituées : ce qui se prouve ici, c'est le classement (dépassement, vide
sur host plafonné, host sans plafond, conforme) et le drapeau « tourne encore
sur l'ancienne valeur ».
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from portal.devpod import memory_inventory


def _cfg_global(defaut: str, plafonds: dict[str, str]) -> SimpleNamespace:
    hosts = [SimpleNamespace(name=n, max_memory=m) for n, m in plafonds.items()]
    return SimpleNamespace(
        hosts=hosts,
        devpod=SimpleNamespace(defaults=SimpleNamespace(memory_limit=defaut)),
    )


def _brancher(
    monkeypatch: pytest.MonkeyPatch,
    *,
    defaut: str,
    plafonds: dict[str, str],
    specs_par_login: dict[str, list[SimpleNamespace]],
    rows: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(memory_inventory, "load_global", lambda: _cfg_global(defaut, plafonds))

    async def _load_user(login: str) -> SimpleNamespace:
        return SimpleNamespace(workspaces=specs_par_login.get(login, []))

    monkeypatch.setattr(memory_inventory, "load_user", _load_user)

    async def _list_all(_conn: Any) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(memory_inventory, "list_all_status_db", _list_all)

    class _Conn:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(memory_inventory, "_get_engine", lambda: SimpleNamespace(connect=_Conn))


def _spec(name: str, host: str, memory_limit: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, host=host, memory_limit=memory_limit)


async def test_classe_depassement_vide_et_ignore_conformes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _brancher(
        monkeypatch,
        defaut="900m",
        plafonds={"pve-a": "8g", "pve-b": ""},  # pve-b sans plafond
        specs_par_login={
            "alice": [
                _spec("web", "pve-a", "32g"),  # dépasse → borné à 8g
                _spec("api", "pve-a", "2g"),  # conforme → ignoré
            ],
            "bob": [_spec("big", "pve-b", "64g")],  # host sans plafond → ignoré
        },
        rows=[
            {"ws_id": "alice-web", "login": "alice", "host_name": "pve-a", "status": "running"},
            {"ws_id": "alice-api", "login": "alice", "host_name": "pve-a", "status": "running"},
            {"ws_id": "bob-big", "login": "bob", "host_name": "pve-b", "status": "running"},
        ],
    )

    inv = await memory_inventory.inventaire_memoire()

    assert len(inv) == 1
    (e,) = inv
    assert e == {
        "login": "alice",
        "workspace": "web",
        "host": "pve-a",
        "demande": "32g",
        "plafond": "8g",
        "applique": "8g",
        "en_cours": True,
    }


async def test_une_limite_vide_sur_host_plafonne_est_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le cas invisible d'un filtre naïf : défaut global vide → aucune limite."""
    _brancher(
        monkeypatch,
        defaut="",  # aucun défaut global : une spec vide vaut « illimité »
        plafonds={"pve-c": "3g"},
        specs_par_login={"carol": [_spec("void", "pve-c", "")]},
        rows=[
            {"ws_id": "carol-void", "login": "carol", "host_name": "pve-c", "status": "stopped"},
        ],
    )

    inv = await memory_inventory.inventaire_memoire()

    assert len(inv) == 1
    (e,) = inv
    assert e["demande"] == ""
    assert e["applique"] == "3g"
    assert e["en_cours"] is False  # arrêté → sera borné au prochain démarrage
