from __future__ import annotations

import hmac
from hashlib import sha256

import portal.mcp.dispatch_common as dc
from portal.mcp.aggregator import CallTarget
from portal.mcp.obo import (
    ACTOR_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    build_obo_headers,
    sign_actor,
)


def test_build_obo_headers_shape() -> None:
    h = build_obo_headers("alice", "s3cr3t", now=1_700_000_000)
    assert h[ACTOR_HEADER] == "alice"
    assert h[TIMESTAMP_HEADER] == "1700000000"
    assert h[SIGNATURE_HEADER] == sign_actor("alice", 1_700_000_000, "s3cr3t")


def test_signature_is_hmac_sha256_of_canonical_payload() -> None:
    """Le service doit pouvoir revérifier avec la clé partagée : contrat figé."""
    expected = hmac.new(b"s3cr3t", b"alice\n1700000000", sha256).hexdigest()
    assert sign_actor("alice", 1_700_000_000, "s3cr3t") == expected


def test_signature_binds_actor_and_timestamp() -> None:
    base = sign_actor("alice", 1_700_000_000, "k")
    assert sign_actor("bob", 1_700_000_000, "k") != base  # acteur différent
    assert sign_actor("alice", 1_700_000_001, "k") != base  # timestamp différent
    assert sign_actor("alice", 1_700_000_000, "k2") != base  # secret différent


def test_forged_actor_without_secret_cannot_match() -> None:
    """Sans la clé (côté client), impossible de reproduire la signature."""
    legit = build_obo_headers("admin", "server-only-secret", now=1_700_000_000)
    forged = sign_actor("admin", 1_700_000_000, "guessed-secret")
    assert forged != legit[SIGNATURE_HEADER]


# --- obo_headers_for : propage le sub OIDC (pas le login), fail-safe ---------


def _target(*, forward_identity: bool) -> CallTarget:
    return CallTarget(
        backend_id="b1",
        original_name="tool",
        url="https://x/mcp",
        transport="streamable_http",
        forward_identity=forward_identity,
        backend_key_id="k1",
    )


async def test_obo_headers_for_propagates_sub_not_login(monkeypatch) -> None:
    async def fake_sub(login: str, conn: object) -> str:
        assert login == "gael"  # on résout bien par login…
        return "oidc-sub-guid"  # …mais on propage le sub

    monkeypatch.setattr(dc, "get_user_sub", fake_sub)
    headers = await dc.obo_headers_for(object(), _target(forward_identity=True), "gael", "key")
    assert headers is not None
    assert headers[ACTOR_HEADER] == "oidc-sub-guid"


async def test_obo_headers_for_none_when_not_opt_in(monkeypatch) -> None:
    monkeypatch.setattr(dc, "get_user_sub", lambda login, conn: "s")  # ne doit pas être appelé
    assert (
        await dc.obo_headers_for(object(), _target(forward_identity=False), "gael", "key") is None
    )


async def test_obo_headers_for_none_without_bearer() -> None:
    assert await dc.obo_headers_for(object(), _target(forward_identity=True), "gael", None) is None


async def test_obo_headers_for_none_when_user_has_no_sub(monkeypatch) -> None:
    async def no_sub(login: str, conn: object) -> None:
        return None

    monkeypatch.setattr(dc, "get_user_sub", no_sub)
    assert await dc.obo_headers_for(object(), _target(forward_identity=True), "gael", "key") is None
