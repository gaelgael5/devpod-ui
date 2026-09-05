# backend/tests/test_provisioning_tailnet.py
"""Adhésion au tailnet (ticket 7) : clé à usage unique pré-autorisée, IP CGNAT
comme adresse, désenrôlement idempotent, échec net quand le tailnet manque."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from portal.provisioning.tailnet import TailnetIndisponible, TailnetService


class _FakeApi:
    """Transport httpx simulant api.tailscale.com — enregistre les requêtes."""

    def __init__(self, devices: list[dict[str, Any]] | None = None) -> None:
        self.devices = devices or []
        self.requetes: list[tuple[str, str, dict[str, Any] | None]] = []
        self.deleted: list[str] = []

    def transport(self) -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requetes.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path.endswith("/keys"):
            return httpx.Response(200, json={"key": "tskey-auth-XXXX", "id": "k1"})
        if request.method == "GET" and request.url.path.endswith("/devices"):
            return httpx.Response(200, json={"devices": self.devices})
        if request.method == "DELETE" and "/device/" in request.url.path:
            self.deleted.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})


def _service(api: _FakeApi) -> TailnetService:
    return TailnetService(
        api_key="tskey-api-test",
        tag="tag:workspace-node",
        transport=api.transport(),
    )


async def test_cle_a_usage_unique_preautorisee_taguee_non_ephemere() -> None:
    """La clé qualifie l'enrôlement : usage unique, pré-autorisée, taguée, et
    le NŒUD n'est pas éphémère — un host éteint des jours ne doit pas
    disparaître du tailnet tout seul."""
    api = _FakeApi()
    key = await _service(api).creer_cle_enrolement(hostname="pve2-docker")

    assert key == "tskey-auth-XXXX"
    _method, _path, body = api.requetes[0]
    create = body["capabilities"]["devices"]["create"]
    assert create["reusable"] is False
    assert create["ephemeral"] is False
    assert create["preauthorized"] is True
    assert create["tags"] == ["tag:workspace-node"]
    assert body["expirySeconds"] <= 3600


async def test_ip_du_noeud_rend_l_adresse_cgnat() -> None:
    api = _FakeApi(
        devices=[
            {
                "id": "d1",
                "name": "pve2-docker.tail1234.ts.net",
                "addresses": ["fd7a:115c:a1e0::1", "100.101.102.103"],
            }
        ]
    )
    assert await _service(api).ip_du_noeud("pve2-docker") == "100.101.102.103"
    assert await _service(api).ip_du_noeud("PVE2-DOCKER") == "100.101.102.103"
    assert await _service(api).ip_du_noeud("autre") is None


async def test_desenrolement_supprime_le_bon_noeud_et_reste_idempotent() -> None:
    api = _FakeApi(
        devices=[
            {"id": "d1", "name": "pve2-docker.tail1234.ts.net", "addresses": []},
            {"id": "d2", "name": "autre.tail1234.ts.net", "addresses": []},
        ]
    )
    svc = _service(api)
    assert await svc.desenroler("pve2-docker") is True
    assert api.deleted == ["d1"]
    # Deux destructions de suite : la seconde est un no-op, pas une erreur.
    api.devices = [d for d in api.devices if d["id"] != "d1"]
    assert await svc.desenroler("pve2-docker") is False


async def test_sans_cle_api_echec_net_pas_de_repli() -> None:
    with pytest.raises(TailnetIndisponible):
        TailnetService(api_key="", tag="tag:workspace-node")


async def test_api_en_panne_est_une_indisponibilite() -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    svc = TailnetService(
        api_key="k",
        tag="tag:workspace-node",
        transport=httpx.MockTransport(_down),
    )
    with pytest.raises(TailnetIndisponible):
        await svc.creer_cle_enrolement(hostname="n1")
    with pytest.raises(TailnetIndisponible):
        await svc.desenroler("n1")


def test_tag_invalide_refuse() -> None:
    with pytest.raises(ValueError):
        TailnetService(api_key="k", tag="workspace-node")
