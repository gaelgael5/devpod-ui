"""Garde : un deploiement dont le PORTAIL ne fournit pas une variable est refuse.

Les collecteurs gardent leurs variables obligatoires (`${METRICS_URL:?…}`) —
sans cible, ne pas demarrer vaut mieux que pousser dans le vide. Mais l'erreur
remontait de `docker compose`, qui refuse AVANT de creer le conteneur : pas de
conteneur, pas de logs, aucune cause lisible. C'est exactement ce qui s'est
passe sur host-105-1 le 25/08 — `alloy-metrics` en `error`, sortie de logs vide.
"""

from __future__ import annotations

import pytest

from portal.compose import service as svc
from portal.compose.models import ComposeTemplate
from portal.compose.validation import required_vars

_METRICS = (
    "services:\n  alloy-metrics:\n    image: grafana/alloy:v1.5.1\n"
    "    environment:\n"
    "      METRICS_URL: ${METRICS_URL:?METRICS_URL requis}\n"
    "      HOSTNAME: ${HOSTNAME:?HOSTNAME requis}\n"
    "      MODULE: ${MODULE:-devpod}\n"
)


class _Host:
    name = "host-105-1"
    type = "ssh"
    usage = "tests"
    address = "debian@192.168.10.249"


def _tpl(contenu: str = _METRICS) -> ComposeTemplate:
    return ComposeTemplate(
        id="alloy-metrics",
        name="Collecteur de métriques (Alloy)",
        description="",
        tags=[],
        version="1",
        compose_content=contenu,
        parameters=[],
        source="imported",
    )


def _config(monkeypatch: pytest.MonkeyPatch, *, loki: str | None, metrics: str | None) -> None:
    class _Cfg:
        class logs:  # noqa: N801 — mime la forme du modele de config
            enabled = True
            loki_push_url = loki
            metrics_push_url = metrics
            module = "devpod"

    monkeypatch.setattr(svc, "load_global", lambda: _Cfg())


# ─── required_vars ───────────────────────────────────────────────────────────


def test_required_vars_retient_les_formes_sans_repli() -> None:
    assert required_vars(_METRICS) == {"METRICS_URL", "HOSTNAME"}


def test_required_vars_ignore_une_valeur_par_defaut() -> None:
    """`${MODULE:-devpod}` se passe de la variable : l'exiger ferait echouer un
    deploiement parfaitement viable."""
    assert "MODULE" not in required_vars(_METRICS)


def test_required_vars_ignore_les_formes_alternatives() -> None:
    assert required_vars("x: ${A:+alt}\ny: ${B-def}\n") == set()


# ─── _require_injected_vars ──────────────────────────────────────────────────


def test_refuse_quand_la_cible_n_est_pas_configuree(monkeypatch: pytest.MonkeyPatch) -> None:
    _config(monkeypatch, loki="http://loki:3100/p", metrics=None)

    with pytest.raises(svc.ComposeServiceError) as exc:
        svc._require_injected_vars(_tpl(), {}, _Host())

    message = str(exc.value)
    assert "METRICS_URL" in message
    # Le message doit mener a l'ecran qui repare, pas decrire un symptome.
    assert "Logs" in message
    assert "HOSTNAME" not in message  # celui-la EST fourni


def test_accepte_quand_tout_est_fourni(monkeypatch: pytest.MonkeyPatch) -> None:
    _config(monkeypatch, loki="http://loki:3100/p", metrics="http://vm:8428/api/v1/write")

    svc._require_injected_vars(_tpl(), {}, _Host())


def test_une_valeur_saisie_par_l_utilisateur_fait_l_affaire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tant que le template expose METRICS_URL en parametre, une saisie vaut
    injection — on ne casse pas les profils deja remplis."""
    _config(monkeypatch, loki="http://loki:3100/p", metrics=None)

    svc._require_injected_vars(_tpl(), {"METRICS_URL": "http://vm:8428/api/v1/write"}, _Host())


def test_une_valeur_saisie_vide_ne_compte_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    _config(monkeypatch, loki="http://loki:3100/p", metrics=None)

    with pytest.raises(svc.ComposeServiceError):
        svc._require_injected_vars(_tpl(), {"METRICS_URL": "   "}, _Host())


def test_un_service_ordinaire_n_est_pas_concerne(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucune variable du portail : la garde ne doit rien exiger, meme chaine
    d'observabilite eteinte."""

    class _Off:
        class logs:  # noqa: N801
            enabled = False
            loki_push_url = None
            metrics_push_url = None
            module = "devpod"

    monkeypatch.setattr(svc, "load_global", lambda: _Off())

    svc._require_injected_vars(
        _tpl("services:\n  searxng:\n    image: searxng/searxng\n"), {}, _Host()
    )


def test_chaine_eteinte_refuse_le_collecteur(monkeypatch: pytest.MonkeyPatch) -> None:
    """Logs desactives : plus AUCUNE variable injectee, y compris HOSTNAME. Le
    compose echouerait de toute facon — autant le dire avant."""

    class _Off:
        class logs:  # noqa: N801
            enabled = False
            loki_push_url = None
            metrics_push_url = None
            module = "devpod"

    monkeypatch.setattr(svc, "load_global", lambda: _Off())

    with pytest.raises(svc.ComposeServiceError) as exc:
        svc._require_injected_vars(_tpl(), {}, _Host())
    assert "HOSTNAME" in str(exc.value) and "METRICS_URL" in str(exc.value)
