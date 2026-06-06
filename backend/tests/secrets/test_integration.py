from __future__ import annotations

from unittest.mock import MagicMock

import yaml

from portal.secrets.backends.inline import InlineBackend
from portal.secrets.resolver import Scope, resolve
from portal.secrets.types import Secret

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
USER_SCOPE = Scope(kind="user", secret_ns=USER_NS, login="alice")


def test_inline_backend_resolves_vault_reference(tmp_path):
    """Vérifie que le backend inline résout correctement une référence vault."""
    (tmp_path / "secrets.yaml").write_text(yaml.dump({"llm": {"key": "inline_value"}}))
    inline = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path="devpod")
    result = resolve("${vault://llm/key}", USER_SCOPE, inline)
    assert isinstance(result, Secret)
    assert result.reveal() == "inline_value"


def test_create_backend_falls_back_to_inline_when_api_key_empty(tmp_path):
    """Quand api_key est vide, create_backend doit retourner un InlineBackend."""
    from portal.secrets.factory import create_backend

    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text("devpod:\n  abc123:\n    key: secret_value\n", encoding="utf-8")

    backend = create_backend(
        backend_type="harpocrate",
        api_key="",
        base_path="devpod",
        user_secrets_path=secrets_file,
    )

    assert isinstance(backend, InlineBackend)


def test_create_backend_logs_warning_when_api_key_empty(tmp_path):
    """create_backend doit logger un warning quand api_key est vide."""
    import structlog.testing

    from portal.secrets.factory import create_backend

    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text("{}", encoding="utf-8")

    with structlog.testing.capture_logs() as log_events:
        create_backend(
            backend_type="harpocrate",
            api_key="",
            base_path="devpod",
            user_secrets_path=secrets_file,
        )

    warning_events = [e for e in log_events if "harpocrate_api_key_empty" in e.get("event", "")]
    assert len(warning_events) >= 1


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
