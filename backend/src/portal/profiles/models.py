from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["shared", "user"]


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, pattern=r"^[\w\s\-+.]{1,80}$")
    description: str = ""
    extensions: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class Profile(ProfileBody):
    slug: str
    scope: Scope

    def to_customizations(self) -> dict[str, Any]:
        return {"vscode": {"extensions": self.extensions, "settings": self.settings}}


class ProfileSummary(BaseModel):
    slug: str
    scope: Scope
    name: str
    description: str
    extension_count: int
    editable: bool
