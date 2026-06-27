"""Erreur métier des primitives devpod (isolée pour éviter les cycles d'import)."""
from __future__ import annotations


class DevpodToolError(Exception):
    """Erreur métier d'une primitive devpod → renvoyée en isError (jamais un 500)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
