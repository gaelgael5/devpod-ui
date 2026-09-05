# backend/tests/test_provisioning_reconciliation.py
"""Garde-fous cloud (ticket 11) : réconciliation trois sources, plafond de
coût, TTL. Deux propriétés structurantes : rien ici ne supprime, et rien ici
n'arrête une machine."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from portal.config.models import HostConfig
from portal.provisioning.azure_inventory import AzureInventaire, InventaireIndisponible
from portal.provisioning.errors import EchecAvantCreation
from portal.provisioning.reconciliation import (
    Ecarts,
    classer_ecarts,
    estimer_cout_eur_mois,
    machines_expirees,
    verifier_plafond,
)


def _host(name: str, cout: float = 0.0, expires: str = "") -> HostConfig:
    return HostConfig(name=name, type="ssh", cost_estimate_eur_month=cout, expires_at=expires)


# ─── Estimation de coût ───────────────────────────────────────────────────────


def test_estimation_grossiere_par_famille() -> None:
    assert estimer_cout_eur_mois("Standard_D4ads_v5") == 152.0
    assert estimer_cout_eur_mois("Standard_B2s_v2") == 30.0


def test_estimation_inconnue_vaut_zero_mais_pas_en_silence() -> None:
    # 0.0 = inconnue ; le log l'accompagne (couvert par le warning structlog).
    assert estimer_cout_eur_mois("Gabarits_Exotiques_9000") == 0.0


# ─── Plafond ──────────────────────────────────────────────────────────────────


def test_plafond_refuse_avant_toute_creation() -> None:
    hosts = [_host("h1", cout=200.0), _host("h2", cout=150.0)]
    with pytest.raises(EchecAvantCreation) as exc:
        verifier_plafond(hosts, 152.0, plafond_eur=400.0)
    assert "rien n'a été créé" in str(exc.value)


def test_plafond_zero_desactive() -> None:
    verifier_plafond([_host("h1", cout=10_000.0)], 10_000.0, plafond_eur=0.0)


def test_sous_le_plafond_ca_passe() -> None:
    verifier_plafond([_host("h1", cout=100.0)], 152.0, plafond_eur=400.0)


# ─── Réconciliation trois sources ────────────────────────────────────────────


def test_les_trois_ecarts_et_le_rattachable() -> None:
    ecarts = classer_ecarts(
        portail={"az-01", "az-fantome"},
        state={"az-01", "az-oubliee"},
        provider={"az-01", "az-oubliee", "az-orpheline"},
    )
    # Orpheline PURE : chez le provider seulement — coûte pour rien.
    assert ecarts.orphelines == ["az-orpheline"]
    # Dans le state mais pas au portail : montée par nous — se RATTACHE,
    # cas distinct de l'orpheline, jamais une destruction.
    assert ecarts.a_rattacher == ["az-oubliee"]
    # Connue du portail, absente chez le provider : le portail ment.
    assert ecarts.fantomes == ["az-fantome"]


def test_panne_provider_ne_rend_pas_le_parc_orphelin() -> None:
    ecarts = classer_ecarts(portail={"az-01"}, state={"az-01"}, provider=None)
    assert ecarts.provider_indisponible is True
    assert ecarts.orphelines == []
    assert ecarts.fantomes == []


def test_panne_du_portail_ne_declenche_rien_de_destructeur() -> None:
    """DoD : base du portail en panne = portail vide = tout paraît orphelin.
    Le modèle Ecarts SIGNALE et ne porte structurellement aucune action —
    c'est le garde-fou : pas de champ d'ordre, pas de suppression possible."""
    ecarts = classer_ecarts(portail=set(), state=set(), provider={"az-01", "az-02"})
    assert ecarts.orphelines == ["az-01", "az-02"]
    champs_action = [c for c in Ecarts.model_fields if "delete" in c or "destroy" in c]
    assert champs_action == []


# ─── TTL ──────────────────────────────────────────────────────────────────────


def test_ttl_depasse_alerte_jamais_arret() -> None:
    hosts = [
        _host("permanente"),
        _host("expiree", expires="2026-01-01T00:00:00+00:00"),
        _host("future", expires="2099-01-01T00:00:00+00:00"),
        _host("illisible", expires="pas-une-date"),
    ]
    maintenant = datetime(2026, 9, 5, tzinfo=UTC)
    assert machines_expirees(hosts, maintenant) == ["expiree", "illisible"]


# ─── Inventaire Azure ─────────────────────────────────────────────────────────


def _arm_transport(resources: list[dict], fail: bool = False) -> httpx.MockTransport:
    def _handle(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("down", request=request)
        if "oauth2" in request.url.path:
            return httpx.Response(200, json={"access_token": "tok"})
        assert "tagName eq 'managed-by'" in dict(request.url.params).get("$filter", "")
        return httpx.Response(200, json={"value": resources})

    return httpx.MockTransport(_handle)


def _inventaire(transport: httpx.MockTransport) -> AzureInventaire:
    return AzureInventaire(
        tenant_id="t",
        client_id="c",
        client_secret="s",
        subscription_id="sub",
        transport=transport,
    )


async def test_inventaire_liste_par_tag_machine() -> None:
    machines = await _inventaire(
        _arm_transport(
            [
                {"tags": {"managed-by": "devflow", "machine": "az-01"}},
                {"tags": {"managed-by": "devflow", "machine": "az-01"}},
                {"tags": {"managed-by": "devflow", "machine": "az-02"}},
                {"tags": {"managed-by": "devflow"}},  # sans tag machine : ignorée
            ]
        )
    ).machines()
    assert machines == {"az-01", "az-02"}


async def test_inventaire_en_panne_est_une_indisponibilite() -> None:
    with pytest.raises(InventaireIndisponible):
        await _inventaire(_arm_transport([], fail=True)).machines()
