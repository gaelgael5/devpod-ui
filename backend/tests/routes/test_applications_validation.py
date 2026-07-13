"""Validation du DTO du kiosque d'applications (sans DB)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.routes.applications import ApplicationCreate


def test_accepts_https_url_and_emoji_icon() -> None:
    app = ApplicationCreate(name=" Doc ", url="https://doc.yoops.org", icon=" 📚 ")
    assert app.name == "Doc"
    assert app.url == "https://doc.yoops.org"
    assert app.icon == "📚"


def test_accepts_http_url_and_image_icon() -> None:
    app = ApplicationCreate(
        name="Rag", url="http://rag.local", icon="https://cdn.io/rag.png"
    )
    assert app.icon == "https://cdn.io/rag.png"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "ftp://x.io",
        "doc.yoops.org",  # schéma manquant
        "",
    ],
)
def test_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        ApplicationCreate(name="Doc", url=url)


def test_rejects_javascript_icon_url() -> None:
    with pytest.raises(ValidationError):
        ApplicationCreate(name="Doc", url="https://x.io", icon="javascript://x")


def test_rejects_empty_or_long_name() -> None:
    with pytest.raises(ValidationError):
        ApplicationCreate(name="   ", url="https://x.io")
    with pytest.raises(ValidationError):
        ApplicationCreate(name="x" * 61, url="https://x.io")


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ApplicationCreate(name="Doc", url="https://x.io", extra="nope")  # type: ignore[call-arg]
