"""Préférences UI par utilisateur — `GET /me/preferences` et `PUT /me/preferences/{key}`.

API générique clé/valeur : le client charge la map complète à l'ouverture d'une
page et écrit chaque réglage individuellement. La valeur est **typée et
discriminée** dans le corps du PUT (`{"bool": true}` / `{"int": 5}` /
`{"string": "x"}`) — exactement un champ renseigné.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db.engine import get_conn
from ..db.user_config import ensure_user_db
from ..db.user_preferences import PrefValue, list_preferences, upsert_preference

router = APIRouter(tags=["preferences"])

# Clé fonctionnelle : composée et namespacée par l'appelant (ex.
# `workspaces.group.3.collapse`). Charset volontairement restreint (anti-abus).
_PREF_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class PreferenceValueBody(BaseModel):
    """Valeur typée discriminée : exactement un de `int` / `string` / `bool`."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    int_: int | None = Field(default=None, alias="int")
    string: str | None = None
    bool_: bool | None = Field(default=None, alias="bool")

    @model_validator(mode="after")
    def _exactly_one(self) -> PreferenceValueBody:
        provided = [v for v in (self.int_, self.string, self.bool_) if v is not None]
        if len(provided) != 1:
            raise ValueError("exactly one of int/string/bool must be set")
        return self

    def value(self) -> PrefValue:
        if self.bool_ is not None:
            return self.bool_
        if self.int_ is not None:
            return self.int_
        assert self.string is not None  # garanti par _exactly_one
        return self.string


@router.get("/preferences")
async def get_preferences(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    return await list_preferences(user.login, conn)


@router.put("/preferences/{key}", status_code=204)
async def put_preference(
    key: str,
    body: PreferenceValueBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not _PREF_KEY_RE.fullmatch(key):
        raise HTTPException(status_code=422, detail=f"Invalid preference key {key!r}")
    # Garde-FK : garantit la ligne users avant l'upsert (idempotent).
    await ensure_user_db(user.login, conn)
    await upsert_preference(user.login, key, body.value(), conn)
