# backend/src/portal/recipes/models.py
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_RECIPE_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")
_SECRET_PATH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,127}$")
_ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
# Dot-path (sous-ensemble de JSONPath) : $.permissions, $.a.b.c — pas de wildcard.
_NODE_RE = re.compile(r"^\$(\.[A-Za-z0-9_-]+)+$")


def _has_traversal(path: str) -> bool:
    """True si un segment du chemin est '..' (path traversal)."""
    return ".." in path.replace("\\", "/").split("/")


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# Familles de machines, reprises telles quelles de `HostConfig.usage` : une
# recette de host ne peut viser que des destinations que le portail connaît
# déjà. Toute divergence entre les deux listes rendrait une recette applicable
# à une famille inexistante — ou l'inverse.
HostUsage = Literal["workspaces", "tests", "portail", "ressources", "autres"]


# Chemin absolu, sans métacaractère shell : ces valeurs finissent dans une
# commande exécutée à distance avec les droits d'administration.
_ABS_PATH_RE = re.compile(r"^/[A-Za-z0-9._/ -]{0,255}$")
_ARCH_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class RecipePrecondition(BaseModel):
    """Ce qu'une machine doit offrir pour qu'une recette de host y soit posée.

    Vérifiée avant tout téléchargement : une recette de 20 Go qui échoue en
    cours de route laisse la machine à moitié faite et l'administrateur sans
    explication.
    """

    model_config = ConfigDict(extra="forbid")

    # Espace libre exigé, en Go, sur `disk_path`.
    disk_free_gb: int | None = Field(default=None, ge=1)
    disk_path: str = "/"
    # Chemin qui doit exister (ex. /dev/kvm pour l'émulateur Android).
    path_exists: str = ""
    # Chemin qui doit être lisible ET inscriptible par l'utilisateur qui
    # applique. Un fichier de périphérique peut exister sans être accessible :
    # /dev/kvm appartient au groupe `kvm`, et l'émulateur échoue sans y être.
    path_writable: str = ""
    # Architecture attendue, telle que `uname -m` la rapporte.
    arch: str = ""

    @field_validator("disk_path", "path_exists", "path_writable")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if v and not _ABS_PATH_RE.fullmatch(v):
            raise ValueError(f"path {v!r} must be absolute and free of shell metacharacters")
        if _has_traversal(v):
            raise ValueError(f"path {v!r} must not contain '..'")
        return v

    @field_validator("arch")
    @classmethod
    def validate_arch(cls, v: str) -> str:
        if v and not _ARCH_RE.fullmatch(v):
            raise ValueError(f"arch {v!r} must match {_ARCH_RE.pattern}")
        return v

    @model_validator(mode="after")
    def check_not_empty(self) -> RecipePrecondition:
        """Une précondition qui ne vérifie rien passerait toujours : c'est une
        fausse garantie, pire que pas de garantie du tout."""
        if (
            self.disk_free_gb is None
            and not self.path_exists
            and not self.path_writable
            and not self.arch
        ):
            raise ValueError(
                "a precondition must check at least one of: "
                "disk_free_gb, path_exists, path_writable, arch"
            )
        return self


class RecipeOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "string"
    default: str = ""
    description: str = ""


class SecretRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    env: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not _SECRET_PATH_RE.fullmatch(v):
            raise ValueError(f"secret path {v!r} contient des caractères invalides")
        return v

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if not _ENV_VAR_RE.fullmatch(v):
            raise ValueError(f"env var name {v!r} must match ^[A-Z][A-Z0-9_]{{0,63}}$")
        return v


class MemoryVolumeMappingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str  # chemin absolu dans le conteneur (ex. /home/vscode/.claude)


class MemoryVolumeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # suffixe du nom Docker volume (ex. "claude-code" → "{ws_id}-claude-code")
    optional: bool = True  # si True, l'utilisateur choisit d'activer ; si False, toujours actif
    mapping: MemoryVolumeMappingSpec


class CopyOp(BaseModel):
    """Copie d'un fichier/dossier embarqué dans la recipe vers le conteneur."""

    model_config = ConfigDict(extra="forbid")

    source: str  # relatif au dossier de la recipe (ex. files/claude)
    target: str  # chemin absolu dans le conteneur

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v.startswith("/") or _has_traversal(v):
            raise ValueError(f"copy source {v!r} must be relative and free of '..' segments")
        return v

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if not v.startswith("/") or _has_traversal(v):
            raise ValueError(f"copy target {v!r} must be absolute and free of '..' segments")
        return v


class TransformTarget(BaseModel):
    """Cible d'une opération transform : un nœud d'un fichier JSON du conteneur."""

    model_config = ConfigDict(extra="forbid")

    file: str  # chemin absolu d'un fichier JSON dans le conteneur
    node: str  # dot-path ($.permissions, $.a.b)

    @field_validator("file")
    @classmethod
    def validate_file(cls, v: str) -> str:
        if not v.startswith("/") or _has_traversal(v):
            raise ValueError(f"transform target file {v!r} must be absolute and free of '..'")
        return v

    @field_validator("node")
    @classmethod
    def validate_node(cls, v: str) -> str:
        if not _NODE_RE.fullmatch(v):
            raise ValueError(f"transform target node {v!r} must be a dot-path like $.a.b")
        return v


