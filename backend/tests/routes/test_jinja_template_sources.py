from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _RecordingClient:
    """Faux httpx.AsyncClient qui enregistre les URLs et sert le toc.txt."""

    def __init__(self, toc_text: str) -> None:
        self.toc_text = toc_text
        self.requested: list[str] = []

    async def get(self, url: str, timeout: float = 5.0, follow_redirects: bool = False):
        self.requested.append(url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = self.toc_text
        return resp


@pytest.mark.parametrize(
    "source",
    ["https://ex.com/jinja/", "https://ex.com/jinja", "https://ex.com/jinja/toc.txt"],
)
async def test_preview_one_source_parses_and_builds_urls(source: str) -> None:
    from portal.routes.jinja_template_sources import _preview_one_source

    toc = (
        "test_host_available.fr.j2 | test_host_available | fr | Message dispo\n"
        "ligne invalide sans pipes\n"
        "bad.j2 | BAD KEY | fr | desc\n"  # key invalide -> skip
    )
    client = _RecordingClient(toc)
    results = await _preview_one_source(client, source)

    assert client.requested == ["https://ex.com/jinja/toc.txt"]
    assert len(results) == 1
    r = results[0]
    assert r["key"] == "test_host_available"
    assert r["culture"] == "fr"
    assert r["description"] == "Message dispo"
    assert r["source_url"] == "https://ex.com/jinja/test_host_available.fr.j2"
    assert r["source_base"] == "https://ex.com/jinja"
