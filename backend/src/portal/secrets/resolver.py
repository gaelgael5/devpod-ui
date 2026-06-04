from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from .backends.base import SecretsBackend
from .types import Secret

_SECRET_REF_RE = re.compile(r"^\$\{(vault|env)://(.+)\}$")


class SecretAccessError(Exception):
    pass


@dataclass
class Scope:
    kind: Literal["user", "global"]
    secret_ns: str = ""
    login: str = ""


def resolve(value: str, scope: Scope, backend: SecretsBackend) -> str | Secret:
    m = _SECRET_REF_RE.fullmatch(value)
    if not m:
        return value

    kind, path = m.group(1), m.group(2)

    if kind == "env":
        env_val = os.environ.get(path)
        if env_val is None:
            raise SecretAccessError(f"Environment variable not found: {path!r}")
        return Secret(env_val)

    # vault://
    if scope.kind == "user":
        _validate_user_vault_path(path, scope.secret_ns)
        full_path = f"{backend.base_path}/{scope.secret_ns}/{path}"
    else:
        full_path = path

    return Secret(backend.get(full_path))


def _validate_user_vault_path(path: str, secret_ns: str) -> None:
    if path.startswith("/"):
        raise SecretAccessError(
            f"User vault path must not be absolute (starts with '/'): {path!r}"
        )
    parts = path.split("/")
    if ".." in parts:
        raise SecretAccessError(
            f"User vault path must not contain '..' traversal: {path!r}"
        )
    for part in parts:
        try:
            parsed_uuid = uuid.UUID(part)
            if str(parsed_uuid) != secret_ns:
                raise SecretAccessError(
                    f"User vault path contains foreign namespace UUID: {part!r}"
                )
        except ValueError:
            pass  # pas un UUID — segment normal
