# Galerie Docker Compose — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend FastAPI de la galerie docker-compose : CRUD de templates, instanciation/cycle de vie de déploiements sur un nœud `ssh` enrôlé, via un canal nœud non-interactif, avec secrets Harpocrate en référence et détection de conflit de ports.

**Architecture :** Nouveau canal nœud SSH non-interactif (`devpod/host_exec.py`) — seul point d'exécution. Nouveau module `compose/` (models pydantic, validation, couche DB SQLAlchemy Core, env builder, ports, service lifecycle). Persistance via Alembic migration 030 + tables Core. Routes `/api/compose/*` (templates admin, deployments dev+ownership). Conforme au cadrage `docs/superpowers/specs/2026-06-27-compose-gallery-design.md` et à `specs/26-compose-gallery.md`.

**Tech Stack :** Python 3.12, FastAPI, pydantic v2 (`extra="forbid"`), SQLAlchemy Core async (asyncpg driver), Alembic, structlog, pytest + pytest-asyncio. PyYAML (déjà dépendance).

## Global Constraints

- **Persistance** : SQLAlchemy Core async (`AsyncConnection`, `conn.execute(select/insert/update/delete(...))`) + Alembic. PAS d'asyncpg en direct, PAS d'ORM. (Corrige la spec 26 §2.5/§11.)
- **Canal nœud** : toute commande/écriture sur un nœud passe par `host_exec.run_host_command` / `write_host_file`. Jamais de shell local au portail, jamais `ws_exec` (scoped workspace). v1 : hosts `type == "ssh"` uniquement → sinon erreur explicite.
- **Secrets (non négociable)** : `env_values` en base ne contient QUE des références `${vault://...}`/`${env://...}` ; jamais une valeur résolue. Résolution via `secrets.resolver.resolve(value, Scope(kind="user", secret_ns, login), backend)`, en mémoire au `up` uniquement.
- **Pas de `:latest`** dans `compose_content` (lint bloquant à create/edit).
- **Tout port hôte exposé** doit être un paramètre `type=port` (vérifié au lint). Détection de conflit node-wide.
- pydantic v2 `extra="forbid"` sur tous les modèles. `type` hints partout, `from __future__ import annotations`.
- Fichiers ≤ 300 lignes ; classes SRP ; logs `structlog.get_logger(__name__)`, jamais `print()` ; jamais de secret dans un log.
- RBAC : templates CRUD = `require_admin` ; deployments = `require_user` + filtrage `owner_login` (admin voit tout).
- Slugs (`template.id`, `deployment.id`) validés `^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$` avant tout usage en chemin distant / `-p` / SQL.
- Tests : pytest-asyncio ; le canal nœud (`run_host_command`/`write_host_file`) est **mocké** dans les tests (pas de vrai nœud), comme `ws_exec` l'est pour les tests devpod_tools. Tests DB testcontainer = skip si Docker absent (cohérent projet).
- Commits conventionnels FR, branche `dev`.

---

# LOT 1 — Fondations : migration, tables, modèles

### Task 1: Migration Alembic 030 + déclarations de tables Core

**Files:**
- Create: `backend/alembic/versions/030_compose_gallery.py`
- Modify: `backend/src/portal/db/tables.py` (ajout de 3 tables)
- Test: `backend/tests/compose/test_tables.py`

**Interfaces:**
- Produces : tables Core `compose_template`, `compose_deployment`, `compose_deployment_log` importables depuis `portal.db.tables`.

> Référence migration : `backend/alembic/versions/029_grant_scopes.py` (format `revision`/`down_revision`, `op.*`). Index GIN via `postgresql_using="gin"`. JSONB via `sqlalchemy.dialects.postgresql.JSONB`. Tableaux via `sqlalchemy.dialects.postgresql.ARRAY`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_tables.py
from portal.db import tables


def test_compose_tables_declared() -> None:
    assert tables.compose_template.name == "compose_template"
    assert tables.compose_deployment.name == "compose_deployment"
    assert tables.compose_deployment_log.name == "compose_deployment_log"
    # colonnes clés présentes
    tcols = set(tables.compose_template.c.keys())
    assert {"id", "name", "tags", "version", "compose_content", "parameters", "source"} <= tcols
    dcols = set(tables.compose_deployment.c.keys())
    assert {"id", "template_id", "node_id", "owner_login", "env_values", "host_ports", "status"} <= dcols
    lcols = set(tables.compose_deployment_log.c.keys())
    assert {"id", "deployment_id", "operation", "content", "started_at", "finished_at"} <= lcols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/compose/test_tables.py -v`
Expected: FAIL (`AttributeError: module 'portal.db.tables' has no attribute 'compose_template'`). Crée `backend/tests/compose/__init__.py` (vide) si nécessaire pour la découverte.

- [ ] **Step 3: Declare the tables in tables.py**

Ajouter dans `backend/src/portal/db/tables.py` (réutiliser l'objet `metadata`/`MetaData` déjà présent dans ce fichier ; importer `JSONB` et `ARRAY` depuis `sqlalchemy.dialects.postgresql`) :

```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # regrouper avec imports existants

