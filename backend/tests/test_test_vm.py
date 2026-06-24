# backend/tests/test_test_vm.py
from __future__ import annotations

from portal.devpod.test_vm import (
    build_test_vm_args,
    map_result_to_host,
    substitute_param_vars,
)


def test_build_args_adds_identifier() -> None:
    args = build_test_vm_args({"STORAGE": "auto", "MEMORY": "2048"}, "NEW_VMID", "150")
    assert args["NEW_VMID"] == "150"
    assert args["STORAGE"] == "auto"
    assert args["MEMORY"] == "2048"


def test_build_args_does_not_mutate_input() -> None:
    params = {"STORAGE": "auto"}
    build_test_vm_args(params, "NEW_VMID", "150")
    assert "NEW_VMID" not in params


def test_map_result_ssh_host_marks_tests() -> None:
    h = map_result_to_host(
        {"name": "test-01", "address": "192.168.1.50", "ssh_user": "debian", "type": "ssh"},
        "150",
        "pve",
    )
    assert h.type == "ssh"
    assert h.address == "debian@192.168.1.50"
    assert h.usage == "tests"
    assert h.vmid == "150"
    assert h.proxmox_node == "pve"


def test_map_result_docker_host() -> None:
    h = map_result_to_host(
        {"name": "test-01", "address": "192.168.1.50", "type": "docker-tls"},
        "150",
        "pve",
    )
    assert h.type == "docker-tls"
    assert h.usage == "tests"
    assert "2376" in h.docker_host


def test_map_result_vmid_and_node_fallback() -> None:
    h = map_result_to_host({"name": "x", "address": "1.2.3.4", "type": "ssh"}, "199", "pve2")
    assert h.vmid == "199"
    assert h.proxmox_node == "pve2"


def test_substitute_param_vars_resolves_arg_and_counter() -> None:
    args = {"NODE_NAME": "host-test-<NEW_VMID>-<N+1>", "NEW_VMID": "150"}
    out = substitute_param_vars(args, {"N": "2", "N+1": "3"})
    assert out["NODE_NAME"] == "host-test-150-3"
    assert out["NEW_VMID"] == "150"


def test_substitute_param_vars_unknown_left_intact() -> None:
    out = substitute_param_vars({"X": "a-<UNKNOWN>-b"}, {})
    assert out["X"] == "a-<UNKNOWN>-b"


def test_substitute_param_vars_plain_value() -> None:
    assert substitute_param_vars({"X": "plain"}, {"N": "1"})["X"] == "plain"
