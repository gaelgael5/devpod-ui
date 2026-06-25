"""Décision du fallback SPA (utilisée par SPAMiddleware).

Isolé dans son propre module : pur, sans dépendance lourde → testable hors runtime.
"""
from __future__ import annotations

# Routes BACKEND atteintes par navigation navigateur (GET + text/html) : redirections
# d'auth qui ne doivent jamais être masquées par l'index.html du SPA, sinon React Router
# se retrouve sur une URL inconnue (/auth/logout → 404) et l'échange OIDC (/auth/callback)
# n'a jamais lieu. `/auth/login` reste une route FRONTEND (page de connexion).
_BACKEND_NAV_PATHS: tuple[str, ...] = (
    "/auth/logout",
    "/auth/oidc",
    "/auth/callback",
)


def should_serve_spa(method: str, path: str, accept: str) -> bool:
    """True si la requête est une navigation navigateur vers une route FRONTEND.

    Critères : GET, Accept inclut text/html (et pas application/json), chemin sans
    extension (pas un asset), et qui n'est pas une route backend navigable.
    """
    if method != "GET":
        return False
    if "text/html" not in accept or "application/json" in accept:
        return False
    if "." in path.rsplit("/", 1)[-1]:  # asset (extension dans le dernier segment)
        return False
    return not path.startswith(_BACKEND_NAV_PATHS)
