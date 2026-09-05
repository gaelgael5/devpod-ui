"""Resync des collecteurs déployés (env LOKI_URL/METRICS_URL figés au déploiement).

Sans resync, un changement de `loki_push_url` / `metrics_push_url` (IP DHCP qui
dérive) ou un bump du template ne touche jamais les collecteurs existants : ils
poussent dans le vide jusqu'à un redéploiement manuel. Le resync réécrit .env +
fichiers + compose sur chaque host et force la recréation, best-effort.

La sélection se fait sur le CONTENU du template — référence-t-il une variable
injectée qui dérive ? — et non sur un identifiant codé en dur : un collecteur
importé depuis la galerie en bénéficie sans que le portail ait à le connaître.
"""

from __future__ import annotations

from typing import Any

import pytest

from portal.compose import service as svc
from portal.compose.models import ComposeDeployment, ComposeTemplate


def _tpl() -> ComposeTemplate:
    return ComposeTemplate(
        id="alloy-collector",
        name="Collecteur de logs (Alloy)",
        description="",
        tags=["builtin"],
        version="3",
        # C'est cette reference qui rend le template resynchronisable.
        compose_content=(
            "services:\n  alloy:\n    image: grafana/alloy:v1.5.1\n"
            "    environment:\n      LOKI_URL: ${LOKI_URL:?LOKI_URL requis}\n"
        ),
        parameters=[],
        source="builtin",
        extra_files={"config.alloy": "// v3 journald=/var/log/journal"},
    )


def _dep(uid: str, node: str) -> ComposeDeployment:
    return ComposeDeployment(
        uid=uid,
        id="alloy-collector",
        template_id="alloy-collector",
        template_version="2",
        node_id=node,
        owner_login="admin",
        env_values={},
        host_ports=[],
        status="running",
    )


class _Host:
    def __init__(self, name: str) -> None:
        self.name = name
        self.type = "ssh"
        self.usage = "autres"
        self.address = f"debian@{name}.lan"
        self.host_cert_slug = f"host.{name}.cert"


class _Cfg:
    def __init__(self, hosts: list[_Host], push_url: str | None) -> None:
        self.hosts = hosts

        class _Logs:
            enabled = bool(push_url)
            loki_push_url = push_url
            metrics_push_url = None
            module = "devpod"

        self.logs = _Logs()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {"writes": [], "cmds": [], "versions": [], "fail_hosts": set()}

    async def _get_template(conn: Any, tpl_id: str) -> ComposeTemplate | None:
        return _tpl()

    async def _list(conn: Any, *, owner_login: str | None) -> list[ComposeDeployment]:
        return [_dep("u1", "workflow"), _dep("u2", "node1")]

    async def _write(host: Any, path: str, content: str) -> None:
        if host.name in calls["fail_hosts"]:
            raise RuntimeError("host down")
        calls["writes"].append((host.name, path, content))

    async def _run(host: Any, command: str, timeout: float = 300.0) -> tuple[int, str, str]:
        if host.name in calls["fail_hosts"]:
            raise RuntimeError("host down")
        calls["cmds"].append((host.name, command))
        return 0, "", ""

    async def _update_version(conn: Any, uid: str, version: str) -> None:
        calls["versions"].append((uid, version))

    async def _load_user(login: str) -> Any:
        class _U:
            secret_ns = "ns-1"

        return _U()

    monkeypatch.setattr(svc, "get_template", _get_template)
    monkeypatch.setattr(svc, "list_deployments", _list)
    monkeypatch.setattr(svc, "write_host_file", _write)
    monkeypatch.setattr(svc, "run_host_command", _run)
    monkeypatch.setattr(svc, "update_deployment_template_version", _update_version)
    monkeypatch.setattr(svc, "load_user", _load_user)
    monkeypatch.setattr(
        svc, "load_global", lambda: _Cfg([_Host("workflow"), _Host("node1")], "http://loki:3100/p")
    )
    return calls


async def test_resync_rewrites_env_and_files_and_recreates(wired: dict[str, Any]) -> None:
    res = await svc.resync_collector_deployments(conn=object())

    assert res["synced"] == ["u1", "u2"]
    # .env réécrit avec le LOKI_URL courant + fichiers du template v3
    env_writes = [w for w in wired["writes"] if w[1].endswith("/.env")]
    assert len(env_writes) == 2
    assert all("http://loki:3100/p" in w[2] for w in env_writes)
    cfg_writes = [w for w in wired["writes"] if w[1].endswith("/config.alloy")]
    assert all("v3 journald" in w[2] for w in cfg_writes)
    # Recréation forcée (fichier bind-mount changé ≠ recreate automatique)
    assert all("up -d --force-recreate" in c for _h, c in wired["cmds"])
    # Version du template tracée sur la row
    assert wired["versions"] == [("u1", "3"), ("u2", "3")]


async def test_resync_best_effort_per_host(wired: dict[str, Any]) -> None:
    wired["fail_hosts"].add("workflow")
    res = await svc.resync_collector_deployments(conn=object())
    assert res["failed"] == ["u1"]
    assert res["synced"] == ["u2"]


async def test_resync_noop_when_logs_disabled(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "load_global", lambda: _Cfg([_Host("workflow")], None))
    res = await svc.resync_collector_deployments(conn=object())
    assert res == {"synced": [], "failed": [], "skipped": ["u1", "u2"]}
    assert wired["writes"] == []