compose_template = Table(
    "compose_template",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("tags", ARRAY(Text), nullable=False, server_default="{}"),
    Column("version", Text, nullable=False),
    Column("compose_content", Text, nullable=False),
    Column("parameters", JSONB, nullable=False, server_default="[]"),
    Column("source", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

compose_deployment = Table(
    "compose_deployment",
    metadata,
    Column("id", Text, primary_key=True),
    Column("template_id", Text, ForeignKey("compose_template.id"), nullable=False),
    Column("template_version", Text, nullable=False),
    Column("node_id", Text, nullable=False),
    Column("owner_login", Text, nullable=False),
    Column("env_values", JSONB, nullable=False, server_default="{}"),
    Column("host_ports", ARRAY(Integer), nullable=False, server_default="{}"),
    Column("status", Text, nullable=False, server_default="created"),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

compose_deployment_log = Table(
    "compose_deployment_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("deployment_id", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("content", Text, nullable=False, server_default=""),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
)
```

> Vérifier en tête de `tables.py` que `Table, Column, Text, Integer, DateTime, ForeignKey, func, metadata` sont importés/définis ; ajouter ceux qui manquent en suivant le style du fichier.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/compose/test_tables.py -v`
Expected: PASS.

- [ ] **Step 5: Write the Alembic migration**

```python
# backend/alembic/versions/030_compose_gallery.py
"""Galerie docker-compose : templates, déploiements, logs.

Revision ID: 030
Revises: 029
Create Date: 2026-06-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "030"
down_revision: str | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compose_template",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("compose_content", sa.Text(), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False, server_default="[]"),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "compose_deployment",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("template_id", sa.Text(), sa.ForeignKey("compose_template.id"), nullable=False),
        sa.Column("template_version", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("owner_login", sa.Text(), nullable=False),
        sa.Column("env_values", JSONB(), nullable=False, server_default="{}"),
        sa.Column("host_ports", ARRAY(sa.Integer()), nullable=False, server_default="{}"),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "compose_deployment_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_deployment_node", "compose_deployment", ["node_id"])
    op.create_index("idx_deployment_owner", "compose_deployment", ["owner_login"])
    op.create_index("idx_deployment_ports", "compose_deployment", ["host_ports"], postgresql_using="gin")
    op.create_index("idx_template_tags", "compose_template", ["tags"], postgresql_using="gin")
    op.create_index("idx_deployment_log_dep", "compose_deployment_log", ["deployment_id"])


def downgrade() -> None:
    op.drop_table("compose_deployment_log")
    op.drop_table("compose_deployment")
    op.drop_table("compose_template")
```

- [ ] **Step 6: Verify migration imports + lint/type**

Run: `cd backend && uv run python -c "import importlib.util,glob; importlib.util.spec_from_file_location('m','alembic/versions/030_compose_gallery.py')" && uv run ruff check src/portal/db/tables.py alembic/versions/030_compose_gallery.py && uv run mypy src/portal/db/tables.py`
Expected: pas d'erreur. (L'`upgrade()` réel sera exercé sur CI/Docker — migration appliquée par `run_migrations`.)

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/030_compose_gallery.py backend/src/portal/db/tables.py backend/tests/compose/
git commit -m "feat(compose-gallery): migration 030 + tables Core (template/deployment/log)"
```

---

### Task 2: Modèles pydantic + slugs

**Files:**
- Create: `backend/src/portal/compose/__init__.py` (vide), `backend/src/portal/compose/models.py`
- Test: `backend/tests/compose/test_models.py`

**Interfaces:**
- Produces :
  - `ComposeParamType = Literal["string","number","bool","enum","port","secret"]`
  - `ComposeParam` (pydantic) : `key, label, description, type, default, required, options, secret_ref_hint`.
  - `ComposeTemplate` : `id, name, description, tags, version, compose_content, parameters, source, created_at, updated_at`.
  - `ComposeDeployment` : `id, template_id, template_version, node_id, owner_login, env_values, host_ports, status, last_error, created_at, updated_at`.
  - `DeploymentStatus = Literal["created","running","partial","stopped","error"]`, `TemplateSource = Literal["user","builtin","imported"]`.
  - `SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$")` + `validate_slug(value: str) -> str` (lève `ValueError`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_models.py
import pytest
from portal.compose import models


def test_param_minimal() -> None:
    p = models.ComposeParam(key="BROWSERLESS_PORT", label="Port", type="port", required=True)
    assert p.key == "BROWSERLESS_PORT"
    assert p.default is None and p.options is None


def test_template_forbids_extra() -> None:
    with pytest.raises(Exception):
        models.ComposeTemplate(
            id="x", name="X", version="1", compose_content="services: {}",
            parameters=[], source="user", bogus=1,
        )


def test_validate_slug() -> None:
    assert models.validate_slug("browserless-1") == "browserless-1"
    for bad in ("Bad", "-x", "x_y", "a", "x" * 60, "a b"):
        with pytest.raises(ValueError):
            models.validate_slug(bad)


def test_deployment_defaults() -> None:
    d = models.ComposeDeployment(
        id="dep1", template_id="t", template_version="1", node_id="n",
        owner_login="alice",
    )
    assert d.env_values == {} and d.host_ports == [] and d.status == "created"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/compose/test_models.py -v`
Expected: FAIL (module `portal.compose.models` absent).

- [ ] **Step 3: Write the models**

```python
# backend/src/portal/compose/models.py
"""Modèles de la galerie docker-compose (spec 26 §4 + cadrage)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$")

ComposeParamType = Literal["string", "number", "bool", "enum", "port", "secret"]
TemplateSource = Literal["user", "builtin", "imported"]
DeploymentStatus = Literal["created", "running", "partial", "stopped", "error"]


def validate_slug(value: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise ValueError(f"slug invalide: {value!r} (attendu ^[a-z0-9][a-z0-9-]{{0,40}}[a-z0-9]$)")
    return value


class ComposeParam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    description: str | None = None
    type: ComposeParamType
    default: str | None = None
    required: bool = False
    options: list[str] | None = None
    secret_ref_hint: str | None = None


class ComposeTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    version: str
    compose_content: str
    parameters: list[ComposeParam] = Field(default_factory=list)
    source: TemplateSource = "user"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ComposeDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    template_id: str
    template_version: str
    node_id: str
    owner_login: str
    env_values: dict[str, str] = Field(default_factory=dict)
    host_ports: list[int] = Field(default_factory=list)
    status: DeploymentStatus = "created"
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/compose/test_models.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/compose/ tests/compose/ && uv run mypy src/portal/compose/
git add backend/src/portal/compose/ backend/tests/compose/test_models.py
git commit -m "feat(compose-gallery): modèles pydantic + validation slug"
```

---

# LOT 2 — Validation + couche DB

### Task 3: Validation des templates (`validation.py`)

**Files:**
- Create: `backend/src/portal/compose/validation.py`
- Test: `backend/tests/compose/test_validation.py`

**Interfaces:**
- Consumes : `ComposeParam` (Task 2), PyYAML (`import yaml`).
- Produces :
  - `class TemplateValidationError(Exception)` (message FR).
  - `def validate_template(compose_content: str, parameters: list[ComposeParam]) -> list[str]` — retourne la liste des **warnings** (ex. `:latest`), lève `TemplateValidationError` sur erreur dure (YAML non parsable, param `${VAR}` non déclaré, port codé en dur).
  - `def referenced_vars(compose_content: str) -> set[str]` — extrait les `${VAR}` (et `${VAR:-default}`) du YAML brut.

> Règles (spec 26 §5/§7) : (1) YAML parsable ; (2) chaque `${VAR}` référencé doit avoir un `ComposeParam` correspondant (sinon erreur) ; (3) lint `:latest` → warning ; (4) tout `ports:` exposant un port hôte doit le faire via une variable `type=port` (heuristique : un mapping `"NNNN:..."` avec un littéral numérique en partie hôte → erreur ; `"${X}:..."` → OK).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_validation.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/compose/test_validation.py -v`
Expected: FAIL (module absent).

- [ ] **Step 3: Write the implementation**

```python
# backend/src/portal/compose/validation.py
"""Validation et lint des templates compose (spec 26 §5/§7)."""
from __future__ import annotations

import re

import yaml

from .models import ComposeParam

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")
# Mapping de ports avec un littéral numérique en partie hôte (port hôte codé en dur).
_HARDCODED_PORT_RE = re.compile(r"^\s*\"?(\d{1,5}):")


class TemplateValidationError(Exception):
    """Erreur dure de validation d'un template (FR)."""


def referenced_vars(compose_content: str) -> set[str]:
    return set(_VAR_RE.findall(compose_content))


def _port_mappings(parsed: dict) -> list[str]:
    out: list[str] = []
    services = (parsed or {}).get("services") or {}
    if not isinstance(services, dict):
        return out
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        ports = svc.get("ports") or []
        if isinstance(ports, list):
            out.extend(str(p) for p in ports)
    return out


def validate_template(compose_content: str, parameters: list[ComposeParam]) -> list[str]:
    try:
        parsed = yaml.safe_load(compose_content)
    except yaml.YAMLError as exc:
        raise TemplateValidationError(f"YAML compose non parsable: {exc}") from exc
    if not isinstance(parsed, dict) or "services" not in parsed:
        raise TemplateValidationError("compose invalide: clé 'services' absente")

    declared = {p.key for p in parameters}
    used = referenced_vars(compose_content)
    missing = used - declared
    if missing:
        raise TemplateValidationError(
            f"variables référencées non déclarées en paramètres: {sorted(missing)}"
        )

    for mapping in _port_mappings(parsed):
        if _HARDCODED_PORT_RE.match(mapping):
            raise TemplateValidationError(
                f"port hôte codé en dur ({mapping!r}) : exposez-le via un paramètre type=port (${{VAR}})"
            )

    warnings: list[str] = []
    for line in compose_content.splitlines():
        if re.search(r"image:\s*\S+:latest(\s|$)", line) or re.search(r"image:\s*[^:\s]+(\s|$)", line):
            if ":latest" in line or re.search(r"image:\s*[^:\s]+\s*$", line):
                warnings.append(f"image non épinglée ('latest' ou sans tag): {line.strip()}")
    return warnings
```

> Le lint `:latest` doit aussi flagger une image sans tag (implicitement `latest`). Garder la logique simple et testée par les cas ci-dessus ; affiner si un cas réel échappe.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/compose/test_validation.py -v`
Expected: PASS (6 tests). Si `test_latest_is_warning` ou un autre échoue à cause de la double-condition du lint, simplifier la boucle de warnings pour qu'elle ne flagge que `:latest` et les images sans `:` — réexécuter jusqu'au vert.

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/compose/validation.py tests/compose/test_validation.py && uv run mypy src/portal/compose/validation.py
git add backend/src/portal/compose/validation.py backend/tests/compose/test_validation.py
git commit -m "feat(compose-gallery): validation template (YAML, params, lint :latest, ports)"
```

---

### Task 4: Couche DB — templates (`db.py`, partie templates)

**Files:**
- Create: `backend/src/portal/compose/db.py`
- Test: `backend/tests/compose/test_db_templates.py`

**Interfaces:**
- Consumes : `portal.db.tables.compose_template`, `ComposeTemplate`/`ComposeParam` (Task 2), `AsyncConnection`.
- Produces (toutes `async`, prennent `conn: AsyncConnection`) :
  - `create_template(conn, tpl: ComposeTemplate) -> None`
  - `get_template(conn, template_id: str) -> ComposeTemplate | None`
  - `list_templates(conn, tag: str | None = None) -> list[ComposeTemplate]`
  - `update_template(conn, tpl: ComposeTemplate) -> None`
  - `delete_template(conn, template_id: str) -> None`
  - Helper interne `_row_to_template(row: Mapping) -> ComposeTemplate`.

> Les tests DB nécessitent PostgreSQL. Suivre le patron testcontainer existant du projet (cf. `tests/` MCP) ; **skip si Docker absent**. Inclure un test pur (sans DB) pour `_row_to_template`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_db_templates.py
from portal.compose import db
from portal.compose.models import ComposeParam


def test_row_to_template_parses_parameters() -> None:
    row = {
        "id": "t1", "name": "T", "description": "", "tags": ["web"], "version": "1",
        "compose_content": "services: {}",
        "parameters": [{"key": "P", "label": "P", "type": "port", "required": True}],
        "source": "user", "created_at": None, "updated_at": None,
    }
    tpl = db._row_to_template(row)
    assert tpl.id == "t1"
    assert tpl.parameters == [ComposeParam(key="P", label="P", type="port", required=True)]
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_db_templates.py -v` → FAIL (module/fn absent).

- [ ] **Step 3: Write the templates DB layer**

```python
# backend/src/portal/compose/db.py
"""Couche DB SQLAlchemy Core de la galerie compose."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.tables import compose_deployment, compose_deployment_log, compose_template
from .models import ComposeDeployment, ComposeParam, ComposeTemplate


def _row_to_template(row: Mapping[str, Any]) -> ComposeTemplate:
    return ComposeTemplate(
        id=row["id"], name=row["name"], description=row["description"],
        tags=list(row["tags"] or []), version=row["version"],
        compose_content=row["compose_content"],
        parameters=[ComposeParam.model_validate(p) for p in (row["parameters"] or [])],
        source=row["source"], created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )


async def create_template(conn: AsyncConnection, tpl: ComposeTemplate) -> None:
    await conn.execute(
        insert(compose_template).values(
            id=tpl.id, name=tpl.name, description=tpl.description, tags=tpl.tags,
            version=tpl.version, compose_content=tpl.compose_content,
            parameters=[p.model_dump() for p in tpl.parameters], source=tpl.source,
        )
    )


async def get_template(conn: AsyncConnection, template_id: str) -> ComposeTemplate | None:
    row = (
        await conn.execute(select(compose_template).where(compose_template.c.id == template_id))
    ).mappings().first()
    return _row_to_template(row) if row else None


async def list_templates(conn: AsyncConnection, tag: str | None = None) -> list[ComposeTemplate]:
    stmt = select(compose_template).order_by(compose_template.c.name)
    if tag is not None:
        stmt = stmt.where(compose_template.c.tags.any(tag))
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_template(r) for r in rows]


async def update_template(conn: AsyncConnection, tpl: ComposeTemplate) -> None:
    await conn.execute(
        update(compose_template).where(compose_template.c.id == tpl.id).values(
            name=tpl.name, description=tpl.description, tags=tpl.tags, version=tpl.version,
            compose_content=tpl.compose_content,
            parameters=[p.model_dump() for p in tpl.parameters], source=tpl.source,
            updated_at=func.now(),
        )
    )


async def delete_template(conn: AsyncConnection, template_id: str) -> None:
    await conn.execute(delete(compose_template).where(compose_template.c.id == template_id))
```

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/compose/test_db_templates.py -v` → PASS (le test pur passe ; les tests DB éventuels skip si Docker absent).

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/compose/db.py tests/compose/test_db_templates.py && uv run mypy src/portal/compose/db.py
git add backend/src/portal/compose/db.py backend/tests/compose/test_db_templates.py
git commit -m "feat(compose-gallery): couche DB templates (CRUD)"
```

---

### Task 5: Couche DB — déploiements + conflit de ports + logs

**Files:**
- Modify: `backend/src/portal/compose/db.py`
- Test: `backend/tests/compose/test_db_deployments.py`

**Interfaces:**
- Produces (async, `conn: AsyncConnection`) :
  - `create_deployment(conn, dep: ComposeDeployment) -> None`
  - `get_deployment(conn, deployment_id: str) -> ComposeDeployment | None`
  - `list_deployments(conn, *, owner_login: str | None) -> list[ComposeDeployment]` (None = tous, pour admin ; sinon filtré)
  - `update_deployment_status(conn, deployment_id: str, status: str, last_error: str | None = None) -> None`
  - `delete_deployment(conn, deployment_id: str) -> None`
  - `conflicting_ports(conn, node_id: str, ports: list[int]) -> set[int]` — SQL `host_ports && :ports` node-wide, retourne l'intersection occupée.
  - `persist_op_log(conn, deployment_id: str, operation: str, content: str) -> None` (insère un blob `compose_deployment_log`).
  - Helper `_row_to_deployment(row) -> ComposeDeployment`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_db_deployments.py
from portal.compose import db


def test_row_to_deployment() -> None:
    row = {
        "id": "d1", "template_id": "t", "template_version": "1", "node_id": "n",
        "owner_login": "alice", "env_values": {"A": "${vault://x/y}"}, "host_ports": [3000],
        "status": "running", "last_error": None, "created_at": None, "updated_at": None,
    }
    dep = db._row_to_deployment(row)
    assert dep.id == "d1" and dep.host_ports == [3000]
    assert dep.env_values == {"A": "${vault://x/y}"}
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_db_deployments.py -v` → FAIL.

- [ ] **Step 3: Append the deployments DB layer** (dans `db.py`)

```python
def _row_to_deployment(row: Mapping[str, Any]) -> ComposeDeployment:
    return ComposeDeployment(
        id=row["id"], template_id=row["template_id"], template_version=row["template_version"],
        node_id=row["node_id"], owner_login=row["owner_login"],
        env_values=dict(row["env_values"] or {}), host_ports=list(row["host_ports"] or []),
        status=row["status"], last_error=row.get("last_error"),
        created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )


async def create_deployment(conn: AsyncConnection, dep: ComposeDeployment) -> None:
    await conn.execute(
        insert(compose_deployment).values(
            id=dep.id, template_id=dep.template_id, template_version=dep.template_version,
            node_id=dep.node_id, owner_login=dep.owner_login, env_values=dep.env_values,
            host_ports=dep.host_ports, status=dep.status, last_error=dep.last_error,
        )
    )


async def get_deployment(conn: AsyncConnection, deployment_id: str) -> ComposeDeployment | None:
    row = (
        await conn.execute(
            select(compose_deployment).where(compose_deployment.c.id == deployment_id)
        )
    ).mappings().first()
    return _row_to_deployment(row) if row else None


async def list_deployments(
    conn: AsyncConnection, *, owner_login: str | None
) -> list[ComposeDeployment]:
    stmt = select(compose_deployment).order_by(compose_deployment.c.created_at.desc())
    if owner_login is not None:
        stmt = stmt.where(compose_deployment.c.owner_login == owner_login)
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_deployment(r) for r in rows]


async def update_deployment_status(
    conn: AsyncConnection, deployment_id: str, status: str, last_error: str | None = None
) -> None:
    await conn.execute(
        update(compose_deployment).where(compose_deployment.c.id == deployment_id).values(
            status=status, last_error=last_error, updated_at=func.now()
        )
    )


async def delete_deployment(conn: AsyncConnection, deployment_id: str) -> None:
    await conn.execute(
        delete(compose_deployment).where(compose_deployment.c.id == deployment_id)
    )


async def conflicting_ports(
    conn: AsyncConnection, node_id: str, ports: list[int]
) -> set[int]:
    """Ports déjà réservés par un autre déploiement sur ce nœud (node-wide, tous owners)."""
    if not ports:
        return set()
    rows = (
        await conn.execute(
            select(compose_deployment.c.host_ports).where(
                (compose_deployment.c.node_id == node_id)
                & compose_deployment.c.host_ports.op("&&")(ports)
            )
        )
    ).all()
    occupied: set[int] = set()
    requested = set(ports)
    for (hp,) in rows:
        occupied |= requested & set(hp or [])
    return occupied


async def persist_op_log(
    conn: AsyncConnection, deployment_id: str, operation: str, content: str
) -> None:
    await conn.execute(
        insert(compose_deployment_log).values(
            deployment_id=deployment_id, operation=operation, content=content,
            finished_at=func.now(),
        )
    )
```

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/compose/test_db_deployments.py -v` → PASS.

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/compose/db.py tests/compose/test_db_deployments.py && uv run mypy src/portal/compose/db.py
git add backend/src/portal/compose/db.py backend/tests/compose/test_db_deployments.py
git commit -m "feat(compose-gallery): couche DB déploiements + conflit ports + op logs"
```

---

# LOT 3 — Canal nœud + service lifecycle

### Task 6: Canal nœud SSH non-interactif (`host_exec.py`)

**Files:**
- Create: `backend/src/portal/devpod/host_exec.py`
- Test: `backend/tests/compose/test_host_exec.py`

**Interfaces:**
- Consumes : `HostConfig` (`config.models`), `_materialize_system_cert` (`devpod.service`), `host_key_changed` (`devpod.ssh_exec`), `_data_root`/`load_global` (`config.store`).
- Produces :
  - `class HostExecError(Exception)`
  - `def _require_ssh_host(host: HostConfig) -> None` (lève `HostExecError` si `host.type != "ssh"` ou `host.host_cert_slug`/`address` vides).
  - `async def run_host_command(host: HostConfig, command: str, *, timeout: float = 120.0) -> tuple[int, str, str]`
  - `async def write_host_file(host: HostConfig, remote_path: str, content: str) -> None` (encode base64 + `mkdir -p` parent + `base64 -d > path`).

> Mirroir de `ssh_exec.run_ssh_capture` mais ciblant `host.address` avec `-i <materialized key>`. `StrictHostKeyChecking=accept-new` + `UserKnownHostsFile=<_data_root()/keys/hosts_known>` (cohérent `ssh_proxy.py`). Pas de PTY. `remote_path` doit être absolu ou sous `~` ; échappé via `shlex.quote`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_host_exec.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from portal.devpod import host_exec


def _ssh_host():
    return SimpleNamespace(name="n1", type="ssh", address="root@10.0.0.1", host_cert_slug="host.n1.cert")


def _tls_host():
    return SimpleNamespace(name="n2", type="docker-tls", address="", host_cert_slug="")


def test_require_ssh_host_rejects_non_ssh() -> None:
    with pytest.raises(host_exec.HostExecError):
        host_exec._require_ssh_host(_tls_host())


@pytest.mark.asyncio
async def test_run_host_command_invokes_ssh(monkeypatch) -> None:
    monkeypatch.setattr(host_exec, "_materialize_system_cert", AsyncMock(return_value="/tmp/k"))
    captured = {}
    async def fake_capture(argv, **kw):
        captured["argv"] = argv
        return (0, "ok", "")
    monkeypatch.setattr(host_exec, "_ssh_capture", fake_capture)
    rc, out, err = await host_exec.run_host_command(_ssh_host(), "docker compose ps")
    assert (rc, out) == (0, "ok")
    assert "root@10.0.0.1" in captured["argv"] and "docker compose ps" in captured["argv"]


@pytest.mark.asyncio
async def test_write_host_file_base64_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(host_exec, "_materialize_system_cert", AsyncMock(return_value="/tmp/k"))
    seen = {}
    async def fake_run(host, command, *, timeout=120.0):
        seen["cmd"] = command
        return (0, "", "")
    monkeypatch.setattr(host_exec, "run_host_command", fake_run)
    await host_exec.write_host_file(_ssh_host(), "~/devpod-compose/d1/.env", "A=1\n")
    assert "base64 -d" in seen["cmd"] and "mkdir -p" in seen["cmd"]
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_host_exec.py -v` → FAIL.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/portal/devpod/host_exec.py
"""Canal d'exécution non-interactif sur un nœud enrôlé (host type=ssh).

Seul point d'exécution des commandes compose (cadrage spec 26). Mirroir de
ssh_exec.run_ssh_capture mais ciblant host.address (pas un workspace devpod).
"""
from __future__ import annotations

import asyncio
import base64
import posixpath
import shlex

import structlog

from ..config.models import HostConfig
from ..config.store import _data_root
from .service import _materialize_system_cert

_log = structlog.get_logger(__name__)


class HostExecError(Exception):
    """Échec d'exécution sur un nœud (FR)."""


def _require_ssh_host(host: HostConfig) -> None:
    if host.type != "ssh":
        raise HostExecError(f"host {host.name!r} n'est pas de type ssh (v1 ssh-only)")
    if not host.address or not host.host_cert_slug:
        raise HostExecError(f"host {host.name!r} : address/host_cert_slug non configurés")


def _argv(key_path: str, address: str, command: str) -> list[str]:
    known = _data_root() / "keys" / "hosts_known"
    known.parent.mkdir(parents=True, exist_ok=True)
    return [
        "ssh", "-i", key_path,
        "-o", "BatchMode=yes",
        "-o", "LogLevel=ERROR",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={known}",
        "-o", "ConnectTimeout=15",
        address, command,
    ]


async def _ssh_capture(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise HostExecError("commande nœud expirée (timeout)") from None
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


async def run_host_command(
    host: HostConfig, command: str, *, timeout: float = 120.0
) -> tuple[int, str, str]:
    _require_ssh_host(host)
    key_path = await _materialize_system_cert(host.host_cert_slug)
    argv = _argv(key_path, host.address, command)
    return await _ssh_capture(argv, timeout=timeout)


async def write_host_file(host: HostConfig, remote_path: str, content: str) -> None:
    if "\0" in remote_path:
        raise HostExecError("chemin distant invalide")
    parent = posixpath.dirname(remote_path)
    b64 = base64.b64encode(content.encode()).decode()
    cmd = (
        f"mkdir -p {shlex.quote(parent)} && "
        f"printf %s {shlex.quote(b64)} | base64 -d > {shlex.quote(remote_path)}"
    )
    rc, _, err = await run_host_command(host, cmd)
    if rc != 0:
        raise HostExecError(f"écriture distante échouée ({remote_path}): {err}")
```

> Note : `run_host_command` appelle `_ssh_capture` (indirection testable). `write_host_file` appelle `run_host_command`. Les tests mockent l'un ou l'autre. `_materialize_system_cert` est importé au niveau module pour être patchable.

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/compose/test_host_exec.py -v` → PASS (3 tests).

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/devpod/host_exec.py tests/compose/test_host_exec.py && uv run mypy src/portal/devpod/host_exec.py
git add backend/src/portal/devpod/host_exec.py backend/tests/compose/test_host_exec.py
git commit -m "feat(compose-gallery): canal nœud SSH non-interactif (host_exec)"
```

---

### Task 7: Résolution des secrets + génération du `.env` (`env_builder.py`)

**Files:**
- Create: `backend/src/portal/compose/env_builder.py`
- Test: `backend/tests/compose/test_env_builder.py`

**Interfaces:**
- Consumes : `secrets.factory.create_backend`, `secrets.resolver.resolve`/`Scope`, `secrets.types.Secret`, `config.store.load_global`/`safe_user_path`/`load_user`.
- Produces :
  - `def resolve_env_values(login: str, secret_ns: str, env_values: dict[str, str]) -> dict[str, str]` — résout les références `${vault://...}`/`${env://...}` en mémoire (réutilise le patron `_resolve_feature_secrets`). Les valeurs non-référence sont laissées telles quelles.
  - `def render_env_file(resolved: dict[str, str]) -> str` — produit le contenu `.env` (`KEY=VALUE\n`, valeurs échappées si besoin).

> **Invariante** : cette fonction ne s'exécute qu'au `up`, en mémoire. Le résultat (`render_env_file`) n'est jamais persisté en base.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_env_builder.py
from portal.compose import env_builder


def test_render_env_file() -> None:
    out = env_builder.render_env_file({"A": "1", "B": "two"})
    assert out == "A=1\nB=two\n"


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
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_env_builder.py -v` → FAIL.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/portal/compose/env_builder.py
"""Génération du .env d'un déploiement : résolution secrets en mémoire (spec 26 §6)."""
from __future__ import annotations

from ..config.store import load_global, safe_user_path
from ..secrets.factory import create_backend
from ..secrets.resolver import Scope, resolve
from ..secrets.types import Secret


def _resolve_one(login: str, secret_ns: str, value: str) -> str:
    """Résout une valeur (référence vault/env ou littéral) en mémoire."""
    global_cfg = load_global()
    backend = create_backend(
        backend_type=global_cfg.secrets.backend,
        url=global_cfg.secrets.harpocrate.url,
        api_key=global_cfg.secrets.harpocrate.api_key,
        base_path=global_cfg.secrets.harpocrate.base_path,
        user_secrets_path=safe_user_path(login, "secrets.yaml"),
    )
    scope = Scope(kind="user", secret_ns=secret_ns, login=login)
    resolved = resolve(value, scope, backend)
    return resolved.reveal() if isinstance(resolved, Secret) else str(resolved)


def resolve_env_values(login: str, secret_ns: str, env_values: dict[str, str]) -> dict[str, str]:
    return {k: _resolve_one(login, secret_ns, v) for k, v in env_values.items()}


def render_env_file(resolved: dict[str, str]) -> str:
    return "".join(f"{k}={v}\n" for k, v in resolved.items())
```

> `create_backend` rend un backend dont `resolve` ne touche le réseau/disque que pour les vraies références ; un littéral revient tel quel (cf. `resolver.resolve` qui retourne `value` si non-référence). Les tests mockent `_resolve_one` pour rester hors-réseau.

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/compose/test_env_builder.py -v` → PASS (3 tests).

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/compose/env_builder.py tests/compose/test_env_builder.py && uv run mypy src/portal/compose/env_builder.py
git add backend/src/portal/compose/env_builder.py backend/tests/compose/test_env_builder.py
git commit -m "feat(compose-gallery): env builder + résolution secrets en mémoire"
```

---

### Task 8: Détection/suggestion de ports (`ports.py`)

**Files:**
- Create: `backend/src/portal/compose/ports.py`
- Test: `backend/tests/compose/test_ports.py`

**Interfaces:**
- Consumes : `compose.db.conflicting_ports` (Task 5), `host_exec.run_host_command` (Task 6).
- Produces :
  - `class PortConflict(Exception)` avec attributs `conflicts: set[int]` et `suggestion: int | None`.
  - `async def check_ports(conn, host, node_id: str, ports: list[int]) -> None` — lève `PortConflict` si conflit (DB node-wide + check live best-effort `ss -ltn`/`docker ps`), avec un port libre suggéré.
  - `def suggest_free_port(occupied: set[int], start: int = 3000, end: int = 9999) -> int | None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_ports.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from portal.compose import ports


def test_suggest_free_port() -> None:
    assert ports.suggest_free_port({3000, 3001}, start=3000, end=3002) == 3002
    assert ports.suggest_free_port({3000, 3001, 3002}, start=3000, end=3002) is None


@pytest.mark.asyncio
async def test_check_ports_conflict_raises_with_suggestion(monkeypatch) -> None:
    monkeypatch.setattr(ports, "conflicting_ports", AsyncMock(return_value={3000}))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    with pytest.raises(ports.PortConflict) as exc:
        await ports.check_ports(None, host, "n1", [3000])
    assert exc.value.conflicts == {3000}
    assert exc.value.suggestion is not None


@pytest.mark.asyncio
async def test_check_ports_ok(monkeypatch) -> None:
    monkeypatch.setattr(ports, "conflicting_ports", AsyncMock(return_value=set()))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    await ports.check_ports(None, host, "n1", [3000])  # ne lève pas
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_ports.py -v` → FAIL.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/portal/compose/ports.py
"""Détection de conflit et suggestion de port hôte (spec 26 §7)."""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import HostConfig
from ..devpod.host_exec import run_host_command
from .db import conflicting_ports

_LISTEN_RE = re.compile(r":(\d{2,5})\s")


class PortConflict(Exception):
    def __init__(self, conflicts: set[int], suggestion: int | None) -> None:
        self.conflicts = conflicts
        self.suggestion = suggestion
        super().__init__(f"ports en conflit: {sorted(conflicts)} (libre suggéré: {suggestion})")


def suggest_free_port(occupied: set[int], start: int = 3000, end: int = 9999) -> int | None:
    for p in range(start, end + 1):
        if p not in occupied:
            return p
    return None


async def _live_used_ports(host: HostConfig) -> set[int]:
    """Ports en écoute sur le nœud (best-effort ; échec silencieux)."""
    try:
        rc, out, _ = await run_host_command(host, "ss -ltn 2>/dev/null || true", timeout=15.0)
    except Exception:
        return set()
    if rc != 0:
        return set()
    return {int(m) for m in _LISTEN_RE.findall(out) if m.isdigit()}


async def check_ports(
    conn: AsyncConnection, host: HostConfig, node_id: str, ports: list[int]
) -> None:
    if not ports:
        return
    db_conflicts = await conflicting_ports(conn, node_id, ports)
    live = await _live_used_ports(host)
    live_conflicts = set(ports) & live
    conflicts = db_conflicts | live_conflicts
    if conflicts:
        occupied = db_conflicts | live | set(ports)
        raise PortConflict(conflicts, suggest_free_port(occupied))
```

> `conflicting_ports` est importé dans `ports` pour être patchable dans les tests. Le check workspace (`workspace_status.host_port`) sera ajouté à l'ensemble `live`/DB si besoin lors du câblage du service (Task 9) — noté comme enrichissement non bloquant.

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/compose/test_ports.py -v` → PASS (3 tests).

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/compose/ports.py tests/compose/test_ports.py && uv run mypy src/portal/compose/ports.py
git add backend/src/portal/compose/ports.py backend/tests/compose/test_ports.py
git commit -m "feat(compose-gallery): détection conflit ports + suggestion"
```

---

### Task 9: Service lifecycle (`service.py`)

**Files:**
- Create: `backend/src/portal/compose/service.py`
- Test: `backend/tests/compose/test_service.py`

**Interfaces:**
- Consumes : `host_exec.run_host_command`/`write_host_file`, `env_builder.resolve_env_values`/`render_env_file`, `compose.db.*`, `compose.ports.check_ports`, `config.store.load_global` (pour résoudre le `HostConfig` depuis `node_id`).
- Produces (async) :
  - `def _remote_dir(deployment_id: str) -> str` → `f"~/devpod-compose/{deployment_id}"`.
  - `async def deploy(conn, *, deployment_id, template, node_id, owner_login, secret_ns, env_values) -> ComposeDeployment` : valide ports requis, `check_ports`, résout secrets (mémoire), `write_host_file` du compose + `.env`, `docker compose -p <id> --env-file .env up -d`, persiste la ligne + op log, retourne le déploiement (status dérivé).
  - `async def lifecycle(conn, deployment_id, action: Literal["stop","start","restart"]) -> None`.
  - `async def teardown(conn, deployment_id) -> None` : `docker compose -p <id> down -v` + `rm -rf` du dossier distant + suppression ligne.
  - `async def fetch_logs(conn, deployment_id, *, service: str | None, tail: int) -> str` : `docker compose -p <id> logs --no-color --tail=<n> [service]` live.
  - `async def refresh_status(conn, deployment_id) -> str` : `docker compose -p <id> ps --format json` → mappe vers `DeploymentStatus`, met à jour la ligne.
  - `def _host_for_node(node_id: str) -> HostConfig` (résout via `load_global().hosts`, lève si absent / non-ssh).
  - `def _parse_ps_status(ps_json: str) -> str` (pur, testable).

> Toutes les commandes via `run_host_command`. Les ports requis (`host_ports`) sont extraits des `env_values` des params `type=port` du template par l'appelant (route) ou ici — ici on les reçoit déjà calculés via `deploy(... host_ports=...)`. Pour rester simple : `deploy` reçoit `env_values` et la liste `port_params: list[str]` (clés des params type=port) pour en déduire `host_ports`. (Ajuster la signature en conséquence ci-dessous.)

Signature retenue :
```python
async def deploy(
    conn, *, deployment_id: str, template: ComposeTemplate, node_id: str,
    owner_login: str, secret_ns: str, env_values: dict[str, str],
) -> ComposeDeployment
```
`deploy` calcule `host_ports` lui-même : pour chaque `ComposeParam` de `template.parameters` avec `type == "port"`, lit `env_values[param.key]` → int.

- [ ] **Step 1: Write the failing test (pure status parser + deploy happy path mocké)**

```python
# backend/tests/compose/test_service.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from portal.compose import service
from portal.compose.models import ComposeParam, ComposeTemplate


def test_parse_ps_status_running() -> None:
    js = '{"Name":"a","State":"running"}\n{"Name":"b","State":"running"}'
    assert service._parse_ps_status(js) == "running"


def test_parse_ps_status_partial() -> None:
    js = '{"Name":"a","State":"running"}\n{"Name":"b","State":"exited"}'
    assert service._parse_ps_status(js) == "partial"


def test_parse_ps_status_stopped_when_empty() -> None:
    assert service._parse_ps_status("") == "stopped"


def _tpl() -> ComposeTemplate:
    return ComposeTemplate(
        id="browserless", name="B", version="1",
        compose_content='services:\n  b:\n    image: x:1\n    ports: ["${PORT}:3000"]',
        parameters=[ComposeParam(key="PORT", label="Port", type="port", required=True)],
        source="user",
    )


@pytest.mark.asyncio
async def test_deploy_happy_path(monkeypatch) -> None:
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(0, "up done", "")))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())

    dep = await service.deploy(
        None, deployment_id="dep1", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )
    assert dep.host_ports == [3000]
    assert dep.owner_login == "alice"
    service.check_ports.assert_awaited_once()
    assert service.write_host_file.await_count == 2  # compose + .env
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_service.py -v` → FAIL.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/portal/compose/service.py
"""Orchestration du cycle de vie d'un déploiement compose (spec 26 §5)."""
from __future__ import annotations

import json
import shlex
from typing import Literal

import structlog

from ..config.models import HostConfig
from ..config.store import load_global
from ..devpod.host_exec import run_host_command, write_host_file
from .db import (
    create_deployment, delete_deployment, get_deployment, persist_op_log,
    update_deployment_status,
)
from .env_builder import render_env_file, resolve_env_values
from .models import ComposeDeployment, ComposeTemplate
from .ports import check_ports

_log = structlog.get_logger(__name__)


class ComposeServiceError(Exception):
    """Erreur de cycle de vie d'un déploiement (FR)."""


def _remote_dir(deployment_id: str) -> str:
    return f"~/devpod-compose/{deployment_id}"


def _host_for_node(node_id: str) -> HostConfig:
    host = next((h for h in load_global().hosts if h.name == node_id), None)
    if host is None:
        raise ComposeServiceError(f"nœud inconnu: {node_id}")
    if host.type != "ssh":
        raise ComposeServiceError(f"nœud {node_id}: type {host.type} non supporté (v1 ssh-only)")
    return host


def _ports_from_env(template: ComposeTemplate, env_values: dict[str, str]) -> list[int]:
    ports: list[int] = []
    for p in template.parameters:
        if p.type == "port" and p.key in env_values:
            try:
                ports.append(int(env_values[p.key]))
            except ValueError as exc:
                raise ComposeServiceError(f"paramètre port {p.key} non entier") from exc
    return ports


def _parse_ps_status(ps_json: str) -> str:
    states: list[str] = []
    for line in ps_json.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            states.append(str(json.loads(line).get("State", "")))
        except json.JSONDecodeError:
            continue
    if not states:
        return "stopped"
    if all(s == "running" for s in states):
        return "running"
    if any(s == "running" for s in states):
        return "partial"
    return "stopped"


async def deploy(
    conn, *, deployment_id: str, template: ComposeTemplate, node_id: str,
    owner_login: str, secret_ns: str, env_values: dict[str, str],
) -> ComposeDeployment:
    host = _host_for_node(node_id)
    host_ports = _ports_from_env(template, env_values)
    await check_ports(conn, host, node_id, host_ports)

    resolved = resolve_env_values(owner_login, secret_ns, env_values)  # mémoire uniquement
    rdir = _remote_dir(deployment_id)
    await write_host_file(host, f"{rdir}/docker-compose.yml", template.compose_content)
    await write_host_file(host, f"{rdir}/.env", render_env_file(resolved))

    cmd = (
        f"cd {shlex.quote(rdir)} && "
        f"docker compose --env-file .env -p {shlex.quote(deployment_id)} up -d"
    )
    rc, out, err = await run_host_command(host, cmd, timeout=600.0)
    status = "running" if rc == 0 else "error"

    dep = ComposeDeployment(
        id=deployment_id, template_id=template.id, template_version=template.version,
        node_id=node_id, owner_login=owner_login, env_values=env_values,  # refs, jamais résolu
        host_ports=host_ports, status=status,
        last_error=None if rc == 0 else (err or out)[:2000],
    )
    await create_deployment(conn, dep)
    await persist_op_log(conn, deployment_id, "up", out + ("\n" + err if err else ""))
    if rc != 0:
        raise ComposeServiceError(f"docker compose up échoué: {(err or out)[:500]}")
    return dep


async def lifecycle(conn, deployment_id: str, action: Literal["stop", "start", "restart"]) -> None:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    rc, out, err = await run_host_command(
        host, f"docker compose -p {shlex.quote(deployment_id)} {action}", timeout=300.0
    )
    await persist_op_log(conn, deployment_id, action, out + ("\n" + err if err else ""))
    if rc != 0:
        await update_deployment_status(conn, deployment_id, "error", (err or out)[:2000])
        raise ComposeServiceError(f"docker compose {action} échoué: {(err or out)[:500]}")
    await refresh_status(conn, deployment_id)


async def teardown(conn, deployment_id: str) -> None:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    rdir = _remote_dir(deployment_id)
    rc, out, err = await run_host_command(
        host,
        f"docker compose -p {shlex.quote(deployment_id)} down -v ; rm -rf {shlex.quote(rdir)}",
        timeout=300.0,
    )
    await persist_op_log(conn, deployment_id, "down", out + ("\n" + err if err else ""))
    await delete_deployment(conn, deployment_id)


async def fetch_logs(conn, deployment_id: str, *, service: str | None, tail: int) -> str:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    svc = f" {shlex.quote(service)}" if service else ""
    cmd = (
        f"docker compose -p {shlex.quote(deployment_id)} logs --no-color "
        f"--tail={int(tail)}{svc}"
    )
    _, out, err = await run_host_command(host, cmd, timeout=60.0)
    return out + ("\n" + err if err else "")


async def refresh_status(conn, deployment_id: str) -> str:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    rc, out, _ = await run_host_command(
        host, f"docker compose -p {shlex.quote(deployment_id)} ps --format json", timeout=60.0
    )
    status = _parse_ps_status(out) if rc == 0 else "error"
    await update_deployment_status(conn, deployment_id, status)
    return status
```

