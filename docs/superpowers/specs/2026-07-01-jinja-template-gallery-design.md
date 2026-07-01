# Galerie de templates Jinja2 (import + export) — Design

**Date** : 2026-07-01
**Statut** : approuvé (design), en attente de plan d'implémentation
**Auteur** : brainstorming Colibri

## Contexte et problème

Les templates Jinja2 (`jinja2_template`, couple `key × culture`) vivent **uniquement en
base**. Contrairement aux templates compose (`seed_builtin_templates`), ils ne sont ni
seedés ni versionnés hors instance. Un crash / une réinitialisation de l'instance ⇒
perte définitive des templates.

**Objectif** : pouvoir stocker les templates Jinja2 **ailleurs que dans l'instance**, en
reprenant le modèle de la *VS Code Profile Gallery*, intégré à la vue
**Admin → Jinja-templates**. Le dépôt git externe devient la source de vérité durable :
l'instance **importe** depuis lui et peut **exporter** vers lui.

## Décisions de cadrage

| Sujet | Décision |
|-------|----------|
| Périmètre | **Import + Export** (la Profile Gallery est import-only ; on ajoute l'export pour vraiment « stocker ailleurs ») |
| Conflit à l'import | **Informer avant d'écraser** : import direct si nouveau, confirmation explicite si `(key,culture)` déjà présent |
| Format d'export | **Bundle ZIP** (`toc.txt` + fichiers `.j2`) — round-trip parfait export → git → import |
| Convention d'URL source | Accepte la forme **dossier** *ou* **toc.txt** (helper robuste partagé, cf. bug profils déjà corrigé) |
| Refactor autres galeries | Hors scope : on ne touche pas recipes/compose/profiles (le helper partagé est simplement réutilisable plus tard) |

## Convention du dépôt externe

Un répertoire (ex. `https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/jinja/`)
contient :

- `toc.txt` — une ligne par template : `filename | key | culture | description`
- `<key>.<culture>.j2` — le **body brut** du template. Aucune métadonnée dans le fichier :
  `key`, `culture` et `description` proviennent exclusivement de la ligne du `toc.txt`.

Exemple de `toc.txt` :

```
test_host_available.fr.j2 | test_host_available | fr | Message dispo machine de test
test_host_available.en.j2 | test_host_available | en | Test host available message
```

Le `filename` est uniquement une cible de fetch ; l'identité canonique du template est
`(key, culture)` porté par le toc.

## Schéma de données

### Nouvelle table `jinja_template_sources`

Calquée sur `compose_catalog_sources` :

```python
jinja_template_sources = Table(
    "jinja_template_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False, unique=True),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
```

- **Migration Alembic `041_jinja_template_sources.py`**, `down_revision = "040"` (tête
  actuelle), `upgrade` = `op.create_table(...)`, `downgrade` = `op.drop_table(...)`.
- Défaut si aucune source configurée :
  `https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/jinja/toc.txt`.

### Table existante réutilisée

Les templates importés atterrissent dans `jinja2_template` via `messages.db.upsert_template`
(upsert par contrainte `pk_jinja2_template` sur `(key, culture)`). Aucune modification de
schéma sur cette table.

### `db/sources.py`

Ajout de `_DEFAULT_JINJA_SOURCE`, `load_jinja_template_sources(conn)` et
`save_jinja_template_sources(sources, conn)`, strictement calqués sur les fonctions
compose.

## Backend — module `routes/jinja_template_sources.py`

Miroir de `routes/profile_sources.py`. Router admin, monté avec préfixe `/admin` dans
`app.py`.

### Helper partagé `split_toc_url`

Extraction d'un utilitaire réutilisable :

```python
def split_toc_url(source: str) -> tuple[str, str]:
    """(toc_url, dir_base) — accepte soit le dossier, soit l'URL du toc.txt."""
```

Comportement identique à la correction déjà appliquée dans `profile_sources.py`
(strip du `/toc.txt` final s'il est présent, sinon on l'ajoute ; `dir_base` sans slash
final). Emplacement retenu : `routes/_sources_util.py` (module utilitaire léger, sans
dépendance FastAPI). `jinja_template_sources.py` l'importe. (Le rattachement de
profiles/recipes/compose à ce helper est hors scope de cette spec.)

### Endpoints

| Méthode & route | Rôle |
|-----------------|------|
| `GET /admin/jinja-template-sources` | `{ "sources": [...] }` (défaut si vide) |
| `PUT /admin/jinja-template-sources` | valide HTTPS + anti-SSRF, `save_jinja_template_sources` |
| `GET /admin/jinja-template-sources/preview` | `{ "templates": [...] }` (parse chaque `toc.txt`) |
| `POST /admin/jinja-template-sources/import` | importe un template, gère le conflit |
| `GET /admin/jinja-templates/export` | ZIP de tous les templates de la DB |

**Preview** — pour chaque source configurée : anti-SSRF, `split_toc_url`, fetch du
`toc.txt`, parse ligne par ligne (4 champs séparés par `|`). Chaque entrée renvoyée :

```json
{
  "filename": "test_host_available.fr.j2",
  "key": "test_host_available",
  "culture": "fr",
  "description": "Message dispo machine de test",
  "source_url": "<dir_base>/<filename>",
  "source_base": "<dir_base>"
}
```

Lignes invalides (≠ 4 champs, filename hors regex, key/culture hors regex) : `log.warning`
et skip. Échec fetch d'une source : `log.warning` et `[]` (pas d'exception qui casse tout).

**Import** — body `{ source_url, key, culture, overwrite: bool = false }` :

