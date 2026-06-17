from __future__ import annotations

from pathlib import Path

# Répertoire des recettes intégrées livrées avec l'image du portail.
# Les recettes admin dans /data/recipes/ écrasent les builtins à id égal (priorité shared > builtin).
BUILTIN_RECIPES_DIR: Path = Path(__file__).parent.parent / "builtin_recipes"
