"""Suivi REST des opérations asynchrones.

Elles n'étaient exposées que par MCP. Sans lecture REST, l'interface peut
lancer une recette de host mais jamais savoir si elle a abouti — un bouton qui
déclenche 20 Go d'installation sans retour n'est pas utilisable.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth.rbac import UserInfo, require_admin
from ..mcp.devpod_tools.operations import get_operation

router = APIRouter(tags=["operations"])


@router.get("/operations/{operation_id}")
async def read_operation(
    operation_id: str, user: UserInfo = Depends(require_admin)
) -> dict[str, Any]:
    """État d'une opération : `state`, `progress`, `result`, `error`.

    Restreinte à son propriétaire : l'identifiant est un UUID, mais on ne fait
    pas reposer le cloisonnement sur le fait qu'il soit difficile à deviner.
    """
    op = await get_operation(operation_id)
    if op is None or op.get("owner_login") != user.login:
        # Même réponse dans les deux cas : distinguer « inexistante » de « pas à
        # vous » renseignerait sur les opérations des autres.
        raise HTTPException(status_code=404, detail="Opération introuvable")
    return op
