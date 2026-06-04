from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretsBackend(Protocol):
    base_path: str

    def get(self, full_path: str) -> str: ...
