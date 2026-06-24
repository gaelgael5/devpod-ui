from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_host_config_has_no_key_path() -> None:
    """HostConfig ne doit plus accepter key_path (extra=forbid)."""
    from portal.config.models import HostConfig

    with pytest.raises(ValidationError):
        HostConfig(name="test", type="ssh", key_path="/data/keys/test")


def test_host_config_accepts_slugs() -> None:
    from portal.config.models import HostConfig

    h = HostConfig(
        name="my-host",
        type="ssh",
        address="debian@192.168.1.50",
        host_cert_slug="host.my-host.cert",
        ci_password_secret_slug="",
        storage_type="local",
        vault_identifier="",
    )
    assert h.host_cert_slug == "host.my-host.cert"
    assert h.storage_type == "local"


def test_host_config_has_no_ci_password_field() -> None:
    """HostConfig ne doit plus accepter ci_password (extra=forbid)."""
    from portal.config.models import HostConfig

    with pytest.raises(ValidationError):
        HostConfig(name="test", type="docker-tls", ci_password="secret")


def test_host_config_usage_defaults_to_workspaces() -> None:
    from portal.config.models import HostConfig

    h = HostConfig(name="test", type="docker-tls")
    assert h.usage == "workspaces"


def test_host_config_usage_tests_accepted() -> None:
    from portal.config.models import HostConfig

    h = HostConfig(name="test", type="docker-tls", usage="tests")
    assert h.usage == "tests"


def test_host_config_usage_invalid_rejected() -> None:
    from portal.config.models import HostConfig

    with pytest.raises(ValidationError):
        HostConfig(name="test", type="docker-tls", usage="staging")
