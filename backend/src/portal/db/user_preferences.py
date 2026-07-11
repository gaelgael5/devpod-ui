"""Persistance des préférences UI par utilisateur (table `user_preferences`).

Modèle générique : une ligne = (login, pref_key) → une valeur rangée dans la
colonne du type indiqué par `value_type` ('int' | 'string' | 'bool'). Le type
est explicite pour lever toute ambiguïté de lecture (int 0 vs bool false vs
absent). Upsert idempotent sur la contrainte unique (login, pref_key).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import user_preferences

# Types de valeur supportés (bool AVANT int : bool est sous-type d'int en Python).
PrefValue = bool | int | str


def _split(value: PrefValue) -> tuple[str, dict[str, Any]]:
    """(value_type, colonnes) — range la valeur dans la bonne colonne, nullifie les autres."""
    if isinstance(value, bool):
        return "bool", {"value_bool": value, "value_int": None, "value_text": None}
    if isinstance(value, int):
        return "int", {"value_int": value, "value_bool": None, "value_text": None}
    return "string", {"value_text": value, "value_int": None, "value_bool": None}


def _decode(row: dict[str, Any]) -> PrefValue:
    """Reconstruit la valeur typée depuis `value_type` et la colonne correspondante."""
    vt = row["value_type"]
    if vt == "bool":
        return bool(row["value_bool"])
    if vt == "int":
        return int(row["value_int"])
    return str(row["value_text"])


async def list_preferences(login: str, conn: AsyncConnection) -> dict[str, PrefValue]:
    """Map `pref_key → valeur typée` de toutes les préférences de l'utilisateur."""
    rows = (
        (await conn.execute(select(user_preferences).where(user_preferences.c.login == login)))
        .mappings()
        .all()
    )
    return {r["pref_key"]: _decode(dict(r)) for r in rows}


async def upsert_preference(
    login: str, pref_key: str, value: PrefValue, conn: AsyncConnection
) -> None:
    """Écrit (ou remplace) une préférence. Idempotent sur (login, pref_key)."""
    value_type, cols = _split(value)
    vals: dict[str, Any] = {
        "login": login,
        "pref_key": pref_key,
        "value_type": value_type,
        **cols,
    }
    set_vals: dict[str, Any] = {"value_type": value_type, **cols, "updated_at": func.now()}
    await conn.execute(
        pg_insert(user_preferences)
        .values(**vals)
        .on_conflict_do_update(
            index_elements=[user_preferences.c.login, user_preferences.c.pref_key],
            set_=set_vals,
        )
    )
