# Chantier — Profils VSCode : CRUD (YAML, partagé + fork) + éditeur

> Dépôt **devpod-ui**. Dernier chantier de la fonctionnalité « Profil VSCode ».
> Backend : stockage YAML des profils (aucune DB), portée **partagé** (admin) + **user**, fork.
> Frontend : liste + éditeur de profil **embarquant le `PluginBrowser`** déjà livré.
> Hors périmètre : sélection d'un profil à la création d'un workspace (intégration `WorkspaceCreate`
> + wrapper DevPod) — chantier suivant.

## 0. Préalables

1. Lis `CLAUDE.md`, `LESSONS.md`. **Mime les patterns existants** :
   - backend : le registre de recettes (`16_M7_recipes.md` / la feature recipes) pour le pattern
     **repository YAML + curation admin** ; la résolution du répertoire user (`users/<login>/`,
     issue de M2) ; la dépendance d'auth existante (`current_user`, `require_admin`).
   - frontend : `@/features/recipes` (catalogue + admin) et `@/features/workspaces` (liste +
     `WorkspaceCreate`) pour le style des listes, formulaires, mutations React Query, toasts.
2. Branche `dev`. Commits conventionnels **FR**. Aucun fichier > 300 lignes.
3. Principes non négociables du portail : **pas de DB**, **isolation user par répertoire**,
   **hosts/partagé = admin only**. Écritures YAML **atomiques** (tmp + `os.replace`).

## 1. Modèle & stockage

Schéma d'un profil (le `slug` = nom de fichier, dérivé de `name`) :

```yaml
# <slug>.yaml
name: Frontend React
description: Stack React + Prettier + ESLint
extensions:
  - esbenp.prettier-vscode
  - dbaeumer.vscode-eslint
settings: {}        # conservé, non édité par l'UI au MVP
```

Emplacements (deux portées) :
- **partagé** (admin) : `/data/profiles/<slug>.yaml`
- **user** : `/data/users/<login>/profiles/<slug>.yaml`

Le `scope` (`"shared"` | `"user"`) **n'est pas stocké** dans le fichier : il découle de l'emplacement.

## 2. Backend — code de référence

### `models.py`

```python
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

Scope = Literal["shared", "user"]


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    extensions: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class Profile(ProfileBody):
    slug: str
    scope: Scope


class ProfileSummary(BaseModel):
    slug: str
    scope: Scope
    name: str
    description: str
    extension_count: int
    editable: bool          # True si l'appelant peut modifier (user = ses profils ; admin = tout)
```

### `repository.py`

