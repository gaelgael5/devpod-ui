"""Détection de l'état devpod local (`_devpod_state_exists`) — incident 30/08.

DevPod range l'état **client** d'un workspace dans
`$DEVPOD_HOME/contexts/<contexte>/workspaces/<ws_id>`. Le sous-arbre `agent/`
est celui de l'**agent**, posé sur le nœud, jamais dans le DEVPOD_HOME du
portail : le chercher là rendait la sonde toujours fausse, et le portail
rejouait un `devpod up` complet à chaque redémarrage (7 jours de logs sans une
seule occurrence de la branche « état présent »).

Vérifié contre devpod v0.6.15 : un `workspace.json` déposé sous
`contexts/default/workspaces/<id>` est listé par `devpod list`, le même déposé
sous `agent/contexts/default/workspaces/<id>` ne l'est pas.
"""

from __future__ import annotations

from pathlib import Path

from portal.devpod.service import DevPodService


def _devpod_home(data_root: Path, login: str) -> Path:
    return data_root / "users" / login / "devpod"


class TestDevpodStateExists:
    def test_true_on_client_side_workspace_dir(self, tmp_data_root: Path, global_cfg) -> None:
        home = _devpod_home(tmp_data_root, "alice")
        (home / "contexts" / "default" / "workspaces" / "alice-app").mkdir(parents=True)

        svc = DevPodService(global_cfg=global_cfg)

        assert svc._devpod_state_exists("alice-app", "alice") is True

    def test_false_when_only_agent_subtree_present(self, tmp_data_root: Path, global_cfg) -> None:
        """Le sous-arbre `agent/` n'est pas l'état client : il ne doit rien prouver."""
        home = _devpod_home(tmp_data_root, "alice")
        (home / "agent" / "contexts" / "default" / "workspaces" / "alice-app").mkdir(parents=True)

        svc = DevPodService(global_cfg=global_cfg)

        assert svc._devpod_state_exists("alice-app", "alice") is False

    def test_false_when_nothing_present(self, tmp_data_root: Path, global_cfg) -> None:
        svc = DevPodService(global_cfg=global_cfg)

        assert svc._devpod_state_exists("alice-app", "alice") is False

    def test_isolated_per_user(self, tmp_data_root: Path, global_cfg) -> None:
        """L'état d'un user ne vaut pas pour un autre (DEVPOD_HOME isolé)."""
        home = _devpod_home(tmp_data_root, "alice")
        (home / "contexts" / "default" / "workspaces" / "alice-app").mkdir(parents=True)

        svc = DevPodService(global_cfg=global_cfg)

        assert svc._devpod_state_exists("alice-app", "bob") is False
