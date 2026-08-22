"""Bug 024 : `_substitute` (proxmox.py) doit quoter les valeurs injectées dans
les commandes bash et ne jamais re-substituer un placeholder littéral produit
par la valeur d'un autre arg (exfiltration de PORTAL_TOKEN)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from portal.routes.proxmox import _substitute


def test_substitute_basic_placeholder() -> None:
    assert _substitute("vmid={VMID}", {"VMID": "100"}) == "vmid=100"


def test_substitute_leaves_unknown_placeholder_intact() -> None:
    assert _substitute("keep {UNKNOWN}", {}) == "keep {UNKNOWN}"


def test_substitute_quotes_value_with_shell_metacharacters() -> None:
    out = _substitute("echo {MSG}", {"MSG": "a b; rm -rf /"})
    assert out == "echo 'a b; rm -rf /'"


def test_substitute_does_not_reprocess_output_of_prior_substitution() -> None:
    """Une valeur d'arg contenant littéralement "{PORTAL_TOKEN}" ne doit jamais se
    faire remplacer par le vrai token, même si PORTAL_TOKEN est substitué ensuite."""
    out = _substitute(
        "notify {ARG}",
        {"ARG": "{PORTAL_TOKEN}", "PORTAL_TOKEN": "s3cr3t-token"},
    )
    assert "s3cr3t-token" not in out
    assert out == "notify '{PORTAL_TOKEN}'"


def test_substitute_multiple_placeholders_single_pass() -> None:
    out = _substitute(
        "{A}-{B}",
        {"A": "x", "B": "y"},
    )
    assert out == "x-y"


def test_missing_placeholders_detects_unresolved() -> None:
    from portal.routes.proxmox import missing_placeholders

    templates = [
        "clone {VMID} --memory {MEMORY} --swap {SWAP_PERCENT}",
        "echo {CIUSER}",
    ]
    args = {"VMID": "105", "MEMORY": "8192", "CIUSER": "debian"}
    assert missing_placeholders(templates, args) == {"SWAP_PERCENT"}


def test_missing_placeholders_empty_when_all_present() -> None:
    from portal.routes.proxmox import missing_placeholders

    assert missing_placeholders(["a {X} b {Y}"], {"X": "1", "Y": "2"}) == set()


def test_spec_arg_defaults_includes_sub_and_excludes_identifier() -> None:
    from portal.routes.proxmox import spec_arg_defaults

    spec = {
        "args": [
            {"arg": "NEW_VMID", "identifier": True, "default": "x"},  # exclu
            {"arg": "STORAGE", "default": "auto"},
            {"arg": "NO_DEFAULT"},  # ignoré (pas de default)
            {
                "type": "sub",
                "args": [
                    {"arg": "MEMORY", "default": 8192},
                    {"arg": "SWAP_PERCENT", "default": 25},
                ],
            },
        ]
    }
    assert spec_arg_defaults(spec) == {"STORAGE": "auto", "MEMORY": "8192", "SWAP_PERCENT": "25"}


# ─── Type de CPU (enabler 6219c9f6) ──────────────────────────────────────────
# Le passthrough `host` expose vmx/svm à l'invité, donc /dev/kvm, donc la
# virtualisation imbriquée. Opt-in : il épingle la VM au CPU de son hôte et
# interdit la migration à chaud vers un hôte différent.

_CLONE_SPEC_PATH = Path(__file__).resolve().parents[3] / "scripts" / "proxmox-clone-vm-node.json"


def _clone_spec() -> dict[str, Any]:
    """Descripteur réellement livré — c'est lui que l'UI et le script consomment."""
    spec = json.loads(_CLONE_SPEC_PATH.read_text(encoding="utf-8"))
    assert isinstance(spec, dict)
    return spec


def _clone_command(spec: dict[str, Any]) -> str:
    """La ligne qui invoque le script (la dernière des `commands`)."""
    commands = spec["commands"]
    assert isinstance(commands, list)
    return str(commands[-1])


def test_substitute_cpu_type_when_provided() -> None:
    out = _substitute("qm set 105 --cpu '{CPU_TYPE}'", {"CPU_TYPE": "host"})
    assert out == "qm set 105 --cpu 'host'"


def test_missing_placeholders_detects_absent_cpu_type() -> None:
    """Un CPU_TYPE non fourni doit être vu AVANT l'exécution : sinon `{CPU_TYPE}`
    part littéral au script, qui le rejette après le clone."""
    from portal.routes.proxmox import missing_placeholders

    templates = ["clone {NEW_VMID} --cpu '{CPU_TYPE}'"]
    assert missing_placeholders(templates, {"NEW_VMID": "105"}) == {"CPU_TYPE"}


def test_clone_spec_declares_cpu_type_as_closed_list() -> None:
    """Liste fermée et non champ libre : un modèle invalide ferait échouer
    `qm set` APRÈS le clone, laissant une VM à moitié configurée."""
    from portal.routes.proxmox import _flatten_args

    args = _clone_spec()["args"]
    assert isinstance(args, list)
    cpu = next(a for a in _flatten_args(args) if a.get("arg") == "CPU_TYPE")

    assert cpu["type"] == "select"
    options = cpu["options"]
    assert isinstance(options, list)
    assert [o["value"] for o in options] == ["x86-64-v3", "host"]


def test_clone_spec_cpu_type_defaults_to_current_behaviour() -> None:
    """AC2 — le défaut reproduit le comportement actuel du script. `kvm64` masque
    AVX, dont dépendent les binaires compilés avec Bun (`claude`) : le poser par
    défaut casserait tout le parc."""
    from portal.routes.proxmox import spec_arg_defaults

    assert spec_arg_defaults(_clone_spec())["CPU_TYPE"] == "x86-64-v3"


def test_clone_command_without_cpu_type_keeps_previous_qm_set_line() -> None:
    """AC2 — sans choix explicite, la ligne produite reste celle d'avant."""
    from portal.routes.proxmox import spec_arg_defaults

    spec = _clone_spec()
    ligne = _substitute(_clone_command(spec), spec_arg_defaults(spec))
    assert "--cpu 'x86-64-v3'" in ligne


def test_clone_command_carries_the_chosen_cpu_type() -> None:
    from portal.routes.proxmox import spec_arg_defaults

    spec = _clone_spec()
    args = {**spec_arg_defaults(spec), "CPU_TYPE": "host"}
    assert "--cpu 'host'" in _substitute(_clone_command(spec), args)