def _tpl_metrics() -> ComposeTemplate:
    """Collecteur de metriques importe depuis la galerie — le portail ne le
    connait pas par son id, seulement par la variable qu'il reference."""
    return ComposeTemplate(
        id="alloy-metrics",
        name="Collecteur de metriques (Alloy)",
        description="",
        tags=["observabilité", "métriques"],
        version="1",
        compose_content=(
            "services:\n  alloy:\n    image: grafana/alloy:v1.5.1\n"
            "    environment:\n      METRICS_URL: ${METRICS_URL:?METRICS_URL requis}\n"
        ),
        parameters=[],
        source="imported",
        extra_files={"config.alloy": "// metrics"},
    )


def _tpl_ordinaire() -> ComposeTemplate:
    """Service utilisateur : aucune variable du portail, donc pas de resync."""
    return ComposeTemplate(
        id="searxng",
        name="SearXNG",
        description="",
        tags=[],
        version="1",
        compose_content="services:\n  searxng:\n    image: searxng/searxng\n",
        parameters=[],
        source="imported",
        extra_files={},
    )


def _dep_de(uid: str, node: str, template_id: str) -> ComposeDeployment:
    return ComposeDeployment(
        uid=uid,
        id=template_id,
        template_id=template_id,
        template_version="1",
        node_id=node,
        owner_login="admin",
        env_values={},
        host_ports=[],
        status="running",
    )


def _cabler(
    monkeypatch: pytest.MonkeyPatch,
    templates: dict[str, ComposeTemplate],
    deployments: list[ComposeDeployment],
    *,
    loki: str | None,
    metrics: str | None,
) -> dict[str, Any]:
    calls: dict[str, Any] = {"writes": [], "cmds": []}

    async def _get_template(conn: Any, tpl_id: str) -> ComposeTemplate | None:
        return templates.get(tpl_id)

    async def _list(conn: Any, *, owner_login: str | None) -> list[ComposeDeployment]:
        return deployments

    async def _write(host: Any, path: str, content: str) -> None:
        calls["writes"].append((host.name, path, content))

    async def _run(host: Any, command: str, timeout: float = 300.0) -> tuple[int, str, str]:
        calls["cmds"].append((host.name, command))
        return 0, "", ""

    async def _noop_version(conn: Any, uid: str, version: str) -> None:
        return None

    async def _load_user(login: str) -> Any:
        class _U:
            secret_ns = "ns-1"

        return _U()

    class _Cfg2:
        hosts = [_Host("node1")]

        class logs:  # noqa: N801 — mime la forme du modele de config
            enabled = True
            loki_push_url = loki
            metrics_push_url = metrics
            module = "devpod"

    monkeypatch.setattr(svc, "get_template", _get_template)
    monkeypatch.setattr(svc, "list_deployments", _list)
    monkeypatch.setattr(svc, "write_host_file", _write)
    monkeypatch.setattr(svc, "run_host_command", _run)
    monkeypatch.setattr(svc, "update_deployment_template_version", _noop_version)
    monkeypatch.setattr(svc, "load_user", _load_user)
    monkeypatch.setattr(svc, "load_global", lambda: _Cfg2())
    return calls


async def test_resync_couvre_le_collecteur_de_metriques(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le portail ne connait pas `alloy-metrics` par son id : il le resynchronise
    parce que son compose reference METRICS_URL."""
    calls = _cabler(
        monkeypatch,
        {"alloy-metrics": _tpl_metrics()},
        [_dep_de("m1", "node1", "alloy-metrics")],
        loki=None,
        metrics="http://vm:8428/api/v1/write",
    )

    res = await svc.resync_collector_deployments(conn=object())

    assert res["synced"] == ["m1"]
    env = [w for w in calls["writes"] if w[1].endswith("/.env")]
    assert len(env) == 1 and "http://vm:8428/api/v1/write" in env[0][2]


async def test_resync_ignore_un_service_ordinaire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un service utilisateur ne doit pas etre recree a chaque changement de
    config d'observabilite : il ne reference aucune variable du portail."""
    calls = _cabler(
        monkeypatch,
        {"searxng": _tpl_ordinaire()},
        [_dep_de("s1", "node1", "searxng")],
        loki="http://loki:3100/p",
        metrics="http://vm:8428/api/v1/write",
    )

    res = await svc.resync_collector_deployments(conn=object())

    assert res == {"synced": [], "failed": [], "skipped": []}
    assert calls["writes"] == []


async def test_resync_saute_le_collecteur_dont_la_cible_a_disparu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metriques non configurees : on laisse le collecteur tel quel plutot que
    de lui reecrire un .env sans METRICS_URL, qui l'empecherait de redemarrer."""
    calls = _cabler(
        monkeypatch,
        {"alloy-metrics": _tpl_metrics()},
        [_dep_de("m1", "node1", "alloy-metrics")],
        loki="http://loki:3100/p",
        metrics=None,
    )

    res = await svc.resync_collector_deployments(conn=object())

    assert res["skipped"] == ["m1"]
    assert calls["writes"] == []


async def test_resync_les_deux_chaines_cote_a_cote(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _cabler(
        monkeypatch,
        {"alloy-collector": _tpl(), "alloy-metrics": _tpl_metrics()},
        [
            _dep_de("l1", "node1", "alloy-collector"),
            _dep_de("m1", "node1", "alloy-metrics"),
        ],
        loki="http://loki:3100/p",
        metrics="http://vm:8428/api/v1/write",
    )

    res = await svc.resync_collector_deployments(conn=object())

    assert sorted(res["synced"]) == ["l1", "m1"]
    env = {w[2] for w in calls["writes"] if w[1].endswith("/.env")}
    # Les deux URL partent dans CHAQUE .env : c'est le meme contexte injecte,
    # et un compose n'utilise que ce qu'il declare.
    assert all("http://loki:3100/p" in e and "http://vm:8428" in e for e in env)
