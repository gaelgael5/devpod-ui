"""Routes CRUD des profils VSCode.

Deux routers :
- router       : préfixe /profiles  (user, monté sans préfixe dans app.py)
- router_admin : préfixe /profiles  (admin, monté sous /admin dans app.py → /admin/profiles)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from ..auth.rbac import UserInfo, require_admin, require_user
from ..profiles.models import Profile, ProfileBody, ProfileSummary, Scope
from ..profiles.repository import ProfileError, ProfileRepository

# ── Dépendance du repository ────────────────────────────────────────────────


def get_repo() -> ProfileRepository:
    """Remplacée par dependency_overrides dans le lifespan et les tests."""
    raise NotImplementedError  # pragma: no cover


_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*$"

# ── Router user ─────────────────────────────────────────────────────────────

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _http(e: ProfileError) -> HTTPException:
    mapping = {"not_found": 404, "conflict": 409, "forbidden": 403}
    return HTTPException(status_code=mapping.get(e.code, 400), detail=e.code)


@router.get("", response_model=list[ProfileSummary])
async def list_profiles(
    user: Annotated[UserInfo, Depends(require_user)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> list[ProfileSummary]:
    is_admin = "admin" in user.roles
    return repo.list(user.login, is_admin)


# IMPORTANT : /shared/{slug}/fork DOIT être déclaré avant /{scope}/{slug}
# pour éviter que FastAPI capte "shared" comme valeur de {scope} et "slug/fork"
# comme slug invalide.
@router.post("/shared/{slug}/fork", response_model=Profile, status_code=201)
async def fork_profile(
    slug: Annotated[str, Path(pattern=_SLUG_PATTERN)],
    user: Annotated[UserInfo, Depends(require_user)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> Profile:
    try:
        return repo.fork(user.login, slug)
    except ProfileError as e:
        raise _http(e) from e


@router.get("/{scope}/{slug}", response_model=Profile)
async def get_profile(
    scope: Scope,
    slug: Annotated[str, Path(pattern=_SLUG_PATTERN)],
    user: Annotated[UserInfo, Depends(require_user)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> Profile:
    try:
        return repo.get(scope, slug, user.login)
    except ProfileError as e:
        raise _http(e) from e


@router.post("", response_model=Profile, status_code=201)
async def create_profile(
    body: ProfileBody,
    user: Annotated[UserInfo, Depends(require_user)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> Profile:
    return repo.create(user.login, body)


@router.put("/{slug}", response_model=Profile)
async def update_profile(
    slug: Annotated[str, Path(pattern=_SLUG_PATTERN)],
    body: ProfileBody,
    user: Annotated[UserInfo, Depends(require_user)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> Profile:
    try:
        return repo.update(user.login, slug, body)
    except ProfileError as e:
        raise _http(e) from e


@router.delete("/{slug}", status_code=204)
async def delete_profile(
    slug: Annotated[str, Path(pattern=_SLUG_PATTERN)],
    user: Annotated[UserInfo, Depends(require_user)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> None:
    try:
        repo.delete(user.login, slug)
    except ProfileError as e:
        raise _http(e) from e


# ── Router admin (monté sous /admin dans app.py) ────────────────────────────

router_admin = APIRouter(prefix="/profiles", tags=["profiles"])


@router_admin.post("", response_model=Profile, status_code=201)
async def admin_create_shared(
    body: ProfileBody,
    _user: Annotated[UserInfo, Depends(require_admin)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> Profile:
    return repo.create_shared(body)


@router_admin.put("/{slug}", response_model=Profile)
async def admin_update_shared(
    slug: Annotated[str, Path(pattern=_SLUG_PATTERN)],
    body: ProfileBody,
    _user: Annotated[UserInfo, Depends(require_admin)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> Profile:
    try:
        return repo.update_shared(slug, body)
    except ProfileError as e:
        raise _http(e) from e


@router_admin.delete("/{slug}", status_code=204)
async def admin_delete_shared(
    slug: Annotated[str, Path(pattern=_SLUG_PATTERN)],
    _user: Annotated[UserInfo, Depends(require_admin)],
    repo: Annotated[ProfileRepository, Depends(get_repo)],
) -> None:
    try:
        repo.delete_shared(slug)
    except ProfileError as e:
        raise _http(e) from e