```python
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import structlog
import yaml

from .models import Profile, ProfileBody, ProfileSummary, Scope

log = structlog.get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "profil"


class ProfileError(Exception):
    """Erreur métier (introuvable, conflit, permission)."""

    def __init__(self, code: str) -> None:  # "not_found" | "conflict" | "forbidden"
        super().__init__(code)
        self.code = code


class ProfileRepository:
    def __init__(self, data_dir: Path) -> None:
        self._data = data_dir

    def _dir(self, scope: Scope, login: str | None) -> Path:
        if scope == "shared":
            return self._data / "profiles"
        if not login:
            raise ProfileError("forbidden")
        return self._data / "users" / login / "profiles"

    def _path(self, scope: Scope, slug: str, login: str | None) -> Path:
        return self._dir(scope, login) / f"{slug}.yaml"

    def list(self, login: str, is_admin: bool) -> list[ProfileSummary]:
        out: list[ProfileSummary] = []
        for scope, base in (("shared", self._dir("shared", None)), ("user", self._dir("user", login))):
            if not base.is_dir():
                continue
            for f in sorted(base.glob("*.yaml")):
                p = self._read(f, scope, f.stem)
                editable = is_admin if scope == "shared" else True
                out.append(ProfileSummary(
                    slug=p.slug, scope=p.scope, name=p.name,
                    description=p.description, extension_count=len(p.extensions),
                    editable=editable,
                ))
        return out

    def get(self, scope: Scope, slug: str, login: str) -> Profile:
        path = self._path(scope, slug, None if scope == "shared" else login)
        if not path.is_file():
            raise ProfileError("not_found")
        return self._read(path, scope, slug)

    def create(self, login: str, body: ProfileBody) -> Profile:
        return self._write("user", login, slugify(body.name), body, allow_overwrite=False)

    def update(self, login: str, slug: str, body: ProfileBody) -> Profile:
        if not self._path("user", slug, login).is_file():
            raise ProfileError("not_found")
        return self._write("user", login, slug, body, allow_overwrite=True)

    def delete(self, login: str, slug: str) -> None:
        path = self._path("user", slug, login)
        if not path.is_file():
            raise ProfileError("not_found")
        path.unlink()

    def fork(self, login: str, shared_slug: str) -> Profile:
        src = self.get("shared", shared_slug, login)
        body = ProfileBody(**src.model_dump(include={"name", "description", "extensions", "settings"}))
        return self._write("user", login, slugify(src.name), body, allow_overwrite=False)

    # --- admin (profils partagés) ---
    def create_shared(self, body: ProfileBody) -> Profile:
        return self._write("shared", None, slugify(body.name), body, allow_overwrite=False)

    def update_shared(self, slug: str, body: ProfileBody) -> Profile:
        if not self._path("shared", slug, None).is_file():
            raise ProfileError("not_found")
        return self._write("shared", None, slug, body, allow_overwrite=True)

    def delete_shared(self, slug: str) -> None:
        path = self._path("shared", slug, None)
        if not path.is_file():
            raise ProfileError("not_found")
        path.unlink()

    # --- internes ---
    def _read(self, path: Path, scope: Scope, slug: str) -> Profile:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Profile(slug=slug, scope=scope, **ProfileBody(**raw).model_dump())

    def _write(self, scope: Scope, login: str | None, slug: str,
               body: ProfileBody, *, allow_overwrite: bool) -> Profile:
        base = self._dir(scope, login)
        base.mkdir(parents=True, exist_ok=True)
        slug = self._unique_slug(base, slug, allow_overwrite)
        path = base / f"{slug}.yaml"
        self._atomic_dump(path, body)
        log.info("profile.write", scope=scope, slug=slug)
        return Profile(slug=slug, scope=scope, **body.model_dump())

    @staticmethod
    def _unique_slug(base: Path, slug: str, allow_overwrite: bool) -> str:
        if allow_overwrite or not (base / f"{slug}.yaml").exists():
            return slug
        i = 2
        while (base / f"{slug}-{i}.yaml").exists():
            i += 1
        return f"{slug}-{i}"

    @staticmethod
    def _atomic_dump(path: Path, body: ProfileBody) -> None:
        data = yaml.safe_dump(body.model_dump(), allow_unicode=True, sort_keys=False)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            os.path.exists(tmp) and os.unlink(tmp)
            raise
```

### Génération du fragment devcontainer

```python
def to_customizations(profile: Profile) -> dict:
    """Fragment `customizations.vscode` d'un profil (autorité de génération)."""
    return {"vscode": {"extensions": profile.extensions, "settings": profile.settings}}
```

### `api/profiles.py` (extraits — routes user + fork)

Utilise la dépendance d'auth existante. Mappe `ProfileError.code` → HTTP
(`not_found`→404, `conflict`→409, `forbidden`→403).

```python
router = APIRouter(prefix="/api/profiles", tags=["profiles"])

@router.get("", response_model=list[ProfileSummary])
async def list_profiles(user=Depends(current_user), repo: ProfileRepository = Depends(get_repo)):
    return repo.list(user.login, user.is_admin)

@router.get("/{scope}/{slug}", response_model=Profile)
async def get_profile(scope: Scope, slug: str, user=Depends(current_user),
                      repo: ProfileRepository = Depends(get_repo)):
    try:
        return repo.get(scope, slug, user.login)
    except ProfileError as e:
        raise _http(e)

@router.post("", response_model=Profile, status_code=201)
async def create_profile(body: ProfileBody, user=Depends(current_user),
                         repo: ProfileRepository = Depends(get_repo)):
    return repo.create(user.login, body)

@router.put("/{slug}", response_model=Profile)
async def update_profile(slug: str, body: ProfileBody, user=Depends(current_user),
                         repo: ProfileRepository = Depends(get_repo)):
    try:
        return repo.update(user.login, slug, body)
    except ProfileError as e:
        raise _http(e)

@router.delete("/{slug}", status_code=204)
async def delete_profile(slug: str, user=Depends(current_user),
                         repo: ProfileRepository = Depends(get_repo)):
    try:
        repo.delete(user.login, slug)
    except ProfileError as e:
        raise _http(e)

@router.post("/shared/{slug}/fork", response_model=Profile, status_code=201)
async def fork_profile(slug: str, user=Depends(current_user),
                       repo: ProfileRepository = Depends(get_repo)):
    try:
        return repo.fork(user.login, slug)
    except ProfileError as e:
        raise _http(e)
```

