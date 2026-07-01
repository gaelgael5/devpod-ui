"""Seeding des templates compose builtin au démarrage du portail."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from . import db as cdb
from .models import ComposeTemplate
from .validation import TemplateValidationError, validate_template

_log = structlog.get_logger(__name__)

_ALLOY_VERSION = "1"

_ALLOY_COMPOSE = """\
services:
  alloy:
    image: grafana/alloy:v1.5.1
    container_name: devpod-alloy-agent
    restart: unless-stopped
    command:
      - run
      - /etc/alloy/config.alloy
      - --storage.path=/var/lib/alloy/data
      - --server.http.listen-addr=0.0.0.0:12345
    environment:
      LOKI_URL: ${LOKI_URL:?LOKI_URL requis}
      HOSTNAME: ${HOSTNAME:?HOSTNAME requis}
      MODULE: ${MODULE:-devpod}
      ROLE: ${ROLE:?ROLE requis}
    volumes:
      - ./config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/log:/var/log:ro
      - /run/log/journal:/run/log/journal:ro
      - /etc/machine-id:/etc/machine-id:ro
      - alloy_data:/var/lib/alloy/data
volumes:
  alloy_data:
"""

_ALLOY_CONFIG = """\
// Collecteur Alloy — devpod-ui (spec 30 §3.1)
// Envoie les logs Docker + journald vers Loki avec labeling structuré.

// ── Source 1 : conteneurs Docker ─────────────────────────────────────────────

discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

discovery.relabel "containers" {
  targets = discovery.docker.containers.targets

  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }
  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
    target_label  = "compose_service"
  }
  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_project"]
    target_label  = "compose_project"
  }
}

loki.source.docker "containers" {
  host          = "unix:///var/run/docker.sock"
  targets       = discovery.relabel.containers.output
  forward_to    = [loki.write.central.receiver]
  relabel_rules = discovery.relabel.containers.rules
}

// ── Source 2 : journald (logs système + kernel + Docker daemon) ───────────────

discovery.relabel "journal" {
  targets = []

  rule {
    source_labels = ["__journal__systemd_unit"]
    target_label  = "unit"
  }
}

loki.source.journal "system" {
  path          = "/run/log/journal"
  forward_to    = [loki.write.central.receiver]
  relabel_rules = discovery.relabel.journal.rules

  labels = {
    host = env("HOSTNAME"),
    job  = "journal",
  }
}

// ── Sortie Loki ──────────────────────────────────────────────────────────────

loki.write "central" {
  endpoint {
    url = env("LOKI_URL")
  }

  external_labels = {
    host   = env("HOSTNAME"),
    module = env("MODULE"),
    role   = env("ROLE"),
  }
}
"""


async def seed_builtin_templates(conn: AsyncConnection) -> None:
    """Insère ou met à jour les templates builtin au démarrage.

    Idempotent : si la version n'a pas changé, aucune écriture.
    """
    await _upsert_alloy_collector(conn)


async def _upsert_alloy_collector(conn: AsyncConnection) -> None:
    tpl_id = "alloy-collector"
    existing = await cdb.get_template(conn, tpl_id)

    tpl = ComposeTemplate(
        id=tpl_id,
        name="Collecteur de logs (Alloy)",
        description=(
            "Collecte les logs Docker et journald du host et les pousse vers Loki. "
            "Variables LOKI_URL/HOSTNAME/MODULE/ROLE injectées par le portail."
        ),
        tags=["observabilité", "logs", "builtin"],
        version=_ALLOY_VERSION,
        compose_content=_ALLOY_COMPOSE,
        parameters=[],
        source="builtin",
        extra_files={"config.alloy": _ALLOY_CONFIG},
    )

    try:
        validate_template(tpl.compose_content, tpl.parameters, source="builtin")
    except TemplateValidationError as exc:
        _log.error("builtin_template_invalid", template_id=tpl_id, error=str(exc))
        return

    if existing is None:
        await cdb.create_template(conn, tpl)
        _log.info("builtin_template_created", template_id=tpl_id)
    elif existing.version != tpl.version:
        await cdb.update_template(conn, tpl)
        _log.info("builtin_template_updated", template_id=tpl_id, version=tpl.version)
