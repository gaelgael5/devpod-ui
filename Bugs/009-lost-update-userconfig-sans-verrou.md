# 009 — Lost update : aucun verrou sur le cycle load → modify → save de `UserConfig`

- **Sévérité** : majeur
- **Sous-système** : config / db
- **Fichiers** : `backend/src/portal/config/store.py:90-95` (`save_user`) ; `db/user_config.py:147-169` (`save_user_db` : `delete` + réinsertion complète des workspaces) ; déclencheurs : `routes/me.py` (add_workspace, put_config, …), `mcp/devpod_tools/__init__.py` (~406, 928, 974, 995)
- **Statut** : ouvert

## Symptôme

Deux requêtes concurrentes pour le même login (ex. l'UI ajoute un workspace pendant qu'un appel MCP
en modifie un autre) : l'une des deux modifications est **perdue** — un workspace ajouté disparaît.

## Cause racine

Chaque requête exécute `cfg = load_user()` → mutation → `save_user()`. `save_user_db` fait un
`delete(workspaces).where(login)` **suivi d'une réinsertion complète** de toute la liste. Le dernier
`save` réécrit l'intégralité de la liste telle qu'elle était **avant** la mutation concurrente → la
modification de l'autre requête est écrasée.

`CLAUDE.md` exige un « verrou par `ws_id`/user ». Il existe bien un lock par `ws_id`
(`devpod/runner.py`), mais il ne couvre **pas** les écritures de `UserConfig`. Pas de verrou
applicatif, pas de `with_for_update`, pas de version optimiste.

## Piste de correction

Verrou `asyncio.Lock` par login autour du cycle load/modify/save, ou `SELECT ... FOR UPDATE` sur
`users` en tête de transaction, ou colonne `version` en compare-and-swap. Le pattern correct existe
déjà dans le repo : `db/tokens.py` utilise `with_for_update()`.
