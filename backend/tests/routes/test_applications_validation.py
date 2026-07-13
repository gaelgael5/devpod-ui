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


# ── extract_icon_hrefs (probe favicon) ────────────────────────────────────────


def test_extract_icon_hrefs_basic() -> None:
    from portal.routes.applications import extract_icon_hrefs

    html = '<head><link rel="icon" type="image/svg+xml" href="/favicon.svg" /></head>'
    assert extract_icon_hrefs(html) == ["/favicon.svg"]


def test_extract_icon_hrefs_variants_and_order() -> None:
    from portal.routes.applications import extract_icon_hrefs

    html = """
    <link href="/a.png" rel="apple-touch-icon">
    <LINK REL='SHORTCUT ICON' HREF='/b.ico'>
    <link rel="stylesheet" href="/style.css">
    <link rel="icon" href="https://cdn.io/c.svg"/>
    """
    assert extract_icon_hrefs(html) == ["/a.png", "/b.ico", "https://cdn.io/c.svg"]


def test_extract_icon_hrefs_ignores_no_href_and_non_icon() -> None:
    from portal.routes.applications import extract_icon_hrefs

    html = '<link rel="icon"><link rel="preload" href="/x.js"><a href="/y">y</a>'
    assert extract_icon_hrefs(html) == []
