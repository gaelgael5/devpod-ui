from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from portal.secrets.backends.base import SecretsBackend
from portal.secrets.resolver import Scope, SecretAccessError, resolve
from portal.secrets.types import Secret

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
OTHER_NS = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_SCOPE = Scope(kind="user", secret_ns=USER_NS, login="alice")
GLOBAL_SCOPE = Scope(kind="global", secret_ns="", login="")


def _backend(return_value: str = "resolved") -> SecretsBackend:
    b = MagicMock(spec=SecretsBackend)  # type: ignore[arg-type]
    b.get.return_value = return_value
    b.base_path = "devpod"
    return b


def test_literal_returned_unchanged():
    result = resolve("hello world", USER_SCOPE, _backend())
    assert result == "hello world"
    assert not isinstance(result, Secret)


def test_empty_string_returned_unchanged():
    result = resolve("", USER_SCOPE, _backend())
    assert result == ""


def test_env_ref_rejected_in_user_resolver(monkeypatch):
    # Bug 002 : env:// exposé aux entrées utilisateur permettait d'exfiltrer
    # n'importe quelle variable du process. Le résolveur user-facing le refuse.
    monkeypatch.setenv("MY_TEST_TOKEN", "env_value")
    b = _backend()
    with pytest.raises(SecretAccessError, match="env://"):
        resolve("${env://MY_TEST_TOKEN}", USER_SCOPE, b)
    b.get.assert_not_called()


def test_env_ref_rejected_even_for_sensitive_process_var(monkeypatch):
    # Le secret existe dans l'environnement du process : il ne doit JAMAIS
    # être renvoyé, quel que soit son nom.
    monkeypatch.setenv("PORTAL_VAULT_KEK", "kek-super-secret")
    with pytest.raises(SecretAccessError, match="env://"):
        resolve("${env://PORTAL_VAULT_KEK}", USER_SCOPE, _backend())


def test_env_ref_rejected_in_global_scope(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", "sig-key")
    with pytest.raises(SecretAccessError, match="env://"):
        resolve("${env://SESSION_SECRET_KEY}", GLOBAL_SCOPE, _backend())


def test_vault_user_prefixes_namespace():
    b = _backend("secret_value")
    result = resolve("${vault://git/my_key}", USER_SCOPE, b)
    b.get.assert_called_once_with(f"devpod/{USER_NS}/git/my_key")
    assert isinstance(result, Secret)
    assert result.reveal() == "secret_value"


def test_vault_user_rejects_absolute_path():
    with pytest.raises(SecretAccessError, match="absolute"):
        resolve("${vault:///etc/passwd}", USER_SCOPE, _backend())


def test_vault_user_rejects_dotdot():
    with pytest.raises(SecretAccessError, match=r"\.\.|traversal"):
        resolve("${vault://../other/secret}", USER_SCOPE, _backend())


def test_vault_user_rejects_foreign_namespace():
    with pytest.raises(SecretAccessError, match="namespace"):
        resolve(f"${{vault://{OTHER_NS}/secret}}", USER_SCOPE, _backend())


def test_vault_global_uses_path_as_is():
    b = _backend("global_secret")
    result = resolve("${vault://devpod/somekey}", GLOBAL_SCOPE, b)
    b.get.assert_called_once_with("devpod/somekey")
    assert isinstance(result, Secret)
