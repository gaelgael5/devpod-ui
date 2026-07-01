"""Génération du .env d'un déploiement : résolution secrets en mémoire (spec 26 §6)."""

from __future__ import annotations

from ..config.store import load_global, safe_user_path
from ..secrets.factory import create_backend
from ..secrets.resolver import Scope, resolve
from ..secrets.types import Secret


def _resolve_one(login: str, secret_ns: str, value: str) -> str:
    """Résout une valeur (référence vault/env ou littéral) en mémoire."""
    global_cfg = load_global()
    backend = create_backend(
        backend_type=global_cfg.secrets.backend,
        url=global_cfg.secrets.harpocrate.url,
        api_key=global_cfg.secrets.harpocrate.api_key,
        base_path=global_cfg.secrets.harpocrate.base_path,
        user_secrets_path=safe_user_path(login, "secrets.yaml"),
    )
    scope = Scope(kind="user", secret_ns=secret_ns, login=login)
    resolved = resolve(value, scope, backend)
    return resolved.reveal() if isinstance(resolved, Secret) else str(resolved)


def resolve_env_values(login: str, secret_ns: str, env_values: dict[str, str]) -> dict[str, str]:
    return {k: _resolve_one(login, secret_ns, v) for k, v in env_values.items()}


def _quote(value: str) -> str:
    """Échappe une valeur .env pour éviter l'injection de lignes (spec 26 T7)."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def render_env_file(
    resolved: dict[str, str],
    context_vars: dict[str, str] | None = None,
) -> str:
    """Rend un dictionnaire de valeurs résolvues en contenu .env.

    Les context_vars (injectées par le portail, non saisies par l'user) sont
    ajoutées après les valeurs user et prennent la priorité en cas de doublon.
    """
    merged = {**resolved, **(context_vars or {})}
    return "".join(f"{k}={_quote(v)}\n" for k, v in merged.items())
