from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import cast

import structlog
import yaml

from .models import Profile, ProfileBody, ProfileSummary, Scope

_log = structlog.get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_VALID_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "profil"


class ProfileError(Exception):
    def __init__(self, code: str) -> None:  # "not_found" | "conflict" | "forbidden"
        super().__init__(code)
        self.code = code


class ProfileRepository:
    def __init__(self, data_dir: Path) -> None:
        self._data = data_dir

    def _dir(self, scope: Scope, login: str | None) -> Path:
        if scope == "shared":
            return self._data / "profiles"
        if not login:
            raise ProfileError("forbidden")
        return self._data / "users" / login / "profiles"

    def _path(self, scope: Scope, slug: str, login: str | None) -> Path:
        if not _VALID_SLUG.fullmatch(slug):
            raise ProfileError("not_found")
        return self._dir(scope, login) / f"{slug}.yaml"

    def list(self, login: str, is_admin: bool) -> list[ProfileSummary]:
        out: list[ProfileSummary] = []
        for scope, base in (
            ("shared", self._dir("shared", None)),
            ("user", self._dir("user", login)),
        ):
            if not base.is_dir():
                continue
            for f in sorted(base.glob("*.yaml")):
                p = self._read(f, cast(Scope, scope), f.stem)
                editable = is_admin if scope == "shared" else True
                out.append(
                    ProfileSummary(
                        slug=p.slug,
                        scope=p.scope,
                        name=p.name,
                        description=p.description,
                        extension_count=len(p.extensions),
                        editable=editable,
                    )
                )
        return out

    def get(self, scope: Scope, slug: str, login: str) -> Profile:
        path = self._path(scope, slug, None if scope == "shared" else login)
        if not path.is_file():
            raise ProfileError("not_found")
        return self._read(path, scope, slug)

    def create(self, login: str, body: ProfileBody) -> Profile:
        return self._write("user", login, slugify(body.name), body, allow_overwrite=False)

    def update(self, login: str, slug: str, body: ProfileBody) -> Profile:
        if not self._path("user", slug, login).is_file():
            raise ProfileError("not_found")
        return self._write("user", login, slug, body, allow_overwrite=True)

    def delete(self, login: str, slug: str) -> None:
        path = self._path("user", slug, login)
        if not path.is_file():
            raise ProfileError("not_found")
        path.unlink()

    def fork(self, login: str, shared_slug: str) -> Profile:
        src = self.get("shared", shared_slug, login)
        body = ProfileBody(
            **src.model_dump(include={"name", "description", "extensions", "settings"})
        )
        return self._write("user", login, slugify(src.name), body, allow_overwrite=False)

    def create_shared(self, body: ProfileBody) -> Profile:
        return self._write("shared", None, slugify(body.name), body, allow_overwrite=False)

    def update_shared(self, slug: str, body: ProfileBody) -> Profile:
        if not self._path("shared", slug, None).is_file():
            raise ProfileError("not_found")
        return self._write("shared", None, slug, body, allow_overwrite=True)

    def delete_shared(self, slug: str) -> None:
        path = self._path("shared", slug, None)
        if not path.is_file():
            raise ProfileError("not_found")
        path.unlink()

    def _read(self, path: Path, scope: Scope, slug: str) -> Profile:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Profile(slug=slug, scope=scope, **ProfileBody(**raw).model_dump())

    def _write(
        self,
        scope: Scope,
        login: str | None,
        slug: str,
        body: ProfileBody,
        *,
        allow_overwrite: bool,
    ) -> Profile:
        base = self._dir(scope, login)
        base.mkdir(parents=True, exist_ok=True)
        slug = self._unique_slug(base, slug, allow_overwrite)
        path = base / f"{slug}.yaml"
        self._atomic_dump(path, body)
        _log.info("profile.write", scope=scope, slug=slug)
        return Profile(slug=slug, scope=scope, **body.model_dump())

    @staticmethod
    def _unique_slug(base: Path, slug: str, allow_overwrite: bool) -> str:
        if allow_overwrite or not (base / f"{slug}.yaml").exists():
            return slug
        i = 2
        while (base / f"{slug}-{i}.yaml").exists():
            i += 1
        return f"{slug}-{i}"

    @staticmethod
    def _atomic_dump(path: Path, body: ProfileBody) -> None:
        data = yaml.safe_dump(body.model_dump(), allow_unicode=True, sort_keys=False)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
