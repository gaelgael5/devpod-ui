"""Tests du ProfileRepository sur un répertoire temporaire."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from portal.profiles.models import Profile, ProfileBody
from portal.profiles.repository import ProfileError, ProfileRepository, slugify

# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


def test_slugify_basic() -> None:
    assert slugify("Frontend React") == "frontend-react"


def test_slugify_special_chars() -> None:
    assert slugify("React + TypeScript!") == "react-typescript"


def test_slugify_empty_fallback() -> None:
    assert slugify("!!!") == "profil"


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------


def test_profile_body_defaults() -> None:
    body = ProfileBody(name="Test")
    assert body.description == ""
    assert body.extensions == []
    assert body.settings == {}


def test_profile_to_customizations() -> None:
    profile = Profile(
        slug="test",
        scope="user",
        name="Test",
        extensions=["ms-python.python"],
        settings={"editor.fontSize": 14},
    )
    result = profile.to_customizations()
    assert result == {
        "vscode": {
            "extensions": ["ms-python.python"],
            "settings": {"editor.fontSize": 14},
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> ProfileRepository:
    return ProfileRepository(tmp_path)


ALICE = "alice"
BOB = "bob"

BODY = ProfileBody(name="Frontend React", extensions=["esbenp.prettier-vscode"])


# ---------------------------------------------------------------------------
# create user
# ---------------------------------------------------------------------------


def test_create_writes_yaml_file(repo: ProfileRepository) -> None:
    profile = repo.create(ALICE, BODY)
    assert profile.slug == "frontend-react"
    assert profile.scope == "user"
    path = repo._path("user", "frontend-react", ALICE)
    assert path.is_file()
    raw = yaml.safe_load(path.read_text())
    assert raw["name"] == "Frontend React"
    assert raw["extensions"] == ["esbenp.prettier-vscode"]


def test_create_slug_collision_appends_suffix(repo: ProfileRepository) -> None:
    p1 = repo.create(ALICE, BODY)
    p2 = repo.create(ALICE, BODY)
    assert p1.slug == "frontend-react"
    assert p2.slug == "frontend-react-2"


def test_create_user_isolation(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.create(BOB, BODY)
    assert repo._path("user", "frontend-react", ALICE).is_file()
    assert repo._path("user", "frontend-react", BOB).is_file()
    # Bob ne voit pas les profils d'Alice via list()
    alice_profiles = [p.slug for p in repo.list(ALICE, False) if p.scope == "user"]
    bob_profiles = [p.slug for p in repo.list(BOB, False) if p.scope == "user"]
    assert "frontend-react" in alice_profiles
    assert "frontend-react" in bob_profiles
    # Mais Alice ne peut pas modifier le profil de Bob
    with pytest.raises(ProfileError) as exc:
        repo.update(ALICE, "frontend-react-bob-fake", BODY)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# update user
# ---------------------------------------------------------------------------


def test_update_modifies_yaml(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    updated_body = ProfileBody(name="Frontend React", description="Updated", extensions=[])
    result = repo.update(ALICE, "frontend-react", updated_body)
    assert result.description == "Updated"
    assert result.extensions == []
    raw = yaml.safe_load(repo._path("user", "frontend-react", ALICE).read_text())
    assert raw["description"] == "Updated"


def test_update_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.update(ALICE, "nonexistent", BODY)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# delete user
# ---------------------------------------------------------------------------


def test_delete_removes_file(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.delete(ALICE, "frontend-react")
    assert not repo._path("user", "frontend-react", ALICE).is_file()


def test_delete_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.delete(ALICE, "nonexistent")
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_returns_profile(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    profile = repo.get("user", "frontend-react", ALICE)
    assert profile.slug == "frontend-react"
    assert profile.scope == "user"
    assert profile.name == "Frontend React"


def test_get_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.get("user", "nonexistent", ALICE)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_includes_user_and_shared(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.create_shared(ProfileBody(name="Shared Profile"))
    summaries = repo.list(ALICE, is_admin=False)
    scopes = {s.scope for s in summaries}
    assert "user" in scopes
    assert "shared" in scopes


def test_list_editable_flag(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.create_shared(ProfileBody(name="Shared"))
    for s in repo.list(ALICE, is_admin=False):
        if s.scope == "user":
            assert s.editable is True
        else:
            assert s.editable is False


def test_list_editable_admin_can_edit_shared(repo: ProfileRepository) -> None:
    repo.create_shared(ProfileBody(name="Shared"))
    for s in repo.list(ALICE, is_admin=True):
        if s.scope == "shared":
            assert s.editable is True


# ---------------------------------------------------------------------------
# fork
# ---------------------------------------------------------------------------


def test_fork_creates_independent_copy(repo: ProfileRepository) -> None:
    shared_body = ProfileBody(name="Shared", extensions=["ms-python.python"])
    repo.create_shared(shared_body)
    forked = repo.fork(ALICE, "shared")
    assert forked.scope == "user"
    assert forked.extensions == ["ms-python.python"]
    # Modifier le partagé n'affecte pas le fork
    repo.update_shared("shared", ProfileBody(name="Shared", extensions=["new.ext"]))
    forked_again = repo.get("user", forked.slug, ALICE)
    assert forked_again.extensions == ["ms-python.python"]


def test_fork_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.fork(ALICE, "nonexistent")
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# shared (admin)
# ---------------------------------------------------------------------------


def test_create_shared_writes_to_data_profiles(repo: ProfileRepository) -> None:
    # "Partage" sans accent — slugify("[^a-z0-9]+" → "-") donne "partage"
    profile = repo.create_shared(ProfileBody(name="Partage"))
    assert profile.slug == "partage"
    assert profile.scope == "shared"
    assert (repo._data / "profiles" / "partage.yaml").is_file()


def test_update_shared_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.update_shared("nonexistent", BODY)
    assert exc.value.code == "not_found"


def test_delete_shared_removes_file(repo: ProfileRepository) -> None:
    repo.create_shared(ProfileBody(name="To Delete"))
    repo.delete_shared("to-delete")
    assert not (repo._data / "profiles" / "to-delete.yaml").is_file()


# ---------------------------------------------------------------------------
# écriture atomique
# ---------------------------------------------------------------------------


def test_atomic_write_no_tmp_residual(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    tmp_files = list((repo._data / "users" / ALICE / "profiles").glob("*.tmp"))
    assert tmp_files == []


# ---------------------------------------------------------------------------
# sécurité — path traversal
# ---------------------------------------------------------------------------


def test_path_traversal_slug_rejected(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.get("user", "../etc/passwd", ALICE)
    assert exc.value.code == "not_found"
