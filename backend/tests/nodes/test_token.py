from __future__ import annotations

from pathlib import Path

import pytest

from portal.nodes.enroll import consume_token, generate_token


def test_generate_token_returns_nonempty_string(tmp_data_root: Path) -> None:
    token = generate_token("pve2-docker", "192.168.1.50")
    assert len(token) >= 32


async def test_consume_token_returns_node_info(tmp_data_root: Path) -> None:
    token = generate_token("pve2-docker", "192.168.1.50")
    node_name, address = await consume_token(token)
    assert node_name == "pve2-docker"
    assert address == "192.168.1.50"


async def test_consume_token_reuse_raises(tmp_data_root: Path) -> None:
    token = generate_token("pve2-docker", "192.168.1.50")
    await consume_token(token)
    with pytest.raises(ValueError, match="already used"):
        await consume_token(token)


async def test_consume_token_expired_raises(
    tmp_data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import portal.nodes.enroll as enroll_mod

    monkeypatch.setattr(enroll_mod, "_TOKEN_TTL_SECONDS", -1)
    token = generate_token("pve2-docker", "192.168.1.50")
    with pytest.raises(ValueError, match="expired"):
        await consume_token(token)


async def test_consume_unknown_token_raises(tmp_data_root: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        await consume_token("nonexistent-token-that-does-not-exist")
