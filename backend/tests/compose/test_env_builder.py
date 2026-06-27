# backend/tests/compose/test_env_builder.py
from portal.compose import env_builder


def test_render_env_file() -> None:
    out = env_builder.render_env_file({"A": "1", "B": "two"})
    assert out == 'A="1"\nB="two"\n'


def test_render_env_file_escapes_newline() -> None:
    out = env_builder.render_env_file({"S": "real\nEXTRA=injected"})
    # exactly one physical line for the key S (no injected EXTRA= line at column 0)
    assert out == 'S="real\\nEXTRA=injected"\n'
    assert out.count("\n") == 1  # only the trailing line terminator


def test_resolve_env_values_passes_through_literals(monkeypatch) -> None:
    # Une valeur non-référence est retournée telle quelle (pas d'appel backend).
    monkeypatch.setattr(env_builder, "_resolve_one", lambda login, ns, v: v)
    res = env_builder.resolve_env_values("alice", "ns", {"PORT": "3000"})
    assert res == {"PORT": "3000"}


def test_resolve_env_values_resolves_refs(monkeypatch) -> None:
    monkeypatch.setattr(
        env_builder, "_resolve_one",
        lambda login, ns, v: "SECRET" if v.startswith("${vault://") else v,
    )
    res = env_builder.resolve_env_values("alice", "ns", {"TOK": "${vault://x/y}", "P": "80"})
    assert res == {"TOK": "SECRET", "P": "80"}
