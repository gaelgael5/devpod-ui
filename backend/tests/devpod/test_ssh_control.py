"""Multiplexage SSH (ControlMaster) — tranche 1 de la refonte des sessions.

Un tunnel devpod « chaud » par workspace, réutilisé entre ouvertures. Le point
critique : le ControlPath ne peut PAS dériver du host nominal (identique pour tous
les workspaces, `vscode@devpod-ws`) — il est donc clé sur `ws_id`, unique.
"""

from __future__ import annotations

from portal.devpod.ssh_exec import _CONTROL_DIR, build_ssh_argv, control_ssh_args


def _control_path(args: list[str]) -> str:
    for a in args:
        if a.startswith("ControlPath="):
            return a[len("ControlPath=") :]
    raise AssertionError("ControlPath absent")


class TestControlSshArgs:
    def test_includes_master_persist_and_path(self) -> None:
        args = control_ssh_args("alice-proj")
        assert "ControlMaster=auto" in args
        assert any(a.startswith("ControlPath=") for a in args)
        assert any(a.startswith("ControlPersist=") for a in args)

    def test_path_stable_per_ws_and_distinct_between_ws(self) -> None:
        pa = _control_path(control_ssh_args("alice-proj"))
        pb = _control_path(control_ssh_args("alice-proj"))
        pc = _control_path(control_ssh_args("bob-proj"))
        assert pa == pb  # même workspace → même master
        assert pa != pc  # workspaces distincts → pas de collision de tunnel
        assert pa.startswith(str(_CONTROL_DIR))

    def test_path_socket_length_bounded(self) -> None:
        # Limite sun_path (~104) : même un ws_id très long doit tenir (on hashe).
        assert len(_control_path(control_ssh_args("x" * 300))) < 100

    def test_build_ssh_argv_carries_control_options(self) -> None:
        argv = build_ssh_argv("alice-proj", "tmux ls", devpod_bin="/usr/bin/devpod", key_path=None)
        assert "ControlMaster=auto" in argv
        assert any(a.startswith("ControlPath=") for a in argv)
