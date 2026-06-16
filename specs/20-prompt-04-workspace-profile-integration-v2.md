# Chantier final — Boucle fermée : profil → workspace (recalé sur le code réel)

> Dépôt **devpod-ui**, branche `dev`. Sélection d'un **Profil VSCode** à la création d'un
> workspace, fusion de son fragment `customizations.vscode` dans le `devcontainer.json` généré.
> Ce prompt cible les **vrais chemins et signatures** vérifiés sur `dev` (commit de référence
> `dc388d5`). Adapte si le code a bougé, mais la structure ci-dessous est celle observée.

## 0. Contrainte d'architecture à connaître AVANT (importante)

`DevPodService._write_devcontainer` n'est appelé **que pour les hosts `docker-tls`**
(`devpod/service.py::up`, vers la ligne 130). Pour les hosts **SSH**, aucun `devcopourtantainer.json`
n'est généré côté portail (l'agent DevPod est distant ; `--devcontainer-path` y est inexploitable).

**Conséquence :** le profil s'applique exactement là où les **recipes** s'appliquent
aujourd'hui — c'est-à-dire **docker-tls uniquement**. Sur SSH, profil et recipes sont ignorés ;
c'est une limitation préexistante, **hors périmètre de ce chantier**. Ne tente pas de la résoudre
ici (pas d'install runtime via `postCreateCommand` — ce serait le contournement qu'on s'interdit).
Documente ce comportement dans `LESSONS.md`.

## 1. Backend

### 1.1 — `config/models.py` : porter la référence de profil

`WorkspaceSpec` possède déjà `recipes: list[str]`, `env`, `extra_sources`, etc. Ajoute une
référence de profil **optionnelle** (rétro-compatible, donc la spec persistée des workspaces
existants reste valide) :

```python
# config/models.py
class ProfileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["shared", "user"]
    slug: str

class WorkspaceSpec(BaseModel):
    # ... champs existants ...
    profile: ProfileRef | None = None
```

Ajoute aussi `profile` au **modèle parsé par l'endpoint `/up`** (le corps du `POST
/me/workspaces/{name}/up` n'est pas la `WorkspaceSpec` complète — voir `routes/workspace_ops.py` —
mais un sous-ensemble qui inclut déjà `recipes`). Mets `profile` au même niveau que `recipes`.

### 1.2 — `profiles/models.py` : déjà prêt

`Profile.to_customizations()` existe et retourne `{"vscode": {"extensions": [...], "settings": {...}}}`.
**Réutilise-la** (c'est une méthode, pas une fonction libre).

### 1.3 — `devpod/service.py::_write_devcontainer` : injecter le profil

Ajoute un paramètre `profile: Profile | None = None`. Après le bloc `if recipes:` (qui remplit
`content["features"]`) et avant l'écriture du fichier, fusionne le fragment :

```python
# import en tête : from ..profiles.models import Profile
def _write_devcontainer(
    self,
    login: str,
    ws_id: str,
    host_port: int | None = None,
    recipes: list[RecipeMeta] | None = None,
    feature_env: dict[str, str] | None = None,
    extra_sources: list[SourceSpec] | None = None,
    profile: Profile | None = None,           # <-- nouveau
) -> Path:
    ...
    # (après le bloc recipes)
    if profile is not None:
        vscode = content.setdefault("customizations", {}).setdefault("vscode", {})
        frag = profile.to_customizations()["vscode"]
        existing = vscode.get("extensions", []) or []
        vscode["extensions"] = list(dict.fromkeys([*existing, *frag["extensions"]]))
        vscode["settings"] = {**(vscode.get("settings", {}) or {}), **frag["settings"]}
    ...
```

> Le `content` n'a aujourd'hui aucun bloc `customizations` ; la fusion défensive (union des
> extensions, settings du profil prioritaires) garantit la robustesse si une recipe en ajoute un
> jour. Clés de settings VS Code plates → fusion superficielle correcte.

### 1.4 — `devpod/service.py::up` : passer le profil

Ajoute `profile: Profile | None = None` à la signature de `up()` (à côté de `recipes`), et
transmets-le à `_write_devcontainer` **dans la branche `docker-tls` uniquement** :

```python
async def up(
    self,
    login: str,
    ws_spec: WorkspaceSpec,
    recipes: list[RecipeMeta] | None = None,
    feature_env: dict[str, str] | None = None,
    generate_ssh_key: bool = False,
    request_host: str = "",
    profile: Profile | None = None,           # <-- nouveau
) -> str:
    ...
    if host_cfg.type == "docker-tls":
        dc_path = self._write_devcontainer(
            login, ws_id,
            host_port=host_port,
            recipes=recipes,
            feature_env=feature_env,
            extra_sources=ws_spec.extra_sources if ws_spec.extra_sources else None,
            profile=profile,                  # <-- nouveau
        )
```

### 1.5 — `routes/workspace_ops.py` : résoudre le profil (miroir des recipes)

C'est le handler du `/up` qui résout aujourd'hui `ws_spec.recipes` (slugs) → `list[RecipeMeta]`
avant d'appeler `service.up(...)`. **Au même endroit**, résous le profil :

```python
# Construire ProfileRepository comme dans routes/profiles.py (même data_dir).
profile_obj = None
if ws_spec.profile is not None:
    try:
        profile_obj = profile_repo.get(
            ws_spec.profile.scope, ws_spec.profile.slug, login
        )
    except ProfileError:
        # Dégradation gracieuse : profil supprimé entre-temps → on lance sans profil.
        _log.warning("workspace.profile_missing",
                     scope=ws_spec.profile.scope, slug=ws_spec.profile.slug)

await service.up(login, ws_spec, recipes=resolved_recipes, profile=profile_obj, ...)
```

`ProfileRepository.get(scope, slug, login)` lève `ProfileError("not_found")` si absent — d'où le
`try/except`. **Ne fais pas échouer le `up`** si le profil manque.

## 2. Frontend

### 2.1 — `features/workspaces/useWorkspaceOps.ts`

`CreateInput` et les deux corps de requête (`POST /me/workspaces` **et** `/up`) doivent porter le
profil, exactement comme `recipes` :

```ts
interface CreateInput {
  name: string
  sources: SourceEntry[]
  host: string
  recipes: string[]
  generateSshKey?: boolean
  profile?: { scope: 'shared' | 'user'; slug: string }   // <-- nouveau
}
// dans spec (POST /me/workspaces) ET dans le body /up : ajouter `profile: profile ?? null`
```

### 2.2 — `features/workspaces/WorkspaceCreate.tsx`

Ajoute un `<Select>` de profil calqué sur le pattern existant (`RecipePicker` / Select host avec
sentinelle, cf. `HOST_DEFAULT`, `CRED_NONE`). Source des données : le hook existant
`@/features/profiles/hooks/useProfiles` (il existe déjà).

```tsx
import { useProfiles } from '@/features/profiles/hooks/useProfiles'

const PROFILE_NONE = '__none__'
const { data: profiles = [] } = useProfiles()
const [profile, setProfile] = useState('')   // '' = aucun, sinon 'scope:slug'

// rendu (près du RecipePicker) :
<div>
  <Label className="text-xs">{t('workspaces.form.profile')}</Label>
  <Select value={profile || PROFILE_NONE}
          onValueChange={(v) => setProfile(v === PROFILE_NONE ? '' : v)}>
    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
    <SelectContent>
      <SelectItem value={PROFILE_NONE}>{t('workspaces.form.profileNone')}</SelectItem>
      {profiles.map((p) => (
        <SelectItem key={`${p.scope}:${p.slug}`} value={`${p.scope}:${p.slug}`}>
          {p.name}{p.scope === 'shared' ? ` ${t('workspaces.form.profileShared')}` : ''}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
</div>

// au submit, convertir 'scope:slug' -> { scope, slug } et passer dans createWorkspace.mutate
const profileRef = profile
  ? (() => { const [scope, slug] = profile.split(':'); return { scope, slug } as const })()
  : undefined
```

> Vérifie le type exposé par `useProfiles` (probablement `ProfileSummary` avec `scope`, `slug`,
> `name`) et aligne-toi dessus.

### 2.3 — i18n (`frontend/src/i18n/fr.json` + `en.json`)

`workspaces.form.profile`, `workspaces.form.profileNone`, `workspaces.form.profileShared`.
Aucune chaîne en dur.

## 3. Persistance

Le `profile` ajouté à `WorkspaceSpec` (§1.1) est persisté via le `POST /me/workspaces` existant →
un `stop`/`up` ou une recréation régénère le devcontainer **avec le même profil**. C'est la
*référence* (scope+slug) qui est stockée : modifier le profil plus tard sera pris en compte au
prochain `up` (cohérent avec le fork = copie indépendante).

## 4. Tests

**Backend (`pytest`, le projet utilise `respx` + `pytest-asyncio` auto)** :
- `_write_devcontainer` avec `profile` : le JSON écrit contient `customizations.vscode.extensions`
  fusionnées (union, ordre stable) et `settings` du profil prioritaires ; sans profil → pas de bloc
  `customizations`.
- `up()` host `docker-tls` + profil → `_write_devcontainer` reçoit bien le profil (capture/mock).
- `routes/workspace_ops` : profil `not_found` → `up` lancé **sans** profil + warning loggé (pas d'échec).
- rétro-compat : spec sans `profile` → comportement inchangé.

**Frontend (`vitest` + MSW)** :
- le Select liste profils user + partagés (suffixe « partagé »), option « aucun » par défaut.
- création avec profil → les deux requêtes (`/me/workspaces` et `/up`) contiennent
  `profile: { scope, slug }`.
- création sans profil → `profile` à `null`/absent.

## 5. Definition of Done

- [ ] `ProfileRef` + `WorkspaceSpec.profile` (et champ équivalent sur le modèle `/up`).
- [ ] `_write_devcontainer` fusionne le fragment (union extensions + settings prioritaires profil).
- [ ] `up()` passe le profil à `_write_devcontainer` (**branche `docker-tls`**).
- [ ] `routes/workspace_ops` résout le profil via `ProfileRepository.get`, dégradation gracieuse si absent.
- [ ] `WorkspaceCreate` : sélecteur de profil (pattern Select + sentinelle), payload enrichi dans
      les **deux** appels.
- [ ] i18n fr + en ; rétro-compatibilité préservée.
- [ ] Tests backend + frontend verts ; `ruff`/`mypy --strict` OK côté back ; TS strict + eslint côté front.
- [ ] Aucun fichier > 300 lignes ; commits conventionnels FR sur `dev`.
- [ ] `LESSONS.md` : limitation SSH (profil/recipes docker-tls only) + dégradation gracieuse.

## 6. Résultat

Un utilisateur crée un profil (extensions Open VSX), le choisit à la création d'un workspace
**docker-tls**, et openvscode-server démarre avec ces extensions pré-installées — via le
`devcontainer.json` standard généré par le portail, sans rien installer sur son poste.
