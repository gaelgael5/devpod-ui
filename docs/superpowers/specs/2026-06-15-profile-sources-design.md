# Profile Sources — Design Spec

## Objectif

Permettre à un admin de configurer des serveurs de profils VSCode distants, de parcourir les profils disponibles, et d'en importer dans les profils partagés du portail. Miroir exact du système `recipe-sources` existant.

## Architecture

`profile-sources.yaml` stocké dans `/data/`. Routes admin dédiées pour gérer les URLs de sources, prévisualiser la galerie agrégée, et importer un profil. Page frontend `/admin/profile-sources` miroir d'`AdminRecipes`. Les profils importés deviennent des profils partagés (`scope="shared"`) dans `/data/profiles/`.

---

## Format `toc.txt`

Chaque serveur expose un fichier `toc.txt` à la racine de son URL, avec une ligne par profil disponible :

```
python-dev.yaml | Python Dev | Profil Python avec debugpy et pytest | 8
frontend-react.yaml | Frontend React | ESLint + Prettier + Tailwind | 5
rust-dev.yaml | Rust Dev | rust-analyzer + CodeLLDB | 3
```

Champs (séparateur `|`, 4 champs obligatoires) :
1. `filename` — nom du fichier YAML (pattern : `^[a-z0-9][a-z0-9-]*\.yaml$`)
2. `name` — nom affiché (max 80 chars)
3. `description` — description courte (max 200 chars)
4. `extension_count` — nombre d'extensions (entier, informatif)

Lignes mal formées (< 4 champs, filename invalide) : ignorées avec warning log.

---

## Backend

### Stockage

`/data/profile-sources.yaml` :
```yaml
sources:
  - https://raw.githubusercontent.com/org/devpod-profiles/main/
  - https://intranet.yoops.org/devpod-profiles/
```

Modèle pydantic `ProfileSourcesConfig` avec `sources: list[str]`, `extra="forbid"`. Écriture atomique via `tempfile` + `os.replace`.

### Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `backend/src/portal/profiles/sources.py` | `ProfileSourcesStore` (load/save) + `fetch_profile_toc()` + `fetch_remote_profile()` |
| `backend/src/portal/routes/profile_sources.py` | Routes admin CRUD sources + preview + import |
| `backend/tests/profiles/test_sources.py` | Tests unitaires fetch/parse toc.txt |
| `backend/tests/routes/test_profile_sources.py` | Tests routes (CRUD, preview, import, anti-SSRF) |

### Routes admin

| Méthode | Endpoint | Corps | Réponse |
|---|---|---|---|
| `GET` | `/admin/profile-sources` | — | `{"sources": ["url1", ...]}` |
| `PUT` | `/admin/profile-sources` | `{"sources": ["url1", ...]}` — URLs HTTPS uniquement, 422 si URL non-HTTPS | `{"sources": [...]}` |
| `GET` | `/admin/profile-sources/preview` | — | `{"profiles": [RemoteProfileSummary[]]}` |
| `POST` | `/admin/profile-sources/import` | `{"source_url": "https://.../python-dev.yaml"}` | `Profile` (201) |

### Modèle `RemoteProfileSummary`

```python
class RemoteProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str
    name: str
    description: str
    extension_count: int
    source_url: str   # URL complète du fichier .yaml
    source_base: str  # URL de base de la source (pour le badge UI)
```

### Logique `fetch_profile_toc(base_url)`

1. Fetch `{base_url}/toc.txt` (timeout 10s, anti-SSRF)
2. Parser chaque ligne : `filename | name | description | extension_count`
3. Valider `filename` avec regex `^[a-z0-9][a-z0-9-]*\.yaml$`
4. Retourner `list[RemoteProfileSummary]`

### Logique `POST /admin/profile-sources/import`

1. Valider `source_url` : doit être HTTPS, anti-SSRF (même module que recipe-sources)
2. Fetch `source_url` (timeout 10s)
3. Parser YAML → valider `ProfileBody` pydantic
4. Slugifier `name` → si slug existe déjà dans `/data/profiles/` → 409 `{"detail": "profile_slug_conflict"}`
5. Écriture atomique `/data/profiles/{slug}.yaml`
6. Retourner `Profile` (scope="shared")

### Sécurité

- Anti-SSRF sur tous les fetches HTTP (résolution DNS + rejet IPs privées/loopback) — réutiliser `_check_ssrf()` existant depuis `recipe_sources.py`
- `ProfileBody` avec `extra="forbid"` : tout champ inconnu dans le YAML distant rejette l'import (422)
- Slug généré côté serveur depuis `name`, jamais depuis le `filename` du toc.txt
- Pas d'écriture hors `/data/profiles/` : `safe_user_path` non nécessaire ici (chemin fixe), mais slug validé par regex avant usage en nom de fichier

---

## Frontend

### Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `frontend/src/features/admin/AdminProfileSources.tsx` | Page principale |
| `frontend/src/features/admin/useProfileSources.ts` | Hooks React Query (sources + preview + import) |

### Route

Ajouter dans le router : `/admin/profile-sources` → `AdminProfileSources`

Ajouter dans la navigation admin : lien "Sources de profils" à côté de "Recettes".

### Structure `AdminProfileSources`

```
AdminProfileSources
├── Section "Sources configurées"
│   ├── Liste des URLs (une <Input> par URL, bouton supprimer)
│   ├── Bouton "Ajouter une source"
│   └── Bouton "Enregistrer" → PUT /admin/profile-sources
│
└── Section "Galerie"
    ├── Bouton "Actualiser" → GET /admin/profile-sources/preview
    └── Grid de RemoteProfileCards
        ├── Nom
        ├── Description
        ├── Badge "N extensions"
        ├── Badge source (source_base tronqué)
        └── Bouton "Importer" → POST /admin/profile-sources/import
```

### Hooks `useProfileSources.ts`

```typescript
useProfileSources()        // GET /admin/profile-sources
useSaveProfileSources()    // PUT /admin/profile-sources
useProfileSourcesPreview() // GET /admin/profile-sources/preview (manuel)
useImportProfile()         // POST /admin/profile-sources/import
                           // → onSuccess: invalidate GET /profiles
```

### États UI

| Situation | Comportement |
|---|---|
| Source inaccessible (toc.txt 404/timeout) | Warning visible sur la galerie, autres sources affichées |
| Ligne toc.txt invalide | Ignorée (backend), pas d'erreur côté UI |
| Import en cours | Spinner sur la card, bouton désactivé |
| Import réussi | Toast "Profil importé", bouton remplacé par badge "Importé" |
| Slug déjà existant | 409 → toast "Ce profil existe déjà" |

### i18n

Clés `admin.profileSources.*` dans `fr.json` et `en.json`, même convention que `admin.recipes.*`.

---

## Ce qui est hors scope

- Mise à jour automatique des profils déjà importés quand la source change
- Auth sur les sources (URLs publiques uniquement)
- Suppression de profils depuis cette page (reste dans AdminProfiles jusqu'à suppression future)
- Suppression de `AdminProfiles` (chantier ultérieur séparé)
