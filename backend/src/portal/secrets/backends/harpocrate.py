from __future__ import annotations

import httpx


class HarpocrateBackend:
    """Client HTTP synchrone vers Harpocrate. API key transmise en header X-Api-Key."""

    base_path: str

    def __init__(
        self,
        url: str,
        api_key: str,
        base_path: str = "devpod",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._api_key = api_key
        self.base_path = base_path
        self._client = http_client or httpx.Client()

    def get(self, full_path: str) -> str:
        response = self._client.get(
            f"{self._url}/secrets/{full_path}",
            headers={"X-Api-Key": self._api_key},
        )
        if response.status_code == 404:
            raise KeyError(f"Secret not found at {full_path!r}: {response.text}")
        response.raise_for_status()
        return str(response.json()["value"])