> Les imports de `create_deployment`/`persist_op_log`/`check_ports`/`resolve_env_values`/`run_host_command`/`write_host_file`/`_host_for_node` sont au niveau module pour être patchables (cf. test). `deploy` reçoit `conn` non typé strict ici (`AsyncConnection`) — annoter `conn: AsyncConnection` à l'implémentation (import depuis `sqlalchemy.ext.asyncio`).

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/compose/test_service.py -v` → PASS (4 tests). Ajuster les annotations `conn: AsyncConnection` pour mypy.

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/portal/compose/service.py tests/compose/test_service.py && uv run mypy src/portal/compose/service.py
git add backend/src/portal/compose/service.py backend/tests/compose/test_service.py
git commit -m "feat(compose-gallery): service lifecycle (deploy/lifecycle/teardown/logs/status)"
```

---

# LOT 4 — Routes API

### Task 10: Routes templates (admin) + schemas

**Files:**
- Create: `backend/src/portal/routes/compose.py`, `backend/src/portal/schemas/compose.py`
- Test: `backend/tests/compose/test_routes_templates.py`

**Interfaces:**
- Consumes : `auth.rbac.require_admin`/`require_user`/`UserInfo`, `db.engine.get_conn`, `compose.db.*`, `compose.validation.validate_template`, `compose.models.*`.
- Produces : routes `GET/POST/PUT/DELETE /api/compose/templates[...]` (admin). DTOs dans `schemas/compose.py` : `TemplateCreateBody`, `TemplateUpdateBody`, `TemplateOut` (incluant `warnings: list[str]` au create/update).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_routes_templates.py
import pytest
from portal.schemas import compose as sc


