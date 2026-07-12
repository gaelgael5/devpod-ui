# Spec 35b — Mode `merge` : agents à fichier de config partagé

> **Révision 2026-07-07 — livraison par écriture conteneur (T4′/T5′).**
> Constat en réel : le vecteur v1 (bind mount + symlink posé au `postCreateCommand`)
> ne s'applique qu'à la **construction** du conteneur — or `devpod up` par défaut
> réutilise le conteneur existant (`--recreate` requis sinon). Mapper un agent sur
> un workspace existant exigeait donc un delete+recreate, contrainte produit
> inacceptable (« restart maximum »). Décision : la livraison des DEUX modes passe
> par **écriture directe dans le conteneur** via le canal T3 (`ws_exec`/`devpod ssh`),
> en hook post-readiness du `up` — le bind mount `/opt/agent-config` et le symlink
> sont retirés du `devcontainer.json` généré. Conséquences :
> - `replace` = fichier rendu complet, écrit tel quel ; `merge` = read→merge→write.
>   Un seul orchestrateur (`agents/push.py::push_agent_files`).
> - Un simple **restart** (re)installe la config ; le resync à chaud écrit aussi
>   directement (plus de dépose host). Best-effort au `up` (workspace reste
>   running, échec logué) ; la révocation DB reste le fail-closed.
> - `home` du conteneur résolu à chaud (`printf %s "$HOME"` via ws_exec), qui sert
>   aussi de sonde de readiness.
> - L'arborescence host `~/.devpod-portal/agent-config` et sa purge au delete sont
>   conservées pour les workspaces créés sous l'ancien mécanisme (legacy).

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
- **T3** — canal fichier conteneur (`agents/container_files.py`, base64 +
  écriture atomique via `ws_exec`). ✅
- **T4′** — orchestrateur unifié `agents/push.py::push_agent_files` (rotation →
  render → [replace: write | merge: read→merge→write] → exclude git). ✅ (révision)
- **T5′** — validation agents au `up` (422) + hook post-readiness dans
  `_run_up_impl` ; retrait du mount/postCreate agents du devcontainer. ✅ (révision)
- **T6** — resync à chaud réécrit par écriture conteneur (running only, stopped
  = skipped) + réconciliation au boot (lifespan, throttlée, best-effort). ✅
- **T7** — DTO + `PATCH /admin/agent-types/{id}` portent `mode` (None = inchangé) ;
  UI sélecteur + pastille, i18n fr/en, Vitest. ✅
- **T8** — migration 059 : templates Codex/Gemini en fragment possédé (clé de
  tête + préfixe `portal-`), codex/gemini toujours désactivés. ✅
- **T9** — vérif bout-en-bout. ✅ **replace/Claude vérifié EN RÉEL sur dev.yoops.org**
  (2026-07-07) : réconciliation au boot `agent_resync_done synced=4 skipped=1`
  (admin-roles arrêté sauté), `agent_files_pushed` sur devpod/rag/workflow/doc,
  `agent_files_pushed_on_up` au restart de workflow, **aucun push_failed** ;
  `.mcp.json` réel + `initialize` gateway OK ; canal T3 prouvé sur conteneur réel
  (écriture atomique 600, réglage user préservé, sentinelle NOFILE). Merge : canal
  + `merge_config` + migration 059 (render→merge→préserve) verts.
  **Reste (action admin utilisateur)** : activer codex/gemini (`enabled=true`) et
  vérifier le e2e merge sur un workspace à `config.toml` préexistant.

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
