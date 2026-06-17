from __future__ import annotations

from sqlalchemy import MetaData

# Point d'entrée unique pour la MetaData.
# Les tables sont ajoutées au fur et à mesure de la migration (un tour par table).
# Alembic importe ce module pour détecter les changements de schéma.
metadata = MetaData()