**Routes admin partagées** (`POST/PUT/DELETE` sur les profils `shared`) : monte-les sous
`/api/admin/profiles` **derrière `require_admin`**, en miroir exact du pattern admin des recipes
(appelle `create_shared` / `update_shared` / `delete_shared`).

## 3. Frontend — feature `@/features/profiles`

### Évolution depuis le chantier #2

- `/profiles` ne sert plus la page de démo : il affiche désormais la **liste des profils**.
  Supprime `PluginBrowserPage` (route de démo). Le `PluginBrowser` est **conservé** et embarqué
  dans l'éditeur.

### `api/profiles.ts` (types + appels)

Reflète les DTO : `ProfileSummary`, `Profile`, `ProfileBody`, `Scope`. Fonctions :
`listProfiles()`, `getProfile(scope, slug)`, `createProfile(body)`, `updateProfile(slug, body)`,
`deleteProfile(slug)`, `forkProfile(slug)`. Même style de `fetch` typé que `api/plugins.ts`.

### Hooks React Query (mutations + invalidation)

```ts
// hooks/useProfiles.ts
export function useProfiles() {
  return useQuery({ queryKey: ['profiles'], queryFn: listProfiles })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { slug?: string; body: ProfileBody }) =>
      v.slug ? updateProfile(v.slug, v.body) : createProfile(v.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['profiles'] }),
  })
}

export function useForkProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: forkProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['profiles'] }),
  })
}
// idem useDeleteProfile (+ confirmation via Dialog avant suppression)
```

Toasts `sonner` sur succès/erreur ; messages traduits.

### `ProfileList.tsx` (route `/profiles`)

- Deux sections : **Mes profils** (éditables) et **Partagés** (badge, bouton **Forker**).
- Carte profil : `name`, `description`, nombre d'extensions. Actions : Éditer (si `editable`),
  Supprimer (confirmation), Forker (si `scope === 'shared'`).
- Bouton « Nouveau profil » → `/profiles/new`.
- États chargement / vide / erreur, comme `RecipeCatalog`.

### `ProfileEditor.tsx` (routes `/profiles/new` et `/profiles/:slug`)

Pièce maîtresse — embarque le `PluginBrowser` contrôlé :

```tsx
export default function ProfileEditor() {
  const { slug } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const editing = Boolean(slug)
  const { data: existing } = useProfile('user', slug)   // enabled si slug
  const save = useSaveProfile()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [settings] = useState<Record<string, unknown>>({}) // non édité au MVP

  useEffect(() => {
    if (existing) {
      setName(existing.name)
      setDescription(existing.description)
      setSelected(new Set(existing.extensions))
    }
  }, [existing])

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const devcontainerPreview = useMemo(
    () => JSON.stringify(
      { customizations: { vscode: { extensions: [...selected], settings } } },
      null, 2,
    ),
    [selected, settings],
  )

  const onSave = () =>
    save.mutate(
      { slug, body: { name, description, extensions: [...selected], settings } },
      { onSuccess: () => navigate('/profiles') },
    )

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-3 max-w-xl">
        <Label htmlFor="name">{t('profiles.fields.name')}</Label>
        <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
        <Label htmlFor="desc">{t('profiles.fields.description')}</Label>
        <Input id="desc" value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>

      <section>
        <h2 className="mb-2 text-lg font-medium">{t('profiles.plugins.title')}</h2>
        <PluginBrowser selectedIds={selected} onToggle={toggle} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">{t('profiles.preview')}</h2>
        <pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs">{devcontainerPreview}</pre>
      </section>

      <div className="flex gap-2">
        <Button onClick={onSave} disabled={!name.trim() || save.isPending}>
          {t('common.save')}
        </Button>
        <Button variant="ghost" onClick={() => navigate('/profiles')}>{t('common.cancel')}</Button>
      </div>
    </div>
  )
}
```

