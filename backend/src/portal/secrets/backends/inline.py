from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

import yaml


class InlineBackend:
    """Lit les secrets depuis un fichier YAML local (user ou global)."""

    base_path: str

    def __init__(self, user_secrets_path: Path, base_path: str = "devpod") -> None:
        self._path = user_secrets_path
        self.base_path = base_path

    def get(self, full_path: str) -> str:
        with open(self._path, encoding="utf-8") as f:
            data = cast(dict[str, object], yaml.safe_load(f) or {})

        # Retirer le préfixe "base_path/"
        prefix = self.base_path + "/"
        rel = full_path[len(prefix) :] if full_path.startswith(prefix) else full_path

        # Retirer le segment UUID (namespace) s'il est en tête
        parts = rel.split("/")
        try:
            uuid.UUID(parts[0])
            parts = parts[1:]
        except (ValueError, IndexError):
            pass

        node: object = data
        for part in parts:
            if not isinstance(node, dict):
                raise KeyError(f"Path not traversable at {part!r} in {full_path!r}")
            if part not in node:
                raise KeyError(f"Key {part!r} not found in {full_path!r}")
            node = node[part]

        if not isinstance(node, str):
            raise KeyError(f"Value at {full_path!r} is not a string: {type(node)}")
        return node
