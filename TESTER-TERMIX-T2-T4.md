# Tester la fondation Termix (T2 → T4) sur test1

Périmètre livré en autonomie : **journal durable + moteur d'automates + écrans +
endpoints de consommation**. T0 (déploiement Termix) et T5 (connecteur) restent à
faire en session avec accès infra — ils s'ajouteront **par paramétrage** (contrat
OpenAPI + automate), sans code en dur.

> Prérequis : suivre le cycle de [`TESTER-MON-DEV.md`](TESTER-MON-DEV.md)
> (lint + mypy → push `dev` → `dev-deploy.sh` sur test1 → lire les vrais logs).
> Les tests DB (`tests/db/test_app_event.py`, `tests/db/test_automation.py`) sont
> skippés en local faute de Docker : **les jouer sur test1** avec `uv sync --extra dev`
> puis `uv run pytest tests/db -v` (exiger des PASSED explicites).

## 0. Migrations

Au boot, `alembic upgrade head` applique **086** (`app_event`) et **087** (moteur
automates). Vérifier dans les logs `db_migrations_done` et l'absence d'erreur.

## 1. T2 — journal durable `app_event`

1. Éditer la connexion d'un serveur de test (menu ⋮ → « Éditer les paramètres »).
2. En DB : `SELECT seq, event_type, actor, workspace, subject FROM app_event ORDER BY seq DESC LIMIT 5;`
   → une ligne `test_server.updated` doit apparaître.
3. Créer / arrêter une session tmux → lignes `session.created` / `session.closed`.
4. **Diff-sonde** : ouvrir une session tmux **hors portail** (SSH direct dans le
   conteneur, `tmux new -s rogue`) ; sous ~60 s une ligne `session.created`
   (actor `system`) doit apparaître. La fermer hors portail → `session.closed`.

## 2. T3 — contrats & automates (écran `/admin/automations`)

### Contrats (`/admin/automations/contracts`)
- **Importer** un contrat par URL (spec OpenAPI JSON/YAML) ou en collant le spec.
- Vérifier la version affichée, le bouton **Rafraîchir** (si URL), **Opérations**.

### Automate
- **Nouvel automate** : choisir un ou plusieurs events déclencheurs, une portée
  (`*` ou noms de workspace), un contrat + une opération (URL/méthode préremplies),
  un corps à variables (`{subject.host_name}`…), éventuellement des en-têtes
  (valeur ou `${vault://…}`), un débounce, `stop_chain`. Créé **désactivé**.
- L'**activer** (toggle). Le curseur est posé au sommet du journal à la création :
  seuls les events **à venir** déclenchent (le rattrapage est explicite, cf. §3).

### Déclenchement
- **Injecter un event de test** (barre Simulation : Host / Workspace / Session a
  bougé) → l'automate actif dont le type matche doit **appeler l'URL cible**.
- Vérifier dans **Historique** : statut `ok`/`failed`, code HTTP, aperçu requête,
  bouton **Rejouer**. Anti-rejeu : réinjecter la **même** version ne relance pas
  (sauf rejeu manuel).
- `stop_chain` : deux automates matchant le même event, le prioritaire (plus haut)
  en `stop_chain` → le suivant reçoit un run `skipped`.

## 3. Rattrapage (backfill)
- Bouton **Rattraper les existants** → émet un event de synchro par host / workspace
  / session **existant** (clé de dédup stable → idempotent, rejouable sans spam).
  Vérifier les compteurs du toast et les runs générés.

## 4. T4 — endpoints de consommation (clé API admin)

Le connecteur (T5) lira les coordonnées SSH via la **clé API admin**
(`PORTAL_API_KEY`, en-tête `Authorization: Bearer <clé>`). Sans clé → 401/403.

```bash
KEY=$PORTAL_API_KEY
curl -s -H "Authorization: Bearer $KEY" https://<portail>/admin/service/ssh/hosts
curl -s -H "Authorization: Bearer $KEY" https://<portail>/admin/service/ssh/workspaces
curl -s -H "Authorization: Bearer $KEY" https://<portail>/admin/service/ssh/sessions
curl -s -X POST -H "Authorization: Bearer $KEY" \
  https://<portail>/admin/service/ssh/hosts/<host>/reveal-password
```

Chaque appel est **audité** (`SELECT * FROM mcp_audit_log WHERE namespaced_name LIKE 'service.ssh.%';`).

## Écarts assumés (à valider avec l'architecte)
- **Journal hors-txn** : les mutations devpod fichier/CLI écrivent `app_event` en
  best-effort (own-txn) ; le trou op→journal est couvert par le backfill.
- **Ordre d'évaluation global** (position ↑/↓) au lieu du drag&drop per-workspace
  de docflow (portées `*` → ordre per-scope ambigu). `stop_chain` conservé.
- **Réordonnancement UI par flèches** (pas de librairie drag&drop).
