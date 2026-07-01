from __future__ import annotations

import pytest

from portal.routes._sources_util import split_toc_url


@pytest.mark.parametrize(
    "source, expected",
    [
        ("https://ex.com/jinja/", ("https://ex.com/jinja/toc.txt", "https://ex.com/jinja")),
        ("https://ex.com/jinja", ("https://ex.com/jinja/toc.txt", "https://ex.com/jinja")),
        ("https://ex.com/jinja/toc.txt", ("https://ex.com/jinja/toc.txt", "https://ex.com/jinja")),
    ],
)
def test_split_toc_url(source: str, expected: tuple[str, str]) -> None:
    assert split_toc_url(source) == expected
