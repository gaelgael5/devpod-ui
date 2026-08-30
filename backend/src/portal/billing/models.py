"""Modèles du socle des forfaits : pays, fiscalité, catalogue d'offres.

Cadrage du 27/08/2026. Périmètre initial : la France seule, en mode de taxe
`manuel`. Le mode `automatique` (Stripe Tax) est modélisé mais **non exercé** —
il n'y a pas encore de compte Stripe, donc rien à déclarer testé de ce côté.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ISO-3166-1 alpha-2 et ISO-4217 : deux et trois lettres majuscules. Bornés
# plutôt que libres — un code mal saisi ne se voit qu'au moment où un client
# ne trouve pas son pays.
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

TaxMode = Literal["automatique", "manuel"]
HostingType = Literal["dedie", "mutualise"]
ProviderKind = Literal["stripe"]


class StripeConfig(BaseModel):
    """Configuration NON SECRÈTE d'un provider Stripe.

    La clé API n'est pas ici : elle vit dans la table des secrets, référencée par
    `PaymentProvider.secret_slug`. Ce modèle ne porte que ce qui peut figurer en
    clair dans une table et dans un log.

    `extra="forbid"` : une clé inconnue est refusée à la saisie, pas découverte
    au premier paiement.
    """

    model_config = ConfigDict(extra="forbid")

    # Compte marchand (`acct_…`) — vide tant que le compte n'est pas ouvert.
    account_id: str = ""
    # Slug du secret portant le secret de signature des webhooks (`whsec_…`).
    # Comme la clé API : une référence, jamais la valeur.
    webhook_secret_slug: str = ""


#: Configuration attendue selon le `kind` du provider. Ajouter un canal de
#: paiement, c'est ajouter un modèle ici — et le validateur refusera tout de
#: suite une config qui n'a pas la forme du canal déclaré.
PROVIDER_CONFIG_MODELS: dict[str, type[BaseModel]] = {"stripe": StripeConfig}


class PaymentProvider(BaseModel):
    """Canal de paiement.

    `slug` identifie l'INSTANCE, `kind` dit quel adaptateur la pilote. Les deux
    sont distincts pour qu'un second compte Stripe — test, ou autre entité
    juridique — coexiste sans dupliquer le code de l'adaptateur.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    kind: ProviderKind
    label: str
    tax_mode: TaxMode = "manuel"
    enabled: bool = True
    config: dict[str, object] = Field(default_factory=dict)
    # Référence vers la table des secrets. JAMAIS la clé elle-même.
    secret_slug: str = ""

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError(f"slug {v!r} invalide : ^[a-z0-9][a-z0-9-]{{0,62}}$")
        return v

    @model_validator(mode="after")
    def _config_conforme_au_kind(self) -> PaymentProvider:
        modele = PROVIDER_CONFIG_MODELS.get(self.kind)
        if modele is not None:
            # Valide sans remplacer : la valeur stockée reste le dict brut, mais
            # une clé inconnue ou mal typée est refusée ici.
            modele.model_validate(self.config)
        return self


