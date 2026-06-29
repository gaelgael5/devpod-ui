from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Jinja2Template(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    culture: str
    body: str
    updated_at: datetime | None = None


class WorkspaceMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    owner_login: str
    workspace_name: str
    type: str
    message: str
    created_at: datetime | None = None