def test_template_create_body_validates() -> None:
    body = sc.TemplateCreateBody(
        id="browserless", name="Browserless", version="1",
        compose_content='services:\n  b:\n    image: x:1\n    ports: ["${P}:3000"]',
        parameters=[{"key": "P", "label": "Port", "type": "port", "required": True}],
    )
    assert body.id == "browserless"


def test_template_create_body_forbids_extra() -> None:
    with pytest.raises(Exception):
        sc.TemplateCreateBody(id="x", name="X", version="1", compose_content="services: {}", bogus=1)
```

> Les tests d'intégration de route (TestClient + DB) suivent le patron du projet et **skip si Docker absent** ; ce test couvre les DTOs (pur). Ajouter, si le patron TestClient existe sans `create_app` (cf. limitation fcntl), des tests de route mockant `compose.db`/`compose.service` ; sinon, les routes seront validées sur CI.

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_routes_templates.py -v` → FAIL.

- [ ] **Step 3: Write schemas**

```python
# backend/src/portal/schemas/compose.py
"""DTOs API de la galerie compose."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..compose.models import ComposeParam, DeploymentStatus, TemplateSource


class TemplateCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str = ""
    tags: list[str] = []
    version: str
    compose_content: str
    parameters: list[ComposeParam] = []
    source: TemplateSource = "user"


class TemplateUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    tags: list[str] = []
    version: str
    compose_content: str
    parameters: list[ComposeParam] = []
    source: TemplateSource = "user"


class DeploymentCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str
    node_id: str
    name: str  # slug du déploiement
    env_values: dict[str, str] = {}


class DeploymentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    template_id: str
    template_version: str
    node_id: str
    owner_login: str
    host_ports: list[int]
    status: DeploymentStatus
    last_error: str | None = None
```

