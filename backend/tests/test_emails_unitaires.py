# backend/tests/test_emails_unitaires.py
"""Emails du cycle (fiche 6fdfdaab) — parties pures : formatage localisé,
complétude des templates, composition du payload, client Listmonk."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from portal.billing.config import PolitiqueRetention
from portal.billing.models import Offer
from portal.billing.subscriptions import Subscription
from portal.emails.formatage import (
    formater_date,
    formater_montant,
    normaliser_culture,
    periodicite,
)
from portal.emails.listmonk_tx import (
    ListmonkIndisponible,
    ListmonkTxClient,
    TemplateAbsent,
)
from portal.emails.service import KINDS_AVEC_EMAIL, composer_payload
from portal.emails.templates import MESSAGES, TEMPLATES, nom_template

MAINTENANT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


# ─── Formatage ────────────────────────────────────────────────────────────────


def test_dates_localisees() -> None:
    quand = datetime(2026, 9, 19, tzinfo=UTC)
    assert formater_date(quand, "fr") == "19 septembre 2026"
    assert formater_date(quand, "en") == "September 19, 2026"


def test_montants_localises_jamais_en_centimes() -> None:
    assert formater_montant(1200, "EUR", "fr") == "12,00 €"
    assert formater_montant(1200, "EUR", "en") == "€12.00"
    assert formater_montant(999, "USD", "en") == "$9.99"
    # Devise inconnue : le code ISO, jamais un montant nu.
    assert formater_montant(500, "SEK", "fr") == "5,00 SEK"


def test_culture_inconnue_replie_sur_fr() -> None:
    assert normaliser_culture("de-DE") == "fr"
    assert normaliser_culture("EN-us") == "en"
    assert normaliser_culture("") == "fr"


def test_periodicite() -> None:
    assert periodicite(30, "fr") == "mois"
    assert periodicite(365, "en") == "year"
    assert periodicite(90, "fr") == "90 jours"
    assert periodicite(None, "en") == "period"


# ─── Templates : complétude et contrat de variables ──────────────────────────


def test_les_douze_templates_existent() -> None:
    assert {(m, c) for m in MESSAGES for c in ("fr", "en")} == set(TEMPLATES)
    for template in TEMPLATES.values():
        assert template.sujet.strip()
        assert template.corps.strip()


def test_noms_de_templates_stables() -> None:
    """Le nom est le contrat portail ↔ Listmonk : il ne bouge pas."""
    assert nom_template("debut_essai", "fr") == "abonnement-debut-essai-fr"
    assert nom_template("avertissement_destruction", "en") == (
        "abonnement-avertissement-destruction-en"
    )


def test_chaque_template_reste_dans_le_vocabulaire_du_payload() -> None:
    """Toute variable citée par un template doit être produite par
    `composer_payload` pour son message — un template qui invente une variable
    rend un trou dans l'email, silencieusement."""
    import re

    for (message, culture), template in TEMPLATES.items():
        payload = _payload(message)
        variables = set(re.findall(r"\.Tx\.Data\.([a-z_]+)", template.sujet + template.corps))
        manquantes = variables - set(payload)
        assert not manquantes, f"{message}/{culture} : variables absentes {manquantes}"


def test_distinction_arrete_supprime_tenue_partout() -> None:
    """La phrase importante des fins de vie : arrêté n'est PAS supprimé."""
    assert "PAS supprimés" in TEMPLATES[("echec_paiement", "fr")].corps
    assert "NOT deleted" in TEMPLATES[("echec_paiement", "en")].corps
    assert "PAS supprimés" in TEMPLATES[("resiliation", "fr")].corps
    assert "résilier n'est pas supprimer son compte" in TEMPLATES[("resiliation", "fr")].corps


# ─── Payload ──────────────────────────────────────────────────────────────────


def _abonnement(**over: object) -> Subscription:
    base: dict[str, object] = {
        "id": "8c9e6f1a-0000-4000-8000-000000000001",
        "login": "alice",
        "offer_slug": "standard",
        "state": "essai",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 1200,
    }
    base.update(over)
    return Subscription.model_validate(base)


def _offre(**over: object) -> Offer:
    base: dict[str, object] = {
        "slug": "standard",
        "label": "Standard",
        "titles": {"fr": "Forfait Standard", "en": "Standard plan"},
        "duration_days": 30,
        "tacite_reconduction": True,
    }
    base.update(over)
    return Offer.model_validate(base)


def _payload(kind: str, **over: object) -> dict[str, object]:
    defauts: dict[str, object] = {
        "kind": kind,
        "abonnement": _abonnement(
            trial_end=datetime(2026, 9, 19, tzinfo=UTC),
            ends_at=datetime(2026, 10, 5, tzinfo=UTC),
            current_period_end=datetime(2026, 10, 5, tzinfo=UTC),
            state="echec_paiement" if kind == "avertissement_destruction" else "essai",
            state_changed_at=MAINTENANT,
        ),
        "offre": _offre(),
        "culture": "fr",
        "prenom_ou_login": "Alice",
        "base_url": "https://dev.yoops.org/",
        "politique": PolitiqueRetention(),
        "maintenant": MAINTENANT,
        "produit": "devflow",
        "email_support": "",
        "machines": ["ded-104"],
    }
    defauts.update(over)
    return composer_payload(**defauts)  # type: ignore[arg-type]


