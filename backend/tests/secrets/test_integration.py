from __future__ import annotations

from unittest.mock import MagicMock

import yaml

from portal.secrets.backends.inline import InlineBackend
from portal.secrets.resolver import Scope, resolve
from portal.secrets.types import Secret

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
USER_SCOPE = Scope(kind="user", secret_ns=USER_NS, login="alice")


def test_inline_backend_works_as_fallback(tmp_path):
    """Vérifie que le backend inline fonctionne en remplacement de Harpocrate."""
    (tmp_path / "secrets.yaml").write_text(yaml.dump({"llm": {"key": "inline_value"}}))
    inline = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path="devpod")
    result = resolve("${vault://llm/key}", USER_SCOPE, inline)
    assert isinstance(result, Secret)
    assert result.reveal() == "inline_value"


def test_secret_repr_safe_in_exception_message():
    s = Secret("top_secret_value")
    try:
        raise ValueError(f"processing failed for secret={s}")
    except ValueError as e:
        assert "top_secret_value" not in str(e)


def test_literal_is_plain_string_not_secret():
    b = MagicMock()
    b.base_path = "devpod"
    result = resolve("plain value", USER_SCOPE, b)
    assert isinstance(result, str)
    assert not isinstance(result, Secret)
    b.get.assert_not_called()


def test_env_resolution_does_not_call_backend(monkeypatch):
    monkeypatch.setenv("PORTAL_TEST_KEY", "from_env")
    b = MagicMock()
    b.base_path = "devpod"
    result = resolve("${env://PORTAL_TEST_KEY}", USER_SCOPE, b)
    assert isinstance(result, Secret)
    assert result.reveal() == "from_env"
    b.get.assert_not_called()
