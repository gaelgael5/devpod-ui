"""Tests DTOs de la galerie compose (pur pydantic, sans TestClient)."""
import pytest

from portal.schemas import compose as sc


def test_template_create_body_validates() -> None:
    body = sc.TemplateCreateBody(
        id="browserless", name="Browserless", version="1",
        compose_content='services:\n  b:\n    image: x:1\n    ports: ["${P}:3000"]',
        parameters=[{"key": "P", "label": "Port", "type": "port", "required": True}],
    )
    assert body.id == "browserless"


def test_template_create_body_forbids_extra() -> None:
    with pytest.raises(Exception):  # noqa: B017
        sc.TemplateCreateBody(  # type: ignore[call-arg]
            id="x", name="X", version="1",
            compose_content="services: {}",
            bogus=1,
        )
