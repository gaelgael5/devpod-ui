"""Orchestration du flux OAuth client (Tranche 2), sans base ni réseau.

Le CRUD (`db`), le protocole (`oc`) et le chiffrement sont monkeypatchés : on teste
la logique d'orchestration et les gardes de sécurité (liaison state↔user, usage
unique, backend non-OAuth).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from portal.mcp import oauth_client as oc
from portal.mcp import oauth_flow

_BACKEND = {
    "id": "be1",
    "url": "https://mcp.example.com/mcp",
    "auth_scheme": "oauth",
    "oauth_auth_url": "",
}
_META = oc.ASMetadata(
    issuer="https://as.example.com",
    authorization_endpoint="https://as.example.com/authorize",
    token_endpoint="https://as.example.com/token",
    registration_endpoint="https://as.example.com/register",
    scopes_supported=["read", "write"],
)


class _Store:
    def __init__(self) -> None:
        self.client: dict | None = None
        self.pending: dict[str, dict] = {}
        self.token: dict[tuple[str, str], dict] = {}
        self.dcr_calls = 0


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    s = _Store()

    async def get_oauth_client(conn, backend_id):  # noqa: ANN001
        return s.client

    async def upsert_oauth_client(conn, backend_id, **kw):  # noqa: ANN001
        s.client = {"backend_id": backend_id, **kw}

    async def insert_pending(conn, **kw):  # noqa: ANN001
        s.pending[kw["state"]] = kw

    async def consume_pending(conn, state):  # noqa: ANN001
        row = s.pending.pop(state, None)
        if row is None or row["expires_at"] < datetime.now(UTC):
            return None
        return row

    async def upsert_oauth_token(conn, backend_id, user_login, **kw):  # noqa: ANN001
        s.token[(backend_id, user_login)] = kw

    async def get_oauth_token(conn, backend_id, user_login):  # noqa: ANN001
        return s.token.get((backend_id, user_login))

    async def delete_oauth_token(conn, backend_id, user_login):  # noqa: ANN001
        return s.token.pop((backend_id, user_login), None) is not None

    for name, fn in {
        "get_oauth_client": get_oauth_client,
        "upsert_oauth_client": upsert_oauth_client,
        "insert_pending": insert_pending,
        "consume_pending": consume_pending,
        "upsert_oauth_token": upsert_oauth_token,
        "get_oauth_token": get_oauth_token,
        "delete_oauth_token": delete_oauth_token,
    }.items():
        monkeypatch.setattr(oauth_flow.db, name, fn)

    async def discover_metadata(url, auth_url=None):  # noqa: ANN001
        return _META

    async def register_client(metadata, redirect_uri, *, client_name, scopes):  # noqa: ANN001
        s.dcr_calls += 1
        return "cid-xyz", None

    monkeypatch.setattr(oauth_flow.oc, "discover_metadata", discover_metadata)
    monkeypatch.setattr(oauth_flow.oc, "register_client", register_client)
    # Chiffrement : évite d'exiger PORTAL_VAULT_KEK dans les tests.
    monkeypatch.setattr(oauth_flow, "encrypt_service_key", lambda v: b"enc:" + v.encode())
    monkeypatch.setattr(
        oauth_flow, "decrypt_service_key", lambda b: b.decode().removeprefix("enc:")
    )

    async def get_backend(conn, login, backend_id):  # noqa: ANN001
        return _BACKEND if backend_id == _BACKEND["id"] else None

    monkeypatch.setattr(oauth_flow.mcp_db, "get_backend", get_backend)
    return s


def test_redirect_uri_for() -> None:
    assert (
        oauth_flow.redirect_uri_for("https://portal.example/")
        == "https://portal.example/me/mcp/oauth/callback"
    )


@pytest.mark.asyncio
async def test_start_registers_client_and_builds_url(store: _Store) -> None:
    url = await oauth_flow.start_authorization(
        object(), _BACKEND, "alice", "https://portal.example"
    )
    assert store.dcr_calls == 1  # DCR au premier appel
    assert store.client is not None and store.client["client_id"] == "cid-xyz"
    # Un state a été mémorisé et se retrouve dans l'URL, avec la ressource.
    (state_key,) = store.pending.keys()
    q = parse_qs(urlsplit(url).query)
    assert q["state"] == [state_key]
    assert q["resource"] == ["https://mcp.example.com/mcp"]
    assert q["client_id"] == ["cid-xyz"]
    assert q["code_challenge_method"] == ["S256"]
    assert store.pending[state_key]["user_login"] == "alice"


@pytest.mark.asyncio
async def test_start_reuses_existing_client(store: _Store) -> None:
    store.client = {
        "backend_id": "be1",
        "issuer": _META.issuer,
        "authorization_endpoint": _META.authorization_endpoint,
        "token_endpoint": _META.token_endpoint,
        "registration_endpoint": _META.registration_endpoint,
        "client_id": "cid-existing",
        "client_secret_enc": None,
        "scopes": "read",
    }
    url = await oauth_flow.start_authorization(object(), _BACKEND, "bob", "https://portal.example")
    assert store.dcr_calls == 0  # pas de ré-enregistrement
    assert parse_qs(urlsplit(url).query)["client_id"] == ["cid-existing"]


@pytest.mark.asyncio
async def test_start_rejects_non_oauth_backend(store: _Store) -> None:
    with pytest.raises(oauth_flow.OAuthFlowError):
        await oauth_flow.start_authorization(
            object(), {**_BACKEND, "auth_scheme": "bearer"}, "alice", "https://portal.example"
        )


@pytest.mark.asyncio
async def test_complete_stores_token(store: _Store, monkeypatch: pytest.MonkeyPatch) -> None:
    store.client = {
        "backend_id": "be1",
        "issuer": _META.issuer,
        "authorization_endpoint": _META.authorization_endpoint,
        "token_endpoint": _META.token_endpoint,
        "registration_endpoint": _META.registration_endpoint,
        "client_id": "cid",
        "client_secret_enc": None,
        "scopes": "read",
    }
    store.pending["st"] = {
        "state": "st",
        "backend_id": "be1",
        "user_login": "alice",
        "code_verifier": "ver",
        "redirect_uri": "https://portal.example/me/mcp/oauth/callback",
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }

    async def exchange_code(metadata, **kw):  # noqa: ANN001
        assert kw["code_verifier"] == "ver"
        return oc.TokenResponse(
            access_token="at", refresh_token="rt", expires_in=3600, scope="read"
        )

    monkeypatch.setattr(oauth_flow.oc, "exchange_code", exchange_code)

    backend_id = await oauth_flow.complete_authorization(object(), "st", "the-code", "alice")
    assert backend_id == "be1"
    stored = store.token[("be1", "alice")]
    assert stored["access_token_enc"] == b"enc:at"
    assert stored["refresh_token_enc"] == b"enc:rt"
    assert stored["expires_at"] is not None
    assert "st" not in store.pending  # usage unique


@pytest.mark.asyncio
async def test_complete_rejects_unknown_state(store: _Store) -> None:
    with pytest.raises(oauth_flow.OAuthFlowError):
        await oauth_flow.complete_authorization(object(), "absent", "code", "alice")


@pytest.mark.asyncio
async def test_complete_rejects_user_mismatch(store: _Store) -> None:
    store.pending["st"] = {
        "state": "st",
        "backend_id": "be1",
        "user_login": "alice",
        "code_verifier": "ver",
        "redirect_uri": "https://portal.example/me/mcp/oauth/callback",
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    with pytest.raises(oauth_flow.OAuthFlowError):
        # bob tente de rejouer le state d'alice
        await oauth_flow.complete_authorization(object(), "st", "code", "bob")
    assert "st" not in store.pending  # consommé quand même (anti-rejeu)


@pytest.mark.asyncio
async def test_status_and_disconnect(store: _Store) -> None:
    assert await oauth_flow.get_status(object(), "be1", "alice") == {
        "connected": False,
        "expires_at": None,
        "scopes": "",
    }
    store.token[("be1", "alice")] = {"expires_at": None, "scopes": "read"}
    st = await oauth_flow.get_status(object(), "be1", "alice")
    assert st["connected"] is True and st["scopes"] == "read"
    assert await oauth_flow.disconnect(object(), "be1", "alice") is True
    assert await oauth_flow.disconnect(object(), "be1", "alice") is False