- [ ] **Step 4: Write the templates routes**

```python
# backend/src/portal/routes/compose.py
"""Routes /api/compose : templates (admin) + déploiements (dev)."""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..compose import db as cdb
from ..compose.models import ComposeTemplate, validate_slug
from ..compose.validation import TemplateValidationError, validate_template
from ..db.engine import get_conn
from ..schemas.compose import TemplateCreateBody, TemplateUpdateBody

_log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/compose", tags=["compose"])


@router.get("/templates")
async def list_templates(
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    tag: str | None = Query(default=None),
) -> list[dict]:
    return [t.model_dump(mode="json") for t in await cdb.list_templates(conn, tag)]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict:
    tpl = await cdb.get_template(conn, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template inconnu")
    return tpl.model_dump(mode="json")


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateCreateBody,
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict:
    try:
        validate_slug(body.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if await cdb.get_template(conn, body.id) is not None:
        raise HTTPException(status_code=409, detail=f"template {body.id!r} existe déjà")
    try:
        warnings = validate_template(body.compose_content, body.parameters)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tpl = ComposeTemplate(**body.model_dump())
    await cdb.create_template(conn, tpl)
    return {"template": tpl.model_dump(mode="json"), "warnings": warnings}


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdateBody,
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict:
    if await cdb.get_template(conn, template_id) is None:
        raise HTTPException(status_code=404, detail="template inconnu")
    try:
        warnings = validate_template(body.compose_content, body.parameters)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tpl = ComposeTemplate(id=template_id, **body.model_dump())
    await cdb.update_template(conn, tpl)
    return {"template": tpl.model_dump(mode="json"), "warnings": warnings}


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> None:
    await cdb.delete_template(conn, template_id)
```

