from __future__ import annotations

import pytest

from portal.mcp.connections import BackendUnavailable, open_session


async def test_open_session_unreachable_raises_backend_unavailable() -> None:
    # port fermé / hôte injoignable → BackendUnavailable, pas une exception brute
    with pytest.raises(BackendUnavailable):
        async with open_session("http://127.0.0.1:1/mcp", timeout_s=2.0):
            pass
