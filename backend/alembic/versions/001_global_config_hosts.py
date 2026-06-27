"""global_config, hypervisor_types, hypervisors, hosts

Revision ID: 001
Revises:
Create Date: 2026-06-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "global_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("listen", sa.Text, nullable=False, server_default="0.0.0.0:8080"),
        sa.Column("base_domain", sa.Text, nullable=False),
        sa.Column("external_url", sa.Text, nullable=False),
        sa.Column("dev_mode", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("workspace_host", sa.Text, nullable=False, server_default=""),
        sa.Column("log_level", sa.Text, nullable=False, server_default="info"),
        sa.Column("log_format", sa.Text, nullable=False, server_default="text"),
        sa.Column("log_output", sa.Text, nullable=False, server_default=""),
        sa.Column("oidc_issuer", sa.Text, nullable=False),
        sa.Column("oidc_client_id", sa.Text, nullable=False),
        sa.Column("oidc_client_secret", sa.Text, nullable=False, server_default=""),
        sa.Column("oidc_scopes", ARRAY(sa.Text), nullable=False),
        sa.Column("oidc_role_claim", sa.Text, nullable=False, server_default="realm_access.roles"),
        sa.Column("oidc_admin_role", sa.Text, nullable=False, server_default="admin"),
        sa.Column("oidc_user_role", sa.Text, nullable=False, server_default="dev"),
        sa.Column("oidc_username_claim", sa.Text, nullable=False, server_default="preferred_username"),
        sa.Column("secrets_backend", sa.Text, nullable=False, server_default="inline"),
        sa.Column("harpocrate_url", sa.Text, nullable=False, server_default=""),
        sa.Column("harpocrate_api_key", sa.Text, nullable=False, server_default=""),
        sa.Column("harpocrate_base_path", sa.Text, nullable=False, server_default="devpod"),
        sa.Column("devpod_binary", sa.Text, nullable=False, server_default="/usr/local/bin/devpod"),
        sa.Column("devpod_client_cert_path", sa.Text, nullable=False, server_default="/data/certs/portal"),
        sa.Column("devpod_ide", sa.Text, nullable=False, server_default="openvscode"),
        sa.Column("devpod_idle_timeout", sa.Text, nullable=False, server_default="2h"),
        sa.Column("devpod_dotfiles", sa.Text, nullable=False, server_default=""),
        sa.Column("caddy_admin_api", sa.Text, nullable=False, server_default="http://caddy:2019"),
        sa.Column("caddy_portal_host", sa.Text, nullable=False, server_default="portal"),
        sa.Column("cf_url", sa.Text, nullable=False, server_default=""),
        sa.Column("cf_api_key", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("id = 1", name="ck_global_config_singleton"),
    )

    op.create_table(
        "hypervisor_types",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False, server_default=""),
        sa.Column("add_script", sa.Text, nullable=False, server_default=""),
        sa.Column("destroy_script", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_hypervisor_types_name"),
    )

    op.create_table(
        "hypervisors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("ssh_user", sa.Text, nullable=False, server_default="root"),
        sa.Column("ssh_port", sa.Integer, nullable=False, server_default="22"),
        sa.Column("ssh_key_path", sa.Text, nullable=False),
        sa.Column("pve_node", sa.Text, nullable=False, server_default="pve"),
        sa.Column("hypervisor_type", sa.Text, nullable=False, server_default=""),
        sa.Column("password", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_hypervisors_name"),
    )

    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("docker_host", sa.Text, nullable=False, server_default=""),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("key_path", sa.Text, nullable=False, server_default=""),
        sa.Column("public_key", sa.Text, nullable=False, server_default=""),
        sa.Column("proxmox_node", sa.Text, nullable=False, server_default=""),
        sa.Column("vmid", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_hosts_name"),
    )


def downgrade() -> None:
    op.drop_table("hosts")
    op.drop_table("hypervisors")
    op.drop_table("hypervisor_types")
    op.drop_table("global_config")
