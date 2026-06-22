from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from portal.config.models import UserConfig

# ─── Fixtures DB partagées (utilisées par tests/db/ et tests/exposure/) ───────


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """Démarre un container PostgreSQL et retourne son URL asyncpg.

    Le container vit toute la session pytest et est détruit à la fin.
    Nécessite Docker disponible sur la machine — skippe si absent.
    """
    try:
        import docker

        docker.from_env()
    except Exception as exc:
        pytest.skip(f"Docker non disponible (tests DB skippés) : {exc}")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers peut renvoyer une URL avec un driver sync par défaut
        # (postgresql+psycopg2://). On force asyncpg pour create_async_engine,
        # quel que soit le driver présent dans l'URL.
        url = re.sub(
            r"^postgresql(\+[a-z0-9]+)?://", "postgresql+asyncpg://", pg.get_connection_url(), count=1
        )
        yield url


@pytest.fixture
async def db_engine(postgres_url: str) -> AsyncEngine:
    """Crée un moteur isolé, applique le schéma, détruit les tables après le test."""
    import portal.db.engine as _engine_module
    from portal.db.tables import metadata

    engine = create_async_engine(postgres_url, pool_size=1, max_overflow=0)
    _engine_module._engine = engine

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)

    await engine.dispose()
    _engine_module._engine = None


@pytest.fixture
async def db_conn(db_engine: AsyncEngine) -> AsyncConnection:
    """Connexion dans une transaction imbriquée (SAVEPOINT).

    La transaction est rollbackée après chaque test : isolation parfaite
    sans avoir à recréer les tables.
    """
    async with db_engine.connect() as conn:
        await conn.begin_nested()
        yield conn
        await conn.rollback()


@pytest.fixture
def tmp_data_root(tmp_path, monkeypatch):
    """Redirige PORTAL_DATA_ROOT vers un répertoire temporaire."""
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def global_config_yaml() -> str:
    return """\
version: "1"
server:
  listen: "0.0.0.0:8080"
  base_domain: "dev.yoops.org"
  external_url: "https://dev.yoops.org"
  dev_mode: false
  log:
    level: "info"
    format: "text"
    output: ""
auth:
  oidc:
    issuer: "https://security.yoops.org/realms/yoops"
    client_id: "workspace-portal"
    client_secret: "${env://OIDC_CLIENT_SECRET}"
    scopes: ["openid", "profile", "email", "roles"]
    role_claim: "realm_access.roles"
    admin_role: "admin"
    user_role: "dev"
    username_claim: "preferred_username"
secrets:
  backend: "inline"
devpod:
  binary: "/usr/local/bin/devpod"
  defaults:
    ide: "openvscode"
    idle_timeout: "2h"
    dotfiles: ""
  client_cert_path: "/data/certs/portal"
hosts:
  - name: "local"
    default: true
    type: "docker-tls"
    docker_host: "tcp://192.168.1.50:2376"
caddy:
  admin_api: "http://caddy:2019"
cloudflare_manager:
  url: ""
  api_key: ""
"""


@pytest.fixture
def user_config_yaml() -> str:
    return """\
version: "1"
secret_ns: "a3f8c1d2-4b56-7890-abcd-ef1234567890"
defaults:
  ide: "openvscode"
  idle_timeout: "4h"
harpocrate:
  api_key: ""
git_credentials: []
workspaces: []
"""


@pytest.fixture
def sample_user_config() -> UserConfig:
    return UserConfig.model_validate(
        {
            "version": "1",
            "secret_ns": str(uuid.uuid4()),
            "defaults": {"ide": "openvscode", "idle_timeout": "4h"},
            "harpocrate": {"api_key": ""},
            "git_credentials": [],
            "workspaces": [],
        }
    )