- [ ] **Step 5: Run** `cd backend && uv run pytest tests/compose/test_routes_templates.py -v` → PASS (DTOs). Lint + mypy.

- [ ] **Step 6: Commit**

```bash
cd backend && uv run ruff check src/portal/routes/compose.py src/portal/schemas/compose.py tests/compose/test_routes_templates.py && uv run mypy src/portal/routes/compose.py src/portal/schemas/compose.py
git add backend/src/portal/routes/compose.py backend/src/portal/schemas/compose.py backend/tests/compose/test_routes_templates.py
git commit -m "feat(compose-gallery): routes templates (admin) + DTOs"
```

---

### Task 11: Routes déploiements (dev + ownership) + montage

**Files:**
- Modify: `backend/src/portal/routes/compose.py`, `backend/src/portal/app.py` (montage du router)
- Test: `backend/tests/compose/test_routes_deployments.py`

**Interfaces:**
- Consumes : `compose.service.*`, `compose.ports.PortConflict`, `compose.models.validate_slug`, `config.store.load_user` (pour `secret_ns`).
- Produces : routes deployments. Helper `_require_owned(conn, deployment_id, user) -> ComposeDeployment` (404 si absent ; 403 si `owner_login != user.login` et non-admin).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_routes_deployments.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from portal.routes import compose as r


