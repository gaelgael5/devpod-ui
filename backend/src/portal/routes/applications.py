"""Kiosque d'applications — `GET/POST /me/applications`, `DELETE /me/applications/{id}`,
`GET /me/applications/favicon`.

Liens personnels (icône + nom + URL) affichés sur la page Applications. L'URL
est restreinte à http(s) — un lien `javascript:` stocké puis rendu dans un
<a href> serait un XSS stocké. L'icône est un emoji/texte court ou une URL
d'image https (même restriction de schéma).

Le probe favicon fetche une URL fournie par l'utilisateur : chaque requête (et
chaque saut de redirection) passe par le module anti-SSRF `_ssrf` (validation
d'IP + GET épinglé anti-rebinding), et les corps sont lus bornés.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db.engine import get_conn
from ..db.user_applications import add_application, delete_application, list_applications
from ..db.user_config import ensure_user_db
from ._ssrf import pinned_get

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["applications"])

_ALLOWED_SCHEMES = ("http://", "https://")


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    icon: str = ""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 60:
            raise ValueError("name must be 1-60 characters")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 2000 or not v.lower().startswith(_ALLOWED_SCHEMES):
            raise ValueError("url must start with http:// or https:// (max 2000 chars)")
        return v

    @field_validator("icon")
    @classmethod
    def _icon(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 300:
            raise ValueError("icon must be ≤ 300 characters")
        # Une icône « URL » doit être http(s) ; sinon c'est un emoji/texte court.
        if "://" in v and not v.lower().startswith(_ALLOWED_SCHEMES):
            raise ValueError("icon url must start with http:// or https://")
        return v


@router.get("/applications")
async def get_applications(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await list_applications(user.login, conn)


@router.post("/applications", status_code=201)
async def post_application(
    body: ApplicationCreate,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    # Garde-FK : garantit la ligne users avant l'insert (idempotent).
    await ensure_user_db(user.login, conn)
    try:
        row = await add_application(user.login, body.name, body.url, body.icon, conn)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail=f"application {body.name!r} already exists"
        ) from exc
    _log.info("application_added", login=user.login, name=body.name)
    return row


@router.delete("/applications/{app_id}", status_code=204)
async def remove_application(
    app_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await delete_application(user.login, app_id, conn):
        raise HTTPException(status_code=404, detail="application not found")
    _log.info("application_deleted", login=user.login, app_id=app_id)


# ── Détection de favicon ──────────────────────────────────────────────────────

# <link rel="icon" href="…"> et variantes (shortcut icon, apple-touch-icon…),
# rel/href dans un ordre quelconque. Regex volontairement simple : on parse un
# HTML borné à _MAX_HTML_BYTES, pas besoin d'un parseur complet.
_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_REL_ICON_RE = re.compile(r"""\brel\s*=\s*["']?[^"'>]*icon[^"'>]*["']?""", re.IGNORECASE)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

_MAX_HTML_BYTES = 512 * 1024
_MAX_REDIRECTS = 3
_PROBE_TIMEOUT = 5.0


def extract_icon_hrefs(html: str) -> list[str]:
    """Extrait les href des <link rel*="icon"> dans l'ordre du document."""
    hrefs: list[str] = []
    for tag in _LINK_TAG_RE.findall(html):
        if not _REL_ICON_RE.search(tag):
            continue
        m = _HREF_RE.search(tag)
        if m:
            hrefs.append(m.group(1).strip())
    return hrefs


async def _get_following_redirects(
    client: httpx.AsyncClient, url: str
) -> tuple[str, httpx.Response]:
    """GET épinglé en suivant au plus _MAX_REDIRECTS redirections.

    pinned_get désactive le suivi automatique (chaque cible doit être re-validée
    anti-SSRF) : on suit donc manuellement, chaque saut repassant par le pin.
    Retourne (url_finale, réponse).
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        resp = await pinned_get(client, current, timeout=_PROBE_TIMEOUT, max_bytes=_MAX_HTML_BYTES)
        if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
            nxt = urljoin(current, resp.headers["location"])
            if not nxt.lower().startswith(_ALLOWED_SCHEMES):
                break
            current = nxt
            continue
        return current, resp
    raise HTTPException(status_code=422, detail="too many redirects")


def _is_image_response(resp: httpx.Response) -> bool:
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    return resp.status_code == 200 and ctype.startswith("image/")


@router.get("/applications/favicon")
async def probe_favicon(
    url: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, str | None]:
    """Tente de déterminer l'URL du favicon d'un site. `{"favicon": url | null}`.

    Candidats : les <link rel=icon> déclarés par la page (ordre du document),
    puis /favicon.svg et /favicon.ico à la racine du site. Un candidat n'est
    retenu que s'il répond 200 avec un Content-Type image/*.
    """
    url = url.strip()
    if not url.lower().startswith(_ALLOWED_SCHEMES):
        raise HTTPException(status_code=422, detail="url must start with http:// or https://")

    async with httpx.AsyncClient() as client:
        try:
            final_url, page = await _get_following_redirects(client, url)
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=422, detail=f"cannot fetch url: {exc}") from exc

        candidates: list[str] = []
        ctype = page.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype == "text/html":
            candidates.extend(
                urljoin(final_url, href) for href in extract_icon_hrefs(page.text)
            )
        parsed = urlparse(final_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        candidates.extend((f"{origin}/favicon.svg", f"{origin}/favicon.ico"))

        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen or not candidate.lower().startswith(_ALLOWED_SCHEMES):
                continue
            seen.add(candidate)
            try:
                _, resp = await _get_following_redirects(client, candidate)
            except (HTTPException, httpx.HTTPError):
                continue
            if _is_image_response(resp):
                _log.info("favicon_probed", url=url, favicon=candidate, login=user.login)
                return {"favicon": candidate}

    return {"favicon": None}
