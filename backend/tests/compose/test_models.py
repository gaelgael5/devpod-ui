import pytest
from pydantic import ValidationError

from portal.compose import models


def test_param_minimal() -> None:
    p = models.ComposeParam(key="BROWSERLESS_PORT", label="Port", type="port", required=True)
    assert p.key == "BROWSERLESS_PORT"
    assert p.default is None and p.options is None


def test_template_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        models.ComposeTemplate(
            id="x", name="X", version="1", compose_content="services: {}",
            parameters=[], source="user", bogus=1,
        )


def test_validate_slug() -> None:
    assert models.validate_slug("browserless-1") == "browserless-1"
    for bad in ("Bad", "-x", "x_y", "a", "x" * 60, "a b"):
        with pytest.raises(ValueError):
            models.validate_slug(bad)


def test_deployment_defaults() -> None:
    d = models.ComposeDeployment(
        id="dep1", template_id="t", template_version="1", node_id="n",
        owner_login="alice",
    )
    assert d.env_values == {} and d.host_ports == [] and d.status == "created"