@pytest.mark.asyncio
async def test_require_owned_forbids_foreign(monkeypatch) -> None:
    dep = SimpleNamespace(id="d1", owner_login="bob")
    monkeypatch.setattr(r.cdb, "get_deployment", AsyncMock(return_value=dep))
    user = SimpleNamespace(login="alice", roles=["dev"])
    with pytest.raises(r.HTTPException) as exc:
        await r._require_owned(None, "d1", user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_owned_admin_sees_all(monkeypatch) -> None:
    dep = SimpleNamespace(id="d1", owner_login="bob")
    monkeypatch.setattr(r.cdb, "get_deployment", AsyncMock(return_value=dep))
    user = SimpleNamespace(login="alice", roles=["admin"])
    assert await r._require_owned(None, "d1", user) is dep
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_routes_deployments.py -v` → FAIL.

- [ ] **Step 3: Append the deployments routes** (dans `routes/compose.py`)

```python
# imports additionnels en tête de routes/compose.py :
from ..compose import service as csvc
from ..compose.ports import PortConflict
from ..compose.service import ComposeServiceError
from ..config.store import load_user
from ..schemas.compose import DeploymentCreateBody


def _is_admin(user: UserInfo) -> bool:
    return "admin" in user.roles


async def _require_owned(conn: AsyncConnection, deployment_id: str, user: UserInfo):
    dep = await cdb.get_deployment(conn, deployment_id)
    if dep is None:
        raise HTTPException(status_code=404, detail="déploiement inconnu")
    if dep.owner_login != user.login and not _is_admin(user):
        raise HTTPException(status_code=403, detail="déploiement d'un autre utilisateur")
    return dep


@router.get("/deployments")
async def list_deployments(
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> list[dict]:
    owner = None if _is_admin(user) else user.login
    deps = await cdb.list_deployments(conn, owner_login=owner)
    return [d.model_dump(mode="json") for d in deps]


@router.post("/deployments", status_code=201)
async def create_deployment(
    body: DeploymentCreateBody,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict:
    try:
        validate_slug(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tpl = await cdb.get_template(conn, body.template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template inconnu")
    missing = [p.key for p in tpl.parameters if p.required and p.key not in body.env_values]
    if missing:
        raise HTTPException(status_code=422, detail=f"paramètres requis manquants: {missing}")
    if await cdb.get_deployment(conn, body.name) is not None:
        raise HTTPException(status_code=409, detail=f"déploiement {body.name!r} existe déjà")
    user_cfg = await load_user(user.login)
    try:
        dep = await csvc.deploy(
            conn, deployment_id=body.name, template=tpl, node_id=body.node_id,
            owner_login=user.login, secret_ns=user_cfg.secret_ns, env_values=body.env_values,
        )
    except PortConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "port_conflict", "conflicts": sorted(exc.conflicts),
                    "suggestion": exc.suggestion},
        ) from exc
    except ComposeServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dep.model_dump(mode="json")


@router.post("/deployments/{deployment_id}/{action}")
async def deployment_action(
    deployment_id: str, action: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict:
    if action not in ("stop", "start", "restart"):
        raise HTTPException(status_code=422, detail="action invalide")
    await _require_owned(conn, deployment_id, user)
    try:
        await csvc.lifecycle(conn, deployment_id, action)  # type: ignore[arg-type]
    except ComposeServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"deployment_id": deployment_id, "action": action}


@router.delete("/deployments/{deployment_id}", status_code=204)
async def delete_deployment(
    deployment_id: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> None:
    await _require_owned(conn, deployment_id, user)
    await csvc.teardown(conn, deployment_id)


@router.get("/deployments/{deployment_id}/logs")
async def deployment_logs(
    deployment_id: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    service: str | None = Query(default=None),
    tail: int = Query(default=200, ge=1, le=5000),
) -> dict:
    await _require_owned(conn, deployment_id, user)
    return {"output": await csvc.fetch_logs(conn, deployment_id, service=service, tail=tail)}


@router.get("/deployments/{deployment_id}/status")
async def deployment_status(
    deployment_id: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict:
    await _require_owned(conn, deployment_id, user)
    return {"deployment_id": deployment_id, "status": await csvc.refresh_status(conn, deployment_id)}
```

- [ ] **Step 4: Mount the router** dans `backend/src/portal/app.py`

Repérer où les autres routers sont inclus (`app.include_router(...)`) et ajouter :
```python
from .routes import compose as compose_routes
app.include_router(compose_routes.router)
```
(Suivre exactement le style d'inclusion existant — préfixe déjà dans le router.)

- [ ] **Step 5: Run** `cd backend && uv run pytest tests/compose/test_routes_deployments.py -v` → PASS (2 tests). Lint + mypy sur les fichiers touchés.

- [ ] **Step 6: Full compose suite + commit**

```bash
cd backend && uv run ruff check src/portal/compose/ src/portal/routes/compose.py src/portal/schemas/compose.py tests/compose/ && uv run mypy src/portal/compose/ src/portal/routes/compose.py && uv run pytest tests/compose/ -q
git add backend/src/portal/routes/compose.py backend/src/portal/app.py backend/tests/compose/test_routes_deployments.py
git commit -m "feat(compose-gallery): routes déploiements (dev+ownership) + montage router"
```

---

## Self-Review (effectuée)

**Spec coverage (spec 26 + cadrage)** :
- Templates CRUD + validation/lint → Task 3, 4, 10. ✓
- Déploiements instanciation (`.env` + up) → Task 7, 9, 11. ✓
- Cycle de vie (stop/start/restart/down/logs/status) → Task 9, 11. ✓
- Conflit de ports (SQL `&&` node-wide + live + 409 + suggestion) → Task 5, 8, 11. ✓
- Secrets Harpocrate référence/injection en mémoire → Task 7, 9 ; invariante DB (refs only) respectée dans `deploy` (`env_values=env_values`, jamais `resolved`). ✓
- Canal nœud SSH non-interactif → Task 6. ✓
- Persistance SQLAlchemy Core + Alembic 030 → Task 1. ✓
- RBAC templates admin / deployments dev + ownership → Task 10, 11. ✓
- Logs services live + op logs persistés → Task 5 (`persist_op_log`), 9, 11. ✓
- Hors v1 (docker-tls, multi-nœuds, build, durcissement .env) → non implémenté. ✓

**Placeholder scan** : pas de TODO/TBD ; code complet à chaque step. Deux points de vigilance signalés explicitement (lint `:latest` à affiner si un cas échappe — Task 3 step 4 ; montage router à aligner sur le style existant — Task 11 step 4) ne sont pas des placeholders mais des contrôles d'exactitude.

**Type consistency** : `run_host_command`/`write_host_file` (Task 6) consommés par `ports`/`service` (Task 8/9) ; `conflicting_ports`/`persist_op_log`/`create_deployment`/`get_deployment` (Task 5) consommés par `service`/routes ; `validate_template`→`TemplateValidationError` (Task 3) consommés par routes (Task 10) ; `deploy(...)` signature cohérente Task 9 ↔ route Task 11 ; `secret_ns` via `load_user(login).secret_ns`.

**Limite environnement (rappel)** : les tests d'intégration de route/DB nécessitant `create_app()`/PostgreSQL ne tournent pas en local (fcntl Unix-only + Docker absent) → validation sur Linux/CI. Tous les tests de ce plan sont conçus pour passer en local en **mockant le canal nœud et la DB** (pur), conformément au patron projet.

---

## Execution Handoff

Plan backend complet et sauvegardé dans `docs/superpowers/plans/2026-06-27-compose-gallery-backend.md`. Le **frontend fera l'objet d'un plan séparé** (`features/compose/` React) une fois le backend vert sur CI.

Deux options d'exécution :
1. **Subagent-Driven (recommandé)** — un subagent frais par tâche, review entre chaque.
2. **Inline** — exécution dans cette session via executing-plans, par lots avec checkpoints.

Quelle approche ?
