from __future__ import annotations

import os
import re
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from portal.config.models import UserConfig

# ─── Fixtures DB partagées (utilisées par tests/db/ et tests/exposure/) ───────


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """URL asyncpg d'un PostgreSQL de test.

    - Si `TEST_DATABASE_URL` est défini, l'utilise tel quel (Postgres externe : CI,
      Docker distant via tunnel SSH…) — permet de jouer les tests DB sans Docker local.
    - Sinon démarre un container PostgreSQL éphémère (testcontainers) qui vit toute la
      session pytest ; skippe si Docker est absent.
    """
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield external
        return

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
            r"^postgresql(\+[a-z0-9]+)?://",
            "postgresql+asyncpg://",
            pg.get_connection_url(),
            count=1,
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
async def db_engine_concurrent(db_engine: AsyncEngine, postgres_url: str) -> AsyncEngine:
    """Moteur secondaire (pool de 2) pour les tests de concurrence (bug 010).

    `db_engine` est limité à une seule connexion (pool_size=1, max_overflow=0) :
    impossible d'y ouvrir deux transactions concurrentes. Ce moteur partage le
    même schéma (créé/détruit par `db_engine`) mais autorise deux connexions.
    Les écritures sont committées (pas de SAVEPOINT) — les tables sont de toute
    façon droppées en fin de test par le teardown de `db_engine`.
    """
    engine = create_async_engine(postgres_url, pool_size=2, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _cles_jetables() -> None:
    """Pose des clés de session et de vault jetables pour toute la suite.

    `AppSettings` lit un `.env` gitignoré, généré au déploiement par
    `deploy-portal.sh`. Un clone neuf n'en a aucun : `dev_mode` reste à `False`
    et `create_app()` lève une `RuntimeError` — 21 tests tombaient pour cette
    seule raison, indiscernables d'une vraie régression.

    Un test porte son propre environnement ; il ne dépend pas d'un fichier
    absent du dépôt. `setdefault` : un environnement déjà configuré (CI, poste
    avec `.env`) reste maître.
    """
    os.environ.setdefault("SESSION_SECRET_KEY", f"test-{uuid.uuid4().hex}")
    # 32 octets en hexadécimal, comme `openssl rand -hex 32` que réclame le message
    # d'erreur du portail.
    os.environ.setdefault("PORTAL_VAULT_KEK", uuid.uuid4().hex + uuid.uuid4().hex)


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
