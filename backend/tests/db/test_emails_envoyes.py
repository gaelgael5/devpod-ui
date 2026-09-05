"""Journal des emails du cycle contre le vrai schéma (fiche 6fdfdaab).

Ce qui se joue : un épisode = un email (la contrainte tranche à l'écriture),
un destinataire inconnu = un refus journalisé, un Listmonk en panne = une
ligne `echec` visible — et jamais une transition d'abonnement cassée.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import insert, select

from portal.billing.subscriptions import Subscription
from portal.config.models import (
    AuthConfig,
    GlobalConfig,
    ListmonkConfig,
    OidcConfig,
    ServerConfig,
)
from portal.db.tables import emails_envoyes, offers, subscriptions, users
from portal.emails.listmonk_tx import ListmonkIndisponible
from portal.emails.service import envoyer_email_cycle

MAINTENANT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


class _ClientFactice:
    def __init__(self, casse: bool = False) -> None:
        self.casse = casse
        self.envois: list[tuple[str, str, dict[str, Any]]] = []

    async def envoyer(self, *, template: str, email: str, data: dict[str, Any]) -> None:
        if self.casse:
            raise ListmonkIndisponible("instance injoignable : down")
        self.envois.append((template, email, data))


@pytest.fixture(autouse=True)
def _listmonk_active(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url="https://dev.yoops.org"),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        listmonk=ListmonkConfig(enabled=True, url="http://listmonk:9000", apikey_secret="lm"),
    )
    monkeypatch.setattr("portal.config.store.load_global", lambda *a, **k: cfg)


async def _seed(
    conn, *, email: str = "alice@example.org", culture: str = "en"
) -> Subscription:
    await conn.execute(
        insert(users).values(
            login="alice",
            version="1",
            secret_ns=str(uuid.uuid4()),
            default_ide="openvscode",
            default_idle_timeout="2h",
            harpocrate_api_key="",
            email=email,
            culture=culture,
            display_name="Alice",
        )
    )
    await conn.execute(insert(offers).values(slug="standard", hosting_type="dedie"))
    sub_id = str(uuid.uuid4())
    await conn.execute(
        insert(subscriptions).values(
            id=sub_id,
            login="alice",
            offer_slug="standard",
            state="essai",
            country_code="FR",
            currency="EUR",
            amount_minor=1200,
        )
    )
    return Subscription(
        id=sub_id,
        login="alice",
        offer_slug="standard",
        state="essai",
        country_code="FR",
        currency="EUR",
        amount_minor=1200,
        trial_end=datetime(2026, 9, 19, tzinfo=UTC),
    )


async def _lignes(conn) -> list[dict[str, Any]]:
    return [dict(r) for r in (await conn.execute(select(emails_envoyes))).mappings().all()]


async def test_un_episode_un_email_et_le_payload_est_fige(db_conn) -> None:
    abonnement = await _seed(db_conn)
    client = _ClientFactice()

    premier = await envoyer_email_cycle(
        "debut_essai",
        abonnement,
        provider_event_id="evt_1",
        conn=db_conn,
        maintenant=MAINTENANT,
        client=client,
    )
    rejeu = await envoyer_email_cycle(
        "debut_essai",
        abonnement,
        provider_event_id="evt_1",
        conn=db_conn,
        maintenant=MAINTENANT,
        client=client,
    )

    assert premier is True
    assert rejeu is False  # webhook rejoué : l'épisode a déjà son email
    assert len(client.envois) == 1
    template, email, data = client.envois[0]
    assert template == "abonnement-debut-essai-en"  # la culture route le template
    assert email == "alice@example.org"

    lignes = await _lignes(db_conn)
    assert len(lignes) == 1
    assert lignes[0]["statut"] == "envoye"
    # Le payload est FIGÉ : la date annoncée est prouvable après coup.
    assert lignes[0]["data"]["essai_fin_date"] == "September 19, 2026"
    assert lignes[0]["data"] == data


async def test_sans_email_refus_journalise_jamais_d_envoi_a_vide(db_conn) -> None:
    abonnement = await _seed(db_conn, email="")
    client = _ClientFactice()

    parti = await envoyer_email_cycle(
        "resiliation",
        abonnement,
        provider_event_id="evt_2",
        conn=db_conn,
        maintenant=MAINTENANT,
        client=client,
    )

    assert parti is False
    assert client.envois == []
    (ligne,) = await _lignes(db_conn)
    assert ligne["statut"] == "echec"
    assert "email du compte inconnu" in ligne["erreur"]


async def test_listmonk_en_panne_echec_visible_pas_d_exception(db_conn) -> None:
    abonnement = await _seed(db_conn)

    parti = await envoyer_email_cycle(
        "echec_paiement",
        abonnement,
        provider_event_id="evt_3",
        conn=db_conn,
        maintenant=MAINTENANT,
        client=_ClientFactice(casse=True),
    )

    assert parti is False  # et surtout : rien n'a levé
    (ligne,) = await _lignes(db_conn)
    assert ligne["statut"] == "echec"
    assert "injoignable" in ligne["erreur"]


async def test_deux_renouvellements_font_deux_recus(db_conn) -> None:
    abonnement = await _seed(db_conn)
    client = _ClientFactice()
    for evt in ("evt_a", "evt_b"):
        assert await envoyer_email_cycle(
            "renouvellement",
            abonnement,
            provider_event_id=evt,
            conn=db_conn,
            maintenant=MAINTENANT,
            client=client,
        )
    assert len(client.envois) == 2  # épisodes distincts = reçus distincts