1. valide `key` (`^[a-zA-Z0-9_-]+$`), `culture` (`^[a-z]{2}$`), et filename déduit
   `^[a-zA-Z0-9._-]+\.j2$` ; anti-SSRF sur `source_url`.
2. fetch du body (`follow_redirects=False`, timeout 5 s).
3. si `(key, culture)` existe déjà en DB **et** `overwrite is False` → **HTTP 409**
   `detail="template_exists"`.
4. sinon `upsert_template(conn, Jinja2Template(key, culture, body))` → renvoie le template
   (200 si écrasement, 201 si création — ou 200 uniforme, à trancher au plan ; défaut :
   201 création / 200 écrasement).

**Export** — `GET /admin/jinja-templates/export` :

1. `list_templates(conn)` (tous les `(key, culture, body)`).
2. construit en mémoire (`io.BytesIO` + `zipfile.ZipFile`) :
   - `toc.txt` : une ligne `<key>.<culture>.j2 | key | culture | <desc>` par template,
     où `<desc>` = première ligne non vide du body, sanitizée (pas de `|`, pas de saut de
     ligne, tronquée ~80 car.).
   - un fichier `<key>.<culture>.j2` par template contenant le body brut.
3. `Response`/`StreamingResponse` `media_type="application/zip"`,
   `Content-Disposition: attachment; filename="jinja-templates.zip"`.

## Frontend

### Hook `features/admin/useJinjaTemplateSources.ts`

Miroir de `useProfileSources.ts` : `sourcesQuery`, `updateSources`, `previewQuery`,
`importTemplate` (mutation `{ source_url, key, culture, overwrite }`). Ajout de
`exportBundle()` : `GET /admin/jinja-templates/export` en `blob`, création d'un lien de
téléchargement `jinja-templates.zip`.

Type `RemoteJinjaTemplate` : `{ filename, key, culture, description, source_url, source_base }`.

### Vue `features/admin/AdminJinjaTemplates.tsx`

Ajout, sans casser l'éditeur existant :

- **Bouton « Exporter »** en tête (à côté de « Nouveau »), déclenche `exportBundle()`.
- **Section Galerie** (sous la table existante), miroir de `AdminProfileSources` :
  - liste éditable des sources (input + ajout/suppression, `PUT`),
  - bouton « Rafraîchir la galerie »,
  - grille des templates distants : `key` / `culture` / `description` + bouton **Importer**.
  - Un template dont `(key, culture)` est déjà en base affiche un **badge « présent »** ;
    cliquer **Importer** ouvre alors un **dialog de confirmation d'écrasement** →
    `importTemplate({ ..., overwrite: true })`. Sinon import direct (`overwrite: false`).

Les `(key, culture)` présents sont calculés côté client à partir de `useJinjaTemplates`
(déjà chargé dans la vue).

### i18n

Nouvelles clés sous `jinjaTemplates.gallery.*` et `jinjaTemplates.export*` dans
`fr.json` et `en.json` (sources, gallery, import, importing, present, overwriteConfirm,
export, exported, empty, filter…).

## Sécurité

- **anti-SSRF** : réutilise `_check_ssrf` (résolution DNS + blocage IP internes), appliqué
  au `PUT` des sources, au `preview` et à l'`import`.
- **HTTPS obligatoire** pour toute source (rejet 422 sinon), comme les profils.
- `follow_redirects=False` sur tous les fetch.
- **Validation stricte** avant DB : `key`, `culture`, filename (regex ci-dessus).
- Aucun secret manipulé ; endpoints réservés `require_admin`.

## Tests (TDD)

### Backend — purs (exécutables en local Windows)

- `split_toc_url` : formes dossier / dossier-sans-slash / toc.txt → même `(toc_url, dir_base)`.
- parsing d'une ligne toc : valide (4 champs) ; invalide (3 champs, filename KO, culture KO) → skip.
- `_preview_one_source` avec faux client enregistreur : un seul `toc.txt` demandé (pas de
  doublon), `source_url`/`source_base` corrects, quelle que soit la forme d'entrée.
- construction du bundle ZIP : contient `toc.txt` + un `.j2` par template ; round-trip
  (re-parse du toc + lecture des fichiers) redonne les `(key, culture, body)` d'origine ;
  sanitize de la description (pas de `|`/newline).

### Backend — DB/app (valident sur CI/serveur ; skip local)

- `GET` sources défaut / `PUT` save + relecture.
- import nouveau `(key,culture)` → template créé en DB.
- import existant sans `overwrite` → **409 `template_exists`**, DB inchangée.
- import existant avec `overwrite=true` → body écrasé.
- export → ZIP non vide reflétant la DB.

### Frontend

- Composant galerie (miroir `AdminProfileSources.test.tsx`) : rendu des sources, ajout,
  import direct d'un nouveau, dialog de confirmation puis import `overwrite` sur un
  présent, déclenchement de l'export.

## Découpage d'implémentation (ordre)

1. Migration `041` + `Table` dans `tables.py` + `db/sources.py` (load/save/défaut jinja).
2. Helper `routes/_sources_util.py::split_toc_url` + tests purs.
3. Module `routes/jinja_template_sources.py` (sources, preview, import, export) + tests.
4. Montage du router dans `app.py`.
5. Frontend : hook + section Galerie + bouton Export + dialog + i18n + tests.
6. Vérif : `ruff` + `mypy` + `pytest` (backend), `vitest` (frontend) ; validation
   déployée via `TESTER-MON-DEV.md` (push `dev` → `dev-deploy.sh` → test réel).

## Hors périmètre

- Refactor de recipes/compose/profiles pour utiliser `split_toc_url`.
- Seeding automatique de templates Jinja builtin au démarrage.
- Versionnement / historique des templates.
- Édition des templates directement dans le dépôt git depuis l'UI.
