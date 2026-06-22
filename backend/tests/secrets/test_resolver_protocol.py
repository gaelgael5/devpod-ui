from __future__ import annotations

import pytest

from portal.secrets.resolver import EnvSecretResolver, SecretAccessError, SecretResolver
from portal.secrets.types import Secret


async def test_env_resolver_resolves(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RAG_TOKEN", "s3cr3t")
    r = EnvSecretResolver()
    out = await r.resolve("${env://MCP_RAG_TOKEN}")
    assert isinstance(out, Secret)
    assert out.reveal() == "s3cr3t"
    # le repr ne fuit jamais la valeur
    assert "s3cr3t" not in repr(out)


async def test_env_resolver_missing_var(monkeypatch) -> None:
    monkeypatch.delenv("MCP_ABSENT", raising=False)
    with pytest.raises(SecretAccessError):
        await EnvSecretResolver().resolve("${env://MCP_ABSENT}")


async def test_env_resolver_rejects_non_env_ref() -> None:
    with pytest.raises(SecretAccessError):
        await EnvSecretResolver().resolve("${vault://foo/bar}")


def test_env_resolver_satisfies_protocol() -> None:
    assert isinstance(EnvSecretResolver(), SecretResolver)
