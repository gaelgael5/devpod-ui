# Spec 35b — Mode `merge` : agents à fichier de config partagé

Addendum à [`35-agents-workspace-mcp.md`](35-agents-workspace-mcp.md). Traite le cas
des clients dont la config MCP **partage un fichier** avec d'autres réglages
(Codex `~/.codex/config.toml`, Gemini `~/.gemini/settings.json`), pour lesquels
le mécanisme v1 (symlink vers un mount **read-only**) est inadapté : il rend le
fichier non-inscriptible par le client **et** en écrase tout réglage existant.

## Ligne de partage

| Mode | Clients | Fichier | Matérialisation |
|------|---------|---------|-----------------|
| `replace` (v1, inchangé) | Claude, Cursor, Cline, Devin | dédié MCP | fichier généré sur le host, bind mount **ro** `/opt/agent-config`, symlink `target_path` → mount, régénération à chaud via le mount |
| `merge` (ce chantier) | Codex, Gemini | **partagé** | le portail **fusionne** le connecteur dans le fichier existant du conteneur |

## Modèle retenu — merge piloté par le portail

Le merge ne peut avoir lieu :
- **ni dans le conteneur** : on ne peut pas supposer un interpréteur (Codex = Rust,
  Gemini = Node ; `python3` non garanti) ;
- **ni sur le host** : le fichier (avec les réglages utilisateur) vit dans le FS du
  **conteneur**, pas sur le host.

→ Le merge a lieu **dans le portail**, et le résultat est déposé dans le conteneur
via `devpod ssh {ws_id} --command …` (façade `devpod/exec.py`, canal déjà en place).

Cycle **read-merge-write** :
1. lire `target_path` dans le conteneur (`cat`, tolère l'absence) ;
2. merger côté portail — JSON via stdlib, TOML via **`tomlkit`** (préserve
   commentaires / structure / réglages utilisateur) ;
3. réécrire atomiquement (`… > tmp && chmod 600 && mv`, `mkdir -p` du parent).

### Sémantique de fusion (D2)

- Le **template rend le fragment possédé** : un mini-document dont la clé de tête
  (`mcpServers` JSON, `[mcp_servers.*]` TOML) porte les serveurs du portail.
- Les serveurs injectés sont préfixés **`portal-<slug>`**.
- Le merge : upsert des `portal-*` sous la clé de tête, **purge des `portal-*`
  périmés**, **jamais** de clé sans préfixe (serveur ajouté par l'utilisateur).
- Fichier absent → création ; existant malformé → **fail-safe** (on ne détruit pas).

### Déclencheurs (4)

`create` · `recreate` · **rotation/décochage** (re-merge live) · **boot portail**
(réconciliation best-effort, throttlée, des workspaces `running` à agents `merge`).

## Décisions actées

- **D1** mode `∈ {replace, merge}` (colonne `agent_type.mode`).
- **D2** serveurs préfixés `portal-`, réconciliation scoping sur la clé de tête.
- **D3** écriture TOML côté portail via `tomlkit` (pas d'émetteur vendu, pas de
  dépendance conteneur).
- **D5** rotation `merge` = **live** (portail pousse), fail-closed gateway immédiat.
- **D6** en `merge` le token atterrit dans un fichier writable (credential propre à
  l'agent) — pas de nouveau risque d'exfiltration, acté.
- **D4 dissoute** : aucun interpréteur/binaire requis dans l'image.

## Découpage TDD

- **T1** — colonne `mode` (migration 058, backfill codex/gemini → `merge` +
  `enabled=false`), couche DB. ✅
- **T2** — cœur de merge pur (`agents/merge.py`, `tomlkit`). ✅
- **T3** — canal fichier conteneur (`read`/`write` atomique via `devpod ssh`).
- **T4** — orchestration `push_merged_agents` (rotation → render → read → merge → write).
- **T5** — partition provisioning par mode ; hook post-readiness dans `service.up`.
- **T6** — déclencheurs rotation (resync) + réconciliation au boot (lifespan).
- **T7** — DTO + `PATCH /admin/agent-types/{id}` portent `mode` ; UI (sélecteur, pastille).
- **T8** — templates Codex/Gemini en fragment (clé de tête + préfixe `portal-`).
- **T9** — vérif bout-en-bout test1 + réactivation codex/gemini.

## Points signalés

- Dépendance `tomlkit` ajoutée au portail.
- `devpod ssh` sur docker-tls : si disponible, `merge` marcherait là où `replace`
  est bloqué (SSH-only) — **à vérifier**, hors DoD.
- Fenêtre de race (client écrit entre read et write) : `mv` atomique +
  read-merge-write auto-réconciliant. Courte, assumée.

## DoD

Lint + mypy + tests verts (dont migration up/down sur CI/test1) ; codex/gemini
réactivés et vérifiés bout-en-bout sur test1 (réglage utilisateur préservé +
injection + révocation live) ; aucun secret en clair ; LESSONS.md + note mémoire
spec 35 actualisés.
