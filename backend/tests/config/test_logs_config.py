"""Tests unitaires pour LogsConfig."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.config.models import GlobalConfig, LogsConfig


def test_defaults_disabled() -> None:
    cfg = LogsConfig()
    assert cfg.enabled is False
    assert cfg.loki_push_url is None
    assert cfg.loki_query_url is None
    assert cfg.grafana_url is None
    assert cfg.module == "devpod"
    assert cfg.push_token is None
    assert cfg.grafana_oauth_client_secret is None


def test_full_config() -> None:
    cfg = LogsConfig(
        enabled=True,
        loki_push_url="http://192.168.10.50:3100/loki/api/v1/push",
        loki_query_url="http://loki:3100",
        grafana_url="https://log.dev.yoops.org",
        module="devpod",
        push_token="${vault://logs/loki_push_token}",
        grafana_oauth_client_secret="gf-secret",
    )
    assert cfg.enabled is True
    assert cfg.push_token == "${vault://logs/loki_push_token}"
    assert cfg.grafana_oauth_client_secret == "gf-secret"


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        LogsConfig(unknown_field="oops")


def test_global_config_has_logs_section() -> None:
    cfg = GlobalConfig.model_validate(
        {
            "version": "1",
            "server": {
                "base_domain": "dev.yoops.org",
                "external_url": "https://portal.dev.yoops.org",
            },
            "auth": {
                "oidc": {
                    "issuer": "https://security.yoops.org/realms/yoops",
                    "client_id": "workspace-portal",
                    "client_secret": "secret",
                }
            },
            "logs": {
                "enabled": True,
                "loki_query_url": "http://loki:3100",
                "grafana_url": "https://log.dev.yoops.org",
            },
        }
    )
    assert cfg.logs.enabled is True
    assert cfg.logs.grafana_url == "https://log.dev.yoops.org"


def test_global_config_logs_defaults_when_absent() -> None:
    cfg = GlobalConfig.model_validate(
        {
            "version": "1",
            "server": {
                "base_domain": "dev.yoops.org",
                "external_url": "https://portal.dev.yoops.org",
            },
            "auth": {
                "oidc": {
                    "issuer": "https://security.yoops.org/realms/yoops",
                    "client_id": "workspace-portal",
                    "client_secret": "secret",
                }
            },
        }
    )
    assert cfg.logs.enabled is False
    assert cfg.logs.loki_push_url is None
