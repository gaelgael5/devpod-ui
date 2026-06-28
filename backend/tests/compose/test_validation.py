import pytest

from portal.compose import validation
from portal.compose.models import ComposeParam

_OK = """
services:
  web:
    image: nginx:1.27.0
    ports:
      - "${WEB_PORT}:80"
"""


def _port_param() -> list[ComposeParam]:
    return [ComposeParam(key="WEB_PORT", label="Port", type="port", required=True)]


def test_referenced_vars() -> None:
    assert validation.referenced_vars('image: x\nports: ["${WEB_PORT}:80"]') == {"WEB_PORT"}


def test_valid_template_no_warnings() -> None:
    assert validation.validate_template(_OK, _port_param()) == []


def test_latest_is_warning() -> None:
    content = _OK.replace("nginx:1.27.0", "nginx:latest")
    warnings = validation.validate_template(content, _port_param())
    assert any("latest" in w for w in warnings)


def test_untagged_image_is_warning() -> None:
    content = """
services:
  web:
    image: nginx
    ports:
      - "${WEB_PORT}:80"
"""
    warnings = validation.validate_template(content, _port_param())
    assert warnings  # non-empty: untagged image flagged


def test_unparseable_yaml_raises() -> None:
    with pytest.raises(validation.TemplateValidationError):
        validation.validate_template("services: [unbalanced", _port_param())


def test_undeclared_var_raises() -> None:
    with pytest.raises(validation.TemplateValidationError):
        validation.validate_template(_OK, [])  # WEB_PORT non déclaré


def test_hardcoded_host_port_raises() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    ports:
      - "3000:80"
"""
    with pytest.raises(validation.TemplateValidationError):
        validation.validate_template(content, [])


def test_bind_ip_hardcoded_host_port_raises() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    ports:
      - "0.0.0.0:3000:80"
"""
    with pytest.raises(validation.TemplateValidationError):
        validation.validate_template(content, [])


def test_longform_hardcoded_published_raises() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    ports:
      - {published: 3000, target: 80}
"""
    with pytest.raises(validation.TemplateValidationError):
        validation.validate_template(content, [])


def test_bind_ip_with_var_ok() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    ports:
      - "127.0.0.1:${WEB_PORT}:80"
"""
    result = validation.validate_template(content, _port_param())
    assert isinstance(result, list)  # no exception → warnings list returned


def test_longform_published_var_ok() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    ports:
      - {published: "${WEB_PORT}", target: 80}
"""
    result = validation.validate_template(content, _port_param())
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Nouveau format alias>min:container
# ---------------------------------------------------------------------------

def test_alias_port_format_accepted() -> None:
    """chromium>3000:3000 ne doit pas être rejeté comme port codé en dur."""
    content = """
services:
  browser:
    image: chromium:1.0.0
    ports:
      - chromium>3000:3000
"""
    result = validation.validate_template(content, [])
    assert isinstance(result, list)  # pas d'exception


def test_multiple_alias_ports_accepted() -> None:
    content = """
services:
  browser:
    image: chromium:1.0.0
    ports:
      - chromium>3000:3000
      - api>8080:8080
"""
    result = validation.validate_template(content, [])
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Bind-mounts absolus
# ---------------------------------------------------------------------------

def test_absolute_bind_mount_raises() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    volumes:
      - /etc/nginx:/etc/nginx:ro
"""
    with pytest.raises(validation.TemplateValidationError, match="absolu"):
        validation.validate_template(content, [])


def test_absolute_bind_mount_longform_raises() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    volumes:
      - type: bind
        source: /var/data
        target: /data
"""
    with pytest.raises(validation.TemplateValidationError, match="absolu"):
        validation.validate_template(content, [])


def test_relative_bind_mount_ok() -> None:
    content = """
services:
  web:
    image: nginx:1.27.0
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
"""
    result = validation.validate_template(content, [])
    assert isinstance(result, list)


def test_named_volume_ok() -> None:
    content = """
services:
  db:
    image: postgres:15
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
"""
    result = validation.validate_template(content, [])
    assert isinstance(result, list)
