# backend/tests/test_test_vm.py
from __future__ import annotations

from portal.config.models import HostConfig
from portal.devpod.test_vm import (
    build_resolve_fqdn,
    build_test_host_views,
    build_test_vm_args,
    build_testhost_ssh_command,
    host_cert_ready,
    map_result_to_host,
    replace_host_ip,
    substitute_param_vars,
)


def _ssh_host(name: str = "host-test-114-1", addr: str = "debian@192.168.10.160") -> HostConfig:
    return HostConfig(name=name, type="ssh", address=addr, vmid="114", usage="tests")


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


def test_build_test_host_views_maps_ip_and_vmid() -> None:
    hosts = [
        HostConfig(name="host-test-114-1", type="ssh", address="debian@192.168.10.160",
                   vmid="114", proxmox_node="pve1", usage="tests"),
    ]
    views = build_test_host_views([("host-test-114-1", "test1")], hosts)
    assert views == [
        {"alias": "test1", "name": "host-test-114-1", "ip": "192.168.10.160", "vmid": "114"}
    ]


def test_build_test_host_views_skips_orphan_association() -> None:
    # Association sans host correspondant (host retiré) → ignorée.
    views = build_test_host_views([("gone", "test1")], [])
    assert views == []


def test_testhost_ssh_command_for_allowed_host() -> None:
    cmd = build_testhost_ssh_command("host-test-114-1", ["host-test-114-1"], [_ssh_host()])
    assert cmd is not None
    assert "root@192.168.10.160" in cmd
    assert "ssh" in cmd
    # VM de test éphémère (DHCP, recréée) → pas de pinning de clé d'hôte.
    assert "StrictHostKeyChecking=no" in cmd
    assert "UserKnownHostsFile=/dev/null" in cmd


def test_testhost_ssh_command_rejects_host_outside_workspace() -> None:
    # Sécurité : host non listé pour ce workspace → refus, même s'il existe.
    assert build_testhost_ssh_command("host-test-114-1", [], [_ssh_host()]) is None


def test_testhost_ssh_command_rejects_missing_host() -> None:
    assert build_testhost_ssh_command("gone", ["gone"], []) is None


def test_testhost_ssh_command_rejects_non_ssh_host() -> None:
    docker = HostConfig(name="d", type="docker-tls", docker_host="tcp://x:2376", usage="tests")
    assert build_testhost_ssh_command("d", ["d"], [docker]) is None


def test_build_resolve_fqdn_with_domain() -> None:
    assert build_resolve_fqdn("host-test-114-1", "home.lan") == "host-test-114-1.home.lan"


def test_build_resolve_fqdn_without_domain() -> None:
    assert build_resolve_fqdn("host-test-114-1", "") == "host-test-114-1"


def test_build_resolve_fqdn_strips_dots_and_spaces() -> None:
    assert build_resolve_fqdn("host-1", ".home.lan.") == "host-1.home.lan"
    assert build_resolve_fqdn("host-1", "  home.lan  ") == "host-1.home.lan"


def test_replace_host_ip_preserves_user() -> None:
    assert replace_host_ip("debian@192.168.10.160", "192.168.10.200") == "debian@192.168.10.200"


def test_replace_host_ip_bare_ip() -> None:
    assert replace_host_ip("192.168.10.160", "10.0.0.5") == "10.0.0.5"


def test_replace_host_ip_empty_old() -> None:
    assert replace_host_ip("", "10.0.0.5") == "10.0.0.5"


def test_build_test_host_views_preserves_order() -> None:
    hosts = [
        HostConfig(name="a", type="ssh", address="u@10.0.0.1", vmid="1", usage="tests"),
        HostConfig(name="b", type="ssh", address="u@10.0.0.2", vmid="2", usage="tests"),
    ]
    views = build_test_host_views([("b", "test1"), ("a", "test2")], hosts)
    assert [v["alias"] for v in views] == ["test1", "test2"]
    assert [v["name"] for v in views] == ["b", "a"]


def test_host_cert_ready_true_when_slug_set() -> None:
    hosts = [_ssh_host("h1")]
    hosts[0].host_cert_slug = "compose.h1"
    assert host_cert_ready(hosts, "h1") is True


def test_host_cert_ready_false_when_slug_missing() -> None:
    assert host_cert_ready([_ssh_host("h1")], "h1") is False


def test_host_cert_ready_false_when_host_unknown() -> None:
    assert host_cert_ready([_ssh_host("h1")], "unknown") is False