def test_payload_commun_et_liens() -> None:
    data = _payload("debut_essai")
    assert data["offre_label"] == "Forfait Standard"
    assert data["prix_formate"] == "12,00 €"
    assert data["lien_abonnement"] == "https://dev.yoops.org/abonnement"
    assert data["lien_offres"] == "https://dev.yoops.org/forfaits"


def test_payload_essai() -> None:
    data = _payload("debut_essai")
    assert data["essai_fin_date"] == "19 septembre 2026"
    assert data["essai_duree_jours"] == 30
    assert data["tacite_reconduction"] is True


def test_payload_echec_paiement_dates_limites() -> None:
    data = _payload("echec_paiement")
    # 05/09 + 14 jours de rétention = 19/09, calculé à l'envoi et figé.
    assert data["date_limite_recuperation"] == "19 septembre 2026"
    assert data["recuperation_jours"] == 14
    assert data["avertissement_avant_destruction"] is True


def test_payload_resiliation_fin_acces() -> None:
    data = _payload("resiliation")
    assert data["fin_acces_date"] == "5 octobre 2026"  # ends_at futur : accès payé
    assert data["date_limite_recuperation"] == "5 octobre 2026"  # 05/09 + 30 j
    sans_acces = _payload(
        "resiliation",
        abonnement=_abonnement(ends_at=datetime(2026, 9, 1, tzinfo=UTC)),
    )
    assert sans_acces["fin_acces_date"] == ""  # résiliation immédiate


def test_payload_avertissement_destruction() -> None:
    data = _payload("avertissement_destruction")
    assert data["etat"] == "echec_paiement"
    assert data["destruction_date"] == "19 septembre 2026"  # state_changed + 14 j
    assert data["destruction_dans_jours"] == 14
    assert data["machines"] == ["ded-104"]


def test_offre_absente_replie_sur_le_slug() -> None:
    data = _payload("debut_essai", offre=None)
    assert data["offre_label"] == "standard"


def test_kinds_sans_email() -> None:
    assert "remboursement" not in KINDS_AVEC_EMAIL
    assert "litige_ouvert" not in KINDS_AVEC_EMAIL


# ─── Client Listmonk ──────────────────────────────────────────────────────────


class _FakeListmonk:
    def __init__(self, templates: dict[str, int] | None = None) -> None:
        self.templates = templates if templates is not None else {}
        self.envois: list[dict[str, object]] = []
        self.crees: list[str] = []
        self.majs: list[str] = []
        self._prochain_id = 100

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token api_user:secret"
        if request.method == "GET" and request.url.path == "/api/templates":
            data = [{"id": i, "name": n} for n, i in self.templates.items()]
            return httpx.Response(200, json={"data": data})
        if request.method == "POST" and request.url.path == "/api/templates":
            corps = json.loads(request.content)
            self.templates[corps["name"]] = self._prochain_id
            self.crees.append(corps["name"])
            self._prochain_id += 1
            return httpx.Response(200, json={"data": {"id": self._prochain_id - 1}})
        if request.method == "PUT" and request.url.path.startswith("/api/templates/"):
            self.majs.append(json.loads(request.content)["name"])
            return httpx.Response(200, json={"data": {}})
        if request.method == "POST" and request.url.path == "/api/tx":
            self.envois.append(json.loads(request.content))
            return httpx.Response(200, json={"data": True})
        return httpx.Response(404, json={"message": "not found"})


def _client(fake: _FakeListmonk) -> ListmonkTxClient:
    return ListmonkTxClient(
        url="http://listmonk:9000/",
        credential="api_user:secret",
        transport=fake.transport(),
    )


async def test_envoi_resout_le_template_et_poste_le_payload() -> None:
    fake = _FakeListmonk(templates={"abonnement-debut-essai-fr": 7})
    await _client(fake).envoyer(
        template="abonnement-debut-essai-fr",
        email="alice@example.org",
        data={"offre_label": "Standard"},
    )
    envoi = fake.envois[0]
    assert envoi["template_id"] == 7
    assert envoi["subscriber_email"] == "alice@example.org"
    assert envoi["data"] == {"offre_label": "Standard"}


async def test_template_absent_dit_quoi_faire() -> None:
    fake = _FakeListmonk()
    with pytest.raises(TemplateAbsent) as exc:
        await _client(fake).envoyer(template="abonnement-x-fr", email="a@b.c", data={})
    assert "sync-templates" in str(exc.value)


async def test_synchro_cree_puis_met_a_jour() -> None:
    fake = _FakeListmonk()
    client = _client(fake)
    assert await client.synchroniser_template(nom="t1", sujet="s", corps="c") == "cree"
    assert await client.synchroniser_template(nom="t1", sujet="s2", corps="c2") == "mis_a_jour"
    assert fake.crees == ["t1"]
    assert fake.majs == ["t1"]


async def test_instance_en_panne_est_une_indisponibilite() -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    client = ListmonkTxClient(
        url="http://listmonk:9000",
        credential="x",
        transport=httpx.MockTransport(_down),
    )
    with pytest.raises(ListmonkIndisponible):
        await client.envoyer(template="t", email="a@b.c", data={})
