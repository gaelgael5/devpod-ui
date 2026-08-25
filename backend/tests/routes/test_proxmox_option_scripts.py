"""Résolution des `option_script` d'une spec d'hyperviseur.

Un `option_script` décrit les valeurs disponibles *sur l'hyperviseur* — les
templates Proxmox clonables, par exemple. Sans l'exécuter, `TEMPLATE_VMID` se
réduit au seul `auto` déclaré en dur dans la spec, et l'utilisateur n'a aucune
liste à choisir.
"""

from __future__ import annotations

from typing import Any

import pytest

from portal.config.models import Hypervisor
from portal.routes.proxmox import parse_option_lines, resolve_option_scripts

_LIGNES_PVE = "9000|9000 — debian-12-cloudinit\n9001|9001 — ubuntu-24-cloudinit\n"


def _node(name: str) -> Hypervisor:
    return Hypervisor(name=name, address="10.0.0.1", ssh_key_path="/data/keys/id", pve_node="pve")


def _spec() -> dict[str, Any]:
    """Extrait réel de `proxmox-clone-vm-node.json`."""
    return {
        "args": [
            {"arg": "NODE_NAME", "type": "string", "default": "host-dev-01"},
            {
                "type": "sub",
                "args": [
                    {
                        "arg": "TEMPLATE_VMID",
                        "type": "select",
                        "default": "auto",
                        "options": [{"value": "auto", "label": "auto (dernier template)"}],
                        "option_script": "for f in /etc/pve/qemu-server/*.conf; do :; done",
                    }
                ],
            },
        ]
    }


def test_parse_option_lines_value_and_label() -> None:
    assert parse_option_lines(_LIGNES_PVE) == [
        {"value": "9000", "label": "9000 — debian-12-cloudinit"},
        {"value": "9001", "label": "9001 — ubuntu-24-cloudinit"},
    ]


def test_parse_option_lines_value_alone_is_its_own_label() -> None:
    assert parse_option_lines("local\nlocal-lvm\n") == [
        {"value": "local", "label": "local"},
        {"value": "local-lvm", "label": "local-lvm"},
    ]


def test_parse_option_lines_ignores_blank_lines() -> None:
    assert parse_option_lines("\n  \n9000|t\n\n") == [{"value": "9000", "label": "t"}]


@pytest.mark.asyncio
async def test_resolve_appends_dynamic_options_after_the_declared_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run(node: Hypervisor, script: str, **kwargs: Any) -> str:
        return _LIGNES_PVE

    monkeypatch.setattr("portal.routes.proxmox._ssh_run", _run)
    spec = _spec()

    await resolve_option_scripts(spec, [_node("pve2")])

    options = spec["args"][1]["args"][0]["options"]
    assert [o["value"] for o in options] == ["auto", "9000", "9001"]


@pytest.mark.asyncio
async def test_resolve_merges_nodes_and_dedupes_on_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deux nœuds d'un même cluster voient le même `/etc/pve` : sans
    déduplication, chaque template apparaîtrait deux fois dans la liste."""
    par_node = {
        "pve2": _LIGNES_PVE,
        "pve3": "9000|9000 — debian-12-cloudinit\n9100|9100 — alpine\n",
    }

    async def _run(node: Hypervisor, script: str, **kwargs: Any) -> str:
        return par_node[node.name]

    monkeypatch.setattr("portal.routes.proxmox._ssh_run", _run)
    spec = _spec()

    await resolve_option_scripts(spec, [_node("pve2"), _node("pve3")])

    options = spec["args"][1]["args"][0]["options"]
    assert [o["value"] for o in options] == ["auto", "9000", "9001", "9100"]


@pytest.mark.asyncio
async def test_resolve_survives_an_unreachable_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un nœud éteint ne doit pas masquer la liste renvoyée par les autres."""

    async def _run(node: Hypervisor, script: str, **kwargs: Any) -> str:
        if node.name == "pve2":
            raise OSError("connection refused")
        return _LIGNES_PVE

    monkeypatch.setattr("portal.routes.proxmox._ssh_run", _run)
    spec = _spec()

    await resolve_option_scripts(spec, [_node("pve2"), _node("pve3")])

    arg = spec["args"][1]["args"][0]
    assert [o["value"] for o in arg["options"]] == ["auto", "9000", "9001"]
    assert "_option_script_error" not in arg


@pytest.mark.asyncio
async def test_resolve_reports_the_error_when_no_node_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Là, en revanche, il faut le dire : la liste affichée est incomplète."""

    async def _run(node: Hypervisor, script: str, **kwargs: Any) -> str:
        raise OSError("connection refused")

    monkeypatch.setattr("portal.routes.proxmox._ssh_run", _run)
    spec = _spec()

    await resolve_option_scripts(spec, [_node("pve2")])

    arg = spec["args"][1]["args"][0]
    assert arg["_option_script_error"] == "pve2: connection refused"
    assert [o["value"] for o in arg["options"]] == ["auto"]


@pytest.mark.asyncio
async def test_resolve_without_any_node_leaves_the_spec_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aucune machine enregistrée pour ce type : rien à interroger, et surtout
    pas d'erreur — la spec reste utilisable avec ses options déclarées."""

    async def _run(node: Hypervisor, script: str, **kwargs: Any) -> str:  # pragma: no cover
        raise AssertionError("aucune machine ne devait etre interrogee")

    monkeypatch.setattr("portal.routes.proxmox._ssh_run", _run)
    spec = _spec()

    await resolve_option_scripts(spec, [])

    arg = spec["args"][1]["args"][0]
    assert [o["value"] for o in arg["options"]] == ["auto"]
    assert "_option_script_error" not in arg
