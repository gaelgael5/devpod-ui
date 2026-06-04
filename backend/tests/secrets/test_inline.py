from __future__ import annotations

import pytest
import yaml

from portal.secrets.backends.inline import InlineBackend

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
BASE = "devpod"


def test_get_returns_string_value(tmp_path):
    (tmp_path / "secrets.yaml").write_text(yaml.dump({"git": {"my_token": "abc123"}}))
    backend = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path=BASE)
    assert backend.get(f"{BASE}/{USER_NS}/git/my_token") == "abc123"


def test_get_raises_key_error_on_missing_key(tmp_path):
    (tmp_path / "secrets.yaml").write_text(yaml.dump({"git": {}}))
    backend = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path=BASE)
    with pytest.raises(KeyError):
        backend.get(f"{BASE}/{USER_NS}/git/missing")


def test_get_raises_on_missing_file(tmp_path):
    backend = InlineBackend(
        user_secrets_path=tmp_path / "nonexistent.yaml", base_path=BASE
    )
    with pytest.raises(FileNotFoundError):
        backend.get(f"{BASE}/{USER_NS}/git/key")


def test_get_nested_key(tmp_path):
    (tmp_path / "secrets.yaml").write_text(
        yaml.dump({"llm": {"anthropic": {"key": "sk-abc"}}})
    )
    backend = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path=BASE)
    assert backend.get(f"{BASE}/{USER_NS}/llm/anthropic/key") == "sk-abc"
