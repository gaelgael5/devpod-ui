# backend/tests/mcp/test_devpod_docs.py
"""La doc produit du MCP devpod ne doit pas diverger du contrat (spec 24 §6)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPT = _HERE.parents[2] / "scripts" / "gen_mcp_docs.py"
_DOC = _HERE.parents[3] / "docs" / "mcp" / "devpod-tools.md"


def _render() -> str:
    spec = importlib.util.spec_from_file_location("gen_mcp_docs", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(mod.render())


def test_doc_lists_all_16_primitives() -> None:
    assert _DOC.read_text(encoding="utf-8").count("## `devpod__") == 16


def test_doc_is_up_to_date_with_registry() -> None:
    # Échoue si le registre a changé sans régénérer la doc (uv run python scripts/gen_mcp_docs.py).
    assert _render() == _DOC.read_text(encoding="utf-8")
