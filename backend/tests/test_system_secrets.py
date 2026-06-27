from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── _system_master_key ────────────────────────────────────────────────────────


def test_system_master_key_requires_kek() -> None:
    """Lève RuntimeError si portal_vault_kek vide."""
    from portal.secrets.system import _system_master_key

    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = ""
        with pytest.raises(RuntimeError, match="PORTAL_VAULT_KEK"):
            _system_master_key()


def test_system_master_key_is_deterministic() -> None:
    kek = "ab" * 32  # 64 hex chars
    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = kek
        from portal.secrets.system import _system_master_key

        k1 = _system_master_key()
        k2 = _system_master_key()
    assert len(k1) == 32
    assert k1 == k2


def test_system_master_key_differs_from_kek() -> None:
    kek = "cd" * 32
    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = kek
        from portal.secrets.system import _system_master_key

        key = _system_master_key()
    assert key != bytes.fromhex(kek)  # HKDF transforme la valeur


# ── encrypt/decrypt roundtrip ─────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip() -> None:
    from portal.vault.crypto import decrypt_token, encrypt_token

    key = bytes(32)  # clé nulle pour le test
    plaintext = "super-secret-password"
    blob = encrypt_token(plaintext, key)
    assert decrypt_token(blob, key) == plaintext


# ── ensure_system_user ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_system_user_inserts_if_absent() -> None:
    from portal.secrets.system import ensure_system_user

    conn = AsyncMock()
    # AsyncMock.execute() retourne un MagicMock ; one_or_none() doit retourner None
    select_result = MagicMock()
    select_result.one_or_none.return_value = None
    conn.execute.return_value = select_result

    await ensure_system_user(conn)

    # Vérifier qu'un INSERT a été appelé (SELECT + INSERT = 2 appels)
    assert conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_ensure_system_user_idempotent() -> None:
    from portal.secrets.system import ensure_system_user

    conn = AsyncMock()
    # AsyncMock.execute() retourne un MagicMock ; one_or_none() retourne une ligne
    select_result = MagicMock()
    select_result.one_or_none.return_value = {"login": "__system__"}
    conn.execute.return_value = select_result

    await ensure_system_user(conn)

    # Seulement le SELECT, pas d'INSERT
    assert conn.execute.call_count == 1


# ── store/reveal secret ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_system_secret_local_does_not_raise() -> None:
    """store_system_secret local ne doit pas lever d'exception."""
    from portal.secrets.system import store_system_secret

    conn = AsyncMock()

    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = "ff" * 32
        await store_system_secret(
            slug="host.test-host.ci-password",
            label="Test",
            value="my-password",
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
    # DELETE + INSERT attendus
    assert conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_reveal_system_secret_raises_if_absent() -> None:
    from portal.secrets.system import reveal_system_secret

    conn = AsyncMock()
    # Construire une chaîne MagicMock pour que .mappings().one_or_none() retourne None
    select_result = MagicMock()
    select_result.mappings.return_value.one_or_none.return_value = None
    conn.execute.return_value = select_result

    with pytest.raises(KeyError, match="not found"):
        await reveal_system_secret("host.ghost.ci-password", conn)


@pytest.mark.asyncio
async def test_delete_system_secret_calls_execute() -> None:
    from portal.secrets.system import delete_system_secret

    conn = AsyncMock()
    await delete_system_secret("host.test.ci-password", conn)
    assert conn.execute.call_count == 1


# ── store/reveal cert ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_system_cert_local_does_not_raise() -> None:
    """store_system_cert local ne doit pas lever d'exception."""
    from portal.secrets.system import store_system_cert

    conn = AsyncMock()

    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = "aa" * 32
        await store_system_cert(
            slug="host.test-host.key",
            label="Test key",
            private_pem="-----BEGIN EC PRIVATE KEY-----\nfake\n-----END EC PRIVATE KEY-----",
            public_key="ssh-ed25519 AAAA... comment",
            cert_type="ssh-ed25519",
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
    # DELETE + INSERT attendus
    assert conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_reveal_system_cert_raises_if_absent() -> None:
    from portal.secrets.system import reveal_system_cert

    conn = AsyncMock()
    # Construire une chaîne MagicMock pour que .mappings().one_or_none() retourne None
    select_result = MagicMock()
    select_result.mappings.return_value.one_or_none.return_value = None
    conn.execute.return_value = select_result

    with pytest.raises(KeyError, match="not found"):
        await reveal_system_cert("host.ghost.key", conn)


@pytest.mark.asyncio
async def test_delete_system_cert_calls_execute() -> None:
    from portal.secrets.system import delete_system_cert

    conn = AsyncMock()
    await delete_system_cert("host.test.key", conn)
    assert conn.execute.call_count == 1
