"""Bug 024 : `_substitute` (proxmox.py) doit quoter les valeurs injectées dans
les commandes bash et ne jamais re-substituer un placeholder littéral produit
par la valeur d'un autre arg (exfiltration de PORTAL_TOKEN)."""
from __future__ import annotations

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