class Country(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    enabled: bool = True

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _COUNTRY_RE.fullmatch(v):
            raise ValueError(f"code pays {v!r} invalide : deux lettres majuscules (ISO-3166-1)")
        return v


class Currency(BaseModel):
    """Devise acceptee par l'application.

    Le jeu est GLOBAL, pas rattache a un pays : ce que la plateforme sait
    encaisser ne depend pas de l'endroit ou vit l'acheteur. Une seule devise
    porte `is_default` — celle qu'on propose faute de mieux.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    enabled: bool = True
    is_default: bool = False

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _CURRENCY_RE.fullmatch(v):
            raise ValueError(f"devise {v!r} invalide : trois lettres majuscules (ISO-4217)")
        return v


class CountryProvider(BaseModel):
    """Rattachement d'un canal de paiement à un pays, avec sa priorité.

    Un pays peut avoir plusieurs canaux — un défaillant ne doit pas emporter la
    vente. `priority` croissante donne l'ordre d'essai ; c'est un ordre, pas un
    poids.
    """

    model_config = ConfigDict(extra="forbid")

    country_code: str
    provider_slug: str
    priority: int = 0

    @field_validator("country_code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _COUNTRY_RE.fullmatch(v):
            raise ValueError(f"code pays {v!r} invalide : deux lettres majuscules (ISO-3166-1)")
        return v


class TaxRate(BaseModel):
    """Taux de taxe, en mode `manuel` uniquement.

    HISTORISÉ : `valid_from` / `valid_to` plutôt qu'un taux mutable. Une facture
    émise l'an dernier doit rester reproductible avec le taux de l'époque —
    écraser le taux ferait perdre sa valeur probante à la facturation au premier
    changement de TVA.
    """

    model_config = ConfigDict(extra="forbid")

    # Identité en base. `None` = pas encore persisté. Un taux ne s'écrase pas,
    # il se clôt puis se remplace : l'API a donc besoin de le désigner.
    id: int | None = None
    country_code: str
    # Vide = tout le pays. Conservé pour un futur pays à taux régionaux.
    region: str = ""
    # 0.2000 = 20 %. Decimal et non float : sur de la facturation, l'erreur
    # d'arrondi d'un binaire flottant se découvre au rapprochement bancaire.
    rate: Decimal
    label: str
    valid_from: date
    valid_to: date | None = None

    @field_validator("rate")
    @classmethod
    def _rate(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("rate: un taux ne peut pas être négatif")
        return v

    @model_validator(mode="after")
    def _periode(self) -> TaxRate:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to doit être postérieur à valid_from")
        return self

    def couvre(self, jour: date) -> bool:
        """Ce taux s'applique-t-il à cette date d'émission ?"""
        if jour < self.valid_from:
            return False
        return self.valid_to is None or jour < self.valid_to


class OfferPrice(BaseModel):
    """Prix d'une offre dans UNE devise.

    `amount_minor` est un entier en unités mineures (centimes) — jamais un
    flottant. Son sens dépend du `tax_mode` du provider : HT en `automatique`
    (le provider ajoute la taxe), TTC en `manuel` (on l'a déjà calculée).
    """

    model_config = ConfigDict(extra="forbid")

    currency: str
    amount_minor: int
    provider_price_id: str = ""

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        if not _CURRENCY_RE.fullmatch(v):
            raise ValueError(f"devise {v!r} invalide : trois lettres majuscules (ISO-4217)")
        return v

    @field_validator("amount_minor")
    @classmethod
    def _amount(cls, v: int) -> int:
        if v < 0:
            raise ValueError("amount_minor: un prix ne peut pas être négatif")
        return v


class Offer(BaseModel):
    """Offre d'abonnement.

    Deux noms, et ils ne jouent pas le même rôle :

    - `label` est un **nom court, non traduit** — « Standard », « Max ». Il vit
      dans les tableaux d'administration, les badges, les journaux. Le traduire
      n'aurait pas de sens : c'est le nom du produit.
    - `titles` est le **titre montré au client**, lui traduit (`{langue: texte}`),
      au même titre que `descriptions`.

    Quotas nullables — `None` = illimité, et les deux sont indépendants.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    label: str = ""
    titles: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)
    hosting_type: HostingType = "mutualise"
    # `max_workspaces` est la CAPACITÉ DU HOST, pas un quota individuel toutes
    # machines confondues — l'owner la partage avec ses invités.
    max_workspaces: int | None = None
    max_hosts_dedies: int | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    provider_slug: str | None = None
    published: bool = False
    prices: list[OfferPrice] = Field(default_factory=list)
    # Sens du montant saisi. Explicite plutot que deduit du mode de taxe du
    # canal : l'administrateur doit pouvoir dire ce qu'il tape, et une offre
    # peut changer de canal sans que ses prix changent de nature.
    prices_include_tax: bool = False
    # Devises sans prix propre : on les derive du prix par defaut plutot que de
    # ne rien proposer. Le taux n'est PAS un taux de change — c'est une
    # majoration commerciale, appliquee au montant de la devise par defaut.
    auto_currencies: bool = False
    #: 1 = pas de majoration. Decimal, jamais un flottant : c'est de l'argent.
    currency_markup: Decimal = Decimal("1")
    # Offre gratuite : un forfait de bienvenue, pour essayer le produit. Elle
    # n'a AUCUN prix — c'est un drapeau et non l'absence de tarif, parce qu'une
    # offre payante dont on a oublie le prix est une erreur de saisie, pas une
    # offre gratuite. Les deux se confondraient sans lui.
    is_free: bool = False
    # Duree du forfait, EN JOURS. Tout forfait est borne : l'essai parce qu'il
    # doit finir, le payant parce qu'un abonnement sans terme ne se facture pas.
    # `None` = pas encore renseignee — l'offre reste un brouillon, la
    # publication l'exige (cf. `pricing.publiable`).
    duration_days: int | None = None

    @field_validator("currency_markup")
    @classmethod
    def _markup(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("currency_markup : une majoration vaut 1 ou davantage, jamais zéro")
        return v

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError(f"slug {v!r} invalide : ^[a-z0-9][a-z0-9-]{{0,62}}$")
        return v

    @field_validator("max_workspaces", "max_hosts_dedies")
    @classmethod
    def _quota(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("un quota vaut None (illimité) ou un entier strictement positif")
        return v

    @field_validator("duration_days")
    @classmethod
    def _duree(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("duration_days : un forfait dure au moins un jour")
        return v

    @model_validator(mode="after")
    def _gratuit_sans_prix(self) -> Offer:
        """Gratuit ET tarifé n'a pas de sens.

        Laisser coexister les deux, c'est laisser le point d'encaissement
        choisir : l'un des deux serait applique, et personne ne saurait lequel.
        """
        if self.is_free and self.prices:
            raise ValueError(
                "offre gratuite : elle ne peut pas porter de prix "
                f"({', '.join(p.currency for p in self.prices)})"
            )
        return self

    @model_validator(mode="after")
    def _pas_deux_prix_dans_la_meme_devise(self) -> Offer:
        devises = [p.currency for p in self.prices]
        if len(devises) != len(set(devises)):
            doublons = sorted({d for d in devises if devises.count(d) > 1})
            raise ValueError(f"deux prix pour la même devise : {', '.join(doublons)}")
        return self

    def prix(self, currency: str) -> OfferPrice | None:
        return next((p for p in self.prices if p.currency == currency), None)
