"""Tests pour portal.compose.port_aliases."""
from portal.compose.port_aliases import (
    PortAlias,
    is_alias_entry,
    parse_port_aliases,
    rewrite_compose_ports,
)

# ---------------------------------------------------------------------------
# is_alias_entry
# ---------------------------------------------------------------------------

def test_alias_entry_recognized() -> None:
    assert is_alias_entry("chromium>3000:3000")
    assert is_alias_entry("api>8080:8080")
    assert is_alias_entry("my-svc>4000:3000")


def test_non_alias_entries_rejected() -> None:
    assert not is_alias_entry("3000:3000")
    assert not is_alias_entry("3000")
    assert not is_alias_entry("${PORT}:3000")
    assert not is_alias_entry("0.0.0.0:3000:80")
    assert not is_alias_entry(3000)
    assert not is_alias_entry({"published": 3000, "target": 80})


# ---------------------------------------------------------------------------
# parse_port_aliases
# ---------------------------------------------------------------------------

_YAML_MULTI = """
services:
  browser:
    image: chromium:1.0.0
    ports:
      - chromium>3000:3000
  backend:
    image: api:1.0.0
    ports:
      - api>8080:8080
      - 5432
"""


def test_parse_extracts_two_aliases() -> None:
    aliases = parse_port_aliases(_YAML_MULTI)
    assert len(aliases) == 2
    assert aliases[0] == PortAlias(alias="chromium", min_host_port=3000, container_port=3000)
    assert aliases[1] == PortAlias(alias="api", min_host_port=8080, container_port=8080)


def test_parse_ignores_plain_ports() -> None:
    yaml = """
services:
  db:
    image: postgres:15
    ports:
      - 5432
"""
    assert parse_port_aliases(yaml) == []


def test_parse_ignores_var_ports() -> None:
    yaml = """
services:
  web:
    image: nginx:1.27.0
    ports:
      - "${WEB_PORT}:80"
"""
    assert parse_port_aliases(yaml) == []


def test_parse_deduplicates_same_alias() -> None:
    """Deux services avec le même alias → un seul PortAlias."""
    yaml = """
services:
  svc1:
    image: x:1
    ports: [chromium>3000:3000]
  svc2:
    image: y:1
    ports: [chromium>3000:3000]
"""
    aliases = parse_port_aliases(yaml)
    assert len(aliases) == 1
    assert aliases[0].alias == "chromium"


def test_parse_returns_empty_on_bad_yaml() -> None:
    assert parse_port_aliases("services: [broken") == []


def test_alias_env_var_name() -> None:
    a = PortAlias(alias="my-svc", min_host_port=3000, container_port=3000)
    assert a.env_var == "PORT_MY_SVC"


# ---------------------------------------------------------------------------
# rewrite_compose_ports
# ---------------------------------------------------------------------------

def test_rewrite_replaces_alias_entries() -> None:
    content = "ports:\n  - chromium>3000:3000\n  - api>8080:8080\n"
    result = rewrite_compose_ports(content, {"chromium": 3007, "api": 8095})
    assert "3007:3000" in result
    assert "8095:8080" in result
    assert "chromium>" not in result
    assert "api>" not in result


def test_rewrite_leaves_plain_ports_untouched() -> None:
    content = "ports:\n  - 5432\n  - chromium>3000:3000\n"
    result = rewrite_compose_ports(content, {"chromium": 3005})
    assert "5432" in result
    assert "3005:3000" in result


def test_rewrite_empty_port_map_noop() -> None:
    content = "ports:\n  - chromium>3000:3000\n"
    assert rewrite_compose_ports(content, {}) == content
