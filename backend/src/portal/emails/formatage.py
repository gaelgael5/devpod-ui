"""Formatage localisé des variables d'email — côté portail, jamais en template.

Les templates reçoivent des chaînes prêtes à afficher : une date localisée, un
montant avec sa devise, un libellé de périodicité. Pas de dépendance à `babel`
ni aux locales système (l'image Docker n'en embarque pas) : deux cultures,
`fr` et `en`, formats écrits ici et testés.
"""

from __future__ import annotations

from datetime import datetime

CULTURES = ("fr", "en")

_MOIS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_MOIS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

#: Symbole devant (en) ou derrière (fr) le montant. Une devise absente
#: s'affiche par son code ISO — jamais un montant nu.
_SYMBOLES = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


def normaliser_culture(culture: str) -> str:
    """`fr`/`en`, repli `fr` (la culture par défaut du portail)."""
    base = (culture or "").strip().lower()[:2]
    return base if base in CULTURES else "fr"


def formater_date(quand: datetime, culture: str) -> str:
    """Date absolue, humaine : « 19 septembre 2026 » / « September 19, 2026 »."""
    if normaliser_culture(culture) == "en":
        return f"{_MOIS_EN[quand.month - 1]} {quand.day}, {quand.year}"
    return f"{quand.day} {_MOIS_FR[quand.month - 1]} {quand.year}"


def formater_montant(amount_minor: int, currency: str, culture: str) -> str:
    """« 12,00 € » / « €12.00 » — le montant en centimes ne sort jamais brut."""
    entier, centimes = divmod(amount_minor, 100)
    code = currency.upper()
    symbole = _SYMBOLES.get(code, code)
    if normaliser_culture(culture) == "en":
        return f"{symbole}{entier}.{centimes:02d}"
    return f"{entier},{centimes:02d} {symbole}"


def periodicite(duration_days: int | None, culture: str) -> str:
    """Libellé de la période de facturation, depuis la durée de l'offre."""
    en = normaliser_culture(culture) == "en"
    if duration_days is None:
        return "period" if en else "période"
    if 28 <= duration_days <= 31:
        return "month" if en else "mois"
    if 360 <= duration_days <= 371:
        return "year" if en else "an"
    return f"{duration_days} days" if en else f"{duration_days} jours"
