# backend/tests/test_proxmox_spec.py
from __future__ import annotations

from portal.routes.proxmox import find_identifier_arg


def test_find_identifier_arg_top_level() -> None:
    spec = {"args": [{"arg": "NEW_VMID", "identifier": True}, {"arg": "NODE_NAME"}]}
    assert find_identifier_arg(spec) == "NEW_VMID"


def test_find_identifier_arg_none_when_unmarked() -> None:
    spec = {"args": [{"arg": "A"}, {"arg": "B"}]}
    assert find_identifier_arg(spec) is None


def test_find_identifier_arg_in_sub_group() -> None:
    spec = {
        "args": [
            {"type": "sub", "args": [{"arg": "VMID", "identifier": True}]},
        ]
    }
    assert find_identifier_arg(spec) == "VMID"


def test_find_identifier_arg_empty_spec() -> None:
    assert find_identifier_arg({}) is None
    assert find_identifier_arg({"args": []}) is None


def test_find_identifier_arg_ignores_false_flag() -> None:
    spec = {"args": [{"arg": "X", "identifier": False}, {"arg": "Y"}]}
    assert find_identifier_arg(spec) is None