> Preview : la coloration `prismjs` (déjà en dépendance) est optionnelle ; un `<pre>` stylé suffit
> au MVP. La forme JSON est triviale, donc la générer côté client ne risque pas de diverger du
> backend (`to_customizations` reste l'autorité au moment de la composition workspace).

### `AdminProfiles.tsx` (route `/admin/profiles`, `AdminGuard`)

Curation des profils **partagés** : même éditeur, mais cible les routes `/api/admin/profiles`.
Miroir de `AdminRecipes`. Ajoute l'entrée de nav admin correspondante.

### Routing & i18n

- `router.tsx` : remplace la route démo par
  ```ts
  const ProfileList = lazy(() => import('@/features/profiles/ProfileList'))
  const ProfileEditor = lazy(() => import('@/features/profiles/ProfileEditor'))
  const AdminProfiles = lazy(() => import('@/features/admin/AdminProfiles'))
  // children AppShell :
  { path: '/profiles', element: <Wrap><ProfileList /></Wrap> },
  { path: '/profiles/new', element: <Wrap><ProfileEditor /></Wrap> },
  { path: '/profiles/:slug', element: <Wrap><ProfileEditor /></Wrap> },
  // children admin :
  { path: '/admin/profiles', element: <AdminGuard><Wrap><AdminProfiles /></Wrap></AdminGuard> },
  ```
- i18n (fr + en) : `profiles.title`, `profiles.fields.name|description`, `profiles.preview`,
  `profiles.new`, `profiles.fork`, `profiles.delete.confirm`, `profiles.sections.mine|shared`,
  `profiles.errors.*`, `common.save|cancel`. Aucune chaîne en dur.

## 4. Tests

**Backend (`pytest`)** — repo sur un `tmp_path` :
- create user → fichier YAML écrit, slug dérivé du name.
- collision de slug → suffixe `-2`.
- update / delete / get `not_found`.
- isolation : un user ne voit/écrit pas les profils d'un autre.
- fork d'un partagé → copie indépendante dans la ns user (modifier le partagé n'affecte pas le fork).
- partagé en écriture sans admin → refusé (au niveau route).
- écriture atomique (le fichier final est complet ; pas de `.tmp` résiduel).

**Frontend (`vitest` + MSW)** :
- liste : sections « mes profils » / « partagés », badge + bouton Forker sur les partagés.
- création : remplir name + sélectionner des plugins → POST, redirection, invalidation.
- édition : préremplissage depuis l'existant, sauvegarde.
- suppression : confirmation puis DELETE.
- preview : se met à jour quand la sélection change.

## 5. Definition of Done

- [ ] Repository YAML (partagé + user), écritures **atomiques**, slugify + anti-collision.
- [ ] Routes user (`list/get/create/update/delete/fork`) + routes admin partagées sous `require_admin`.
- [ ] `to_customizations()` livrée et testée.
- [ ] Liste + éditeur ; l'éditeur **embarque `PluginBrowser`** sans le modifier.
- [ ] Preview `devcontainer.json` (fragment) qui reflète la sélection.
- [ ] Route démo du chantier #2 retirée ; `/profiles` = liste.
- [ ] Admin partagés en miroir des recipes, nav admin ajoutée.
- [ ] i18n fr + en complet, aucune chaîne en dur.
- [ ] Tests backend + frontend verts ; TypeScript strict ; eslint propre.
- [ ] Aucun fichier > 300 lignes. Commits conventionnels FR sur `dev`.

## 6. Hors périmètre — le tout dernier pas (chantier suivant)

Fermeture finale de la boucle : dans `WorkspaceCreate`, permettre de **choisir un profil** ; à
la création du workspace, **fusionner `to_customizations(profile)`** dans le `devcontainer.json`
provisionné (en composant avec la Recipe et l'image de base). Cela touche le flux workspace existant
et le wrapper DevPod — à traiter séparément pour ne pas mélanger les préoccupations.
