"""Connexion à l'instance Listmonk : où, et avec quelle clef.

Le motif est celui du producteur d'événements : `enabled`, une URL de base, et
un `apikey_secret` qui RÉFÉRENCE un secret système — la clef n'apparaît ni dans
la configuration, ni dans un journal, ni dans une sauvegarde.

« Tester la connexion » exerce un appel **authentifié** (`GET /api/lists`) :
un simple `GET /` répondrait 200 même avec une clef fausse — c'est le faux
positif déjà payé sur le producteur d'événements (bug 90cfaca8). Trois issues
distinctes : accepté, refusé par Listmonk (status + motif), injoignable.

Le schéma d'authentification (`Authorization: token api_user:token`) est celui
de la doc officielle courante — relevé le 05/09/2026, l'instance n'étant pas
encore déployée. À confirmer contre elle au premier déploiement.
"""

from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..config.models import ListmonkConfig
from ..config.store import load_global
from ..db.engine import get_conn
from ..db.global_config import save_global_db, set_cached_global
from ..secrets.system import reveal_system_secret

router = APIRouter(tags=["listmonk"])
log = structlog.get_logger(__name__)

_TIMEOUT_S = 10.0


@router.get("/listmonk")
async def lire_config(user: UserInfo = Depends(require_admin)) -> ListmonkConfig:
    return load_global().listmonk


@router.put("/listmonk")
async def ecrire_config(
    body: ListmonkConfig,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> ListmonkConfig:
    """Activer exige le contrat complet — fail closed, comme le producteur."""
    if body.enabled and (not body.url.strip() or not body.apikey_secret.strip()):
        raise HTTPException(
            status_code=422,
            detail="Activer Listmonk exige une URL et une clef d'API choisie.",
        )
    cfg = load_global()
    cfg.listmonk = body.model_copy(update={"url": body.url.strip().rstrip("/")})
    await save_global_db(cfg, conn)
    set_cached_global(cfg)
    log.info(
        "listmonk_config_updated",
        enabled=body.enabled,
        url=cfg.listmonk.url,
        apikey_secret=body.apikey_secret,  # le SLUG — jamais la valeur
        actor=user.login,
    )
    return cfg.listmonk


class ResultatTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    status_code: int | None = None
    #: Diagnostic du refus ou de l'échec réseau — c'est lui qui dit quoi réparer.
    motif: str = ""


@router.post("/listmonk/test-connection")
async def tester_connexion(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> ResultatTest:
    cfg = load_global().listmonk
    if not cfg.url.strip() or not cfg.apikey_secret.strip():
        raise HTTPException(
            status_code=409,
            detail="Renseignez l'URL et la clef d'API avant de tester.",
        )
    try:
        credential = await reveal_system_secret(cfg.apikey_secret, conn)
    except KeyError:
        # Le slug référencé ne résout plus : le dire ICI, pas au premier envoi.
        return ResultatTest(ok=False, motif=f"secret {cfg.apikey_secret!r} introuvable")

    url = f"{cfg.url.rstrip('/')}/api/lists"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                url,
                params={"per_page": "1"},
                headers={"Authorization": f"token {credential}"},
            )
    except httpx.HTTPError as exc:
        log.warning("listmonk_test_unreachable", url=cfg.url, error=type(exc).__name__)
        return ResultatTest(ok=False, motif=f"{type(exc).__name__}: instance injoignable")

    if resp.status_code == httpx.codes.OK:
        log.info("listmonk_test_ok", url=cfg.url, actor=user.login)
        return ResultatTest(ok=True, status_code=resp.status_code)
    # Refusé : le motif de Listmonk rend l'échec exploitable — « invalid API
    # credentials » dit quoi réparer, « HTTP 403 » ne dit rien.
    motif = ""
    try:
        corps = resp.json()
        if isinstance(corps, dict):
            motif = str(corps.get("message") or "")
    except ValueError:
        pass
    log.warning("listmonk_test_rejected", url=cfg.url, status=resp.status_code, motif=motif)
    return ResultatTest(ok=False, status_code=resp.status_code, motif=motif)


@router.post("/listmonk/sync-templates")
async def synchroniser_templates(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, int]:
    """Pousse les 12 templates versionnés (6 messages × fr/en) vers Listmonk.

    Action admin explicite, jamais au démarrage — même règle que la synchro des
    recettes. Idempotente : créé ou mis à jour, au nom près.
    """
    from ..emails.listmonk_tx import ListmonkIndisponible, ListmonkTxClient
    from ..emails.templates import TEMPLATES, nom_template

    cfg = load_global().listmonk
    if not cfg.enabled or not cfg.url.strip() or not cfg.apikey_secret.strip():
        raise HTTPException(
            status_code=409,
            detail="Activez et configurez la connexion Listmonk avant la synchro.",
        )
    try:
        credential = await reveal_system_secret(cfg.apikey_secret, conn)
    except KeyError:
        raise HTTPException(
            status_code=409, detail=f"secret {cfg.apikey_secret!r} introuvable"
        ) from None

    client = ListmonkTxClient(url=cfg.url, credential=credential)
    bilan = {"cree": 0, "mis_a_jour": 0}
    for (message, culture), template in sorted(TEMPLATES.items()):
        try:
            action = await client.synchroniser_template(
                nom=nom_template(message, culture),
                sujet=template.sujet,
                corps=template.corps,
            )
        except ListmonkIndisponible as exc:
            # L'échec au N-ième template dit lesquels sont passés : le bilan
            # partiel accompagne l'erreur.
            raise HTTPException(
                status_code=502, detail=f"{exc} — synchronisés avant l'échec : {bilan}"
            ) from exc
        bilan[action] += 1
    log.info("listmonk_templates_synchronises", **bilan, actor=user.login)
    return bilan