class TransformOp(BaseModel):
    """Opération sur un nœud JSON : replace (pose/écrase) ou remove (supprime)."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["replace", "remove"]
    target: TransformTarget
    value: Any = None

    @model_validator(mode="before")
    @classmethod
    def _check_value_presence(cls, data: Any) -> Any:
        if isinstance(data, dict):
            op = data.get("op")
            has_value = "value" in data
            if op == "replace" and not has_value:
                raise ValueError("transform op 'replace' requires a 'value'")
            if op == "remove" and has_value:
                raise ValueError("transform op 'remove' must not carry a 'value'")
        return data


class RecipeMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _normalize_hyphenated_keys(cls, data: Any) -> Any:
        if isinstance(data, dict) and "memory-volume" in data:
            data = dict(data)
            data["memory_volume"] = data.pop("memory-volume")
        return data

    id: str
    key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["install", "start", "initialize"] = "install"
    # Où la recette s'installe. `type` dit QUAND (install/start/initialize),
    # `scope` dit OÙ — les deux sont orthogonaux, d'où un champ séparé plutôt
    # qu'un quatrième type.
    #
    # `workspace` par défaut : tout le catalogue existant reste valide et
    # inchangé, sans migration. Une recette de host s'exécute sur la machine
    # avec les droits d'administration, là où le conteneur bornait les dégâts.
    scope: Literal["workspace", "host"] = "workspace"
    # Familles de machines que la recette sait viser (scope=host uniquement).
    host_usages: list[HostUsage] = Field(default_factory=list)
    # Vérifiées sur la machine avant tout téléchargement (scope=host uniquement).
    preconditions: list[RecipePrecondition] = Field(default_factory=list)
    version: str = "1.0.0"
    description: str = ""
    options: dict[str, RecipeOption] = Field(default_factory=dict)
    requires_secrets: list[SecretRef] = Field(default_factory=list)
    # Liste de GUIDs (key) des recipes à installer avant celle-ci.
    # Auto-incluses même si non sélectionnées par l'utilisateur.
    installs_after: list[str] = Field(default_factory=list)
    memory_volume: MemoryVolumeSpec | None = None
    # Opérations des recipes type=initialize (déclenchées à la demande).
    # `copies` est exposé en YAML sous la clé `copy` (alias) ; le nom Python évite
    # de masquer BaseModel.copy().
    copies: list[CopyOp] = Field(default_factory=list, alias="copy")
    transform: list[TransformOp] = Field(default_factory=list)

    @field_validator("host_usages")
    @classmethod
    def dedupe_host_usages(cls, v: list[str]) -> list[str]:
        """Dédoublonne en gardant le premier ordre d'apparition."""
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def check_scope_coherence(self) -> RecipeMeta:
        """Portée et familles vont ensemble, dans les deux sens.

        Sans famille déclarée, une recette de host serait applicable partout ou
        nulle part — deux mauvaises réponses pour de l'exécution privilégiée.
        Et des familles sur une recette de workspace trahissent une méta
        incohérente : on la refuse plutôt que d'ignorer le champ en silence.
        """
        if self.scope == "host" and not self.host_usages:
            raise ValueError("host_usages must list at least one family when scope is 'host'")
        if self.scope != "host" and self.host_usages:
            raise ValueError("host_usages requires scope 'host'")
        # Hors scope host, elles ne seraient jamais vérifiées : la déclaration
        # serait trompeuse.
        if self.scope != "host" and self.preconditions:
            raise ValueError("preconditions require scope 'host'")
        return self

    def applies_to_host(self, usage: str) -> bool:
        """La recette peut-elle viser une machine de cette famille ?

        Faux pour toute recette de workspace : c'est le garde-fou qui empêche le
        catalogue existant de devenir applicable sur une machine par accident.
        """
        return self.scope == "host" and usage in self.host_usages

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _RECIPE_ID_RE.fullmatch(v):
            raise ValueError(f"id {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _UUID_RE.fullmatch(v):
            raise ValueError(f"key {v!r} must be a valid UUID")
        return v.lower()

    @field_validator("installs_after", mode="before")
    @classmethod
    def validate_installs_after(cls, v: list[str]) -> list[str]:
        for item in v:
            if not _UUID_RE.fullmatch(item):
                raise ValueError(f"installs_after item {item!r} must be a valid UUID (recipe key)")
        return [i.lower() for i in v]

    @field_validator("requires_secrets", mode="before")
    @classmethod
    def normalize_secret_refs(cls, v: list[Any]) -> list[dict[str, str]]:
        """Accepte string courte ou dict explicite."""
        result = []
        for item in v:
            if isinstance(item, str):
                env = item.upper().replace("/", "_").replace("-", "_")
                result.append({"path": item, "env": env})
            else:
                result.append(item)
        return result

    @classmethod
    def from_yaml(cls, path: str | Path) -> RecipeMeta:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)
