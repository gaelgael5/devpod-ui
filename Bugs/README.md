# Bugs — registre d'audit

Un fichier par bug. Chaque fiche documente un défaut **confirmé par lecture du code**,
avec de quoi le corriger — **sans le corriger ici**.

Audit réalisé le 2026-07-03 sur la branche `dev`, par balayage complet des sous-systèmes
(devpod/exposure, auth/session/vault/secrets, config/DB, MCP, compose/nodes/certificats, frontend).
Les bugs déjà corrigés pendant la session (cookie de session, placeholder Caddy, reconnexion
automatique, cycle de vie des tunnels) ne figurent pas ici.

## Convention

`NNN-<slug>.md` — numéro d'ordre + slug court. Sévérité : critique / majeur / mineur.
Statut : 🔴 ouvert / ✅ corrigé / ⏸️ reporté (voir la fiche pour le détail).

## Index

### Critiques

| # | Sujet | Sous-système | Statut |
|---|-------|--------------|--------|
| [002](002-fuite-secrets-env-resolver-compose.md) | Fuite de secrets du portail (KEK/session/OIDC) via le résolveur `env://` en compose | secrets/compose | 🔴 ouvert |
| [003](003-absence-verrou-lifecycle-workspace.md) | Absence de verrou lifecycle : `up`/`stop`/`delete` concurrents corrompent l'état | devpod | 🔴 ouvert |

### Majeurs

| # | Sujet | Sous-système | Statut |
|---|-------|--------------|--------|
| [001](001-collision-allocation-ports-openvscode.md) | Collision d'allocation de ports openvscode entre workspaces | devpod/exposure | 🔴 ouvert |
| [004](004-culture-non-persistee-userconfig.md) | Champ `culture` de `UserConfig` ni écrit ni relu (perte silencieuse) | config/db | ✅ corrigé |
| [005](005-ws-proxy-websocket-ignore-ws-id-hint.md) | Proxy WebSocket VS Code ignore le `ws_id_hint` → mauvais workspace | exposure | ✅ corrigé |
| [006](006-stop-ignore-returncode-devpod.md) | `stop()` écrit « stopped » même si `devpod stop` a échoué | devpod | ✅ corrigé |
| [007](007-write-status-ressuscite-ligne-supprimee.md) | `_write_status` (upsert) ressuscite une ligne supprimée | devpod/db | 🔴 ouvert |
| [008](008-put-me-config-sans-allowlist-secret-ns.md) | `PUT /me/config` sans allowlist : `secret_ns`/`version` réécrivables | config/routes | ✅ corrigé |
| [009](009-lost-update-userconfig-sans-verrou.md) | Lost update : pas de verrou sur load→modify→save de `UserConfig` | config/db | 🔴 ouvert |
| [010](010-upserts-check-then-insert-non-atomiques.md) | Upserts check-then-insert non atomiques (UniqueViolation) | db | 🔴 ouvert |
| [011](011-ensure-user-db-invente-secret-ns.md) | `ensure_user_db` fabrique un `secret_ns` aléatoire → secrets orphelins | db/secrets | 🔴 ouvert |
| [012](012-portal-api-key-comparaison-non-constant-time.md) | Comparaison non constant-time de `portal_api_key` (bearer admin) | auth | ✅ corrigé |
| [013](013-csr-san-trop-permissif-usurpation-noeud.md) | SAN de CSR trop permissif : cert valide pour d'autres nœuds | nodes | 🔴 ouvert |
| [014](014-enrolement-noeud-non-atomique-token-reutilisable.md) | Enrôlement non atomique → join token réutilisable | nodes | 🔴 ouvert |
| [015](015-course-allocation-ports-compose.md) | Course sur l'allocation de ports compose | compose | 🔴 ouvert |
| [016](016-stream-host-command-sous-process-ssh-orphelin.md) | Sous-process ssh non tué à la déconnexion → déploiement orphelin | compose | ✅ corrigé (partiel, voir fiche) |
| [017](017-mcp-exceptions-non-gerees-echappent-dispatch.md) | MCP : exceptions non gérées échappent au dispatch → trou d'audit | mcp | ✅ corrigé |
| [018](018-frontend-delete-echec-silencieux-apifetch.md) | Frontend : échec silencieux systémique des DELETE (`apiFetch`) | frontend | ✅ corrigé |
| [019](019-frontend-delete-workspace-non-controle.md) | Frontend : `deleteWorkspace` — suppression finale non contrôlée | frontend | ✅ corrigé |
| [020](020-frontend-streams-reader-non-annule.md) | Frontend : streams fetch dont le reader n'est jamais annulé | frontend | ✅ corrigé |

### Mineurs

| # | Sujet | Sous-système | Statut |
|---|-------|--------------|--------|
| [021](021-proxmox-password-clair-renvoye-api.md) | Mot de passe Proxmox stocké/renvoyé en clair | proxmox | ✅ corrigé |
| [022](022-ssrf-dns-rebinding-compose-sources.md) | SSRF résiduelle : DNS rebinding (TOCTOU) | compose_sources | 🔴 ouvert |
| [023](023-proxmox-fetch-spec-sans-ssrf.md) | Fetch de spec proxmox sans contrôle SSRF | proxmox | ✅ corrigé |
| [024](024-proxmox-substitute-non-quote-resubstitution-token.md) | Substitution shell non quotée + re-substitution du token | proxmox/test_vm | ✅ corrigé |
| [025](025-mcp-io-bloquante-operations-yaml.md) | MCP : I/O fichier synchrone bloquant | mcp | ✅ corrigé |
| [026](026-mcp-transaction-db-pendant-probe-reseau.md) | MCP : transaction DB tenue pendant l'I/O réseau du probe | mcp | ✅ corrigé |
| [027](027-mcp-injection-logql-non-echappee.md) | MCP : injection LogQL par interpolation non échappée | mcp | ✅ corrigé |
| [028](028-mcp-deserialisation-loki-non-validee.md) | MCP : désérialisation non validée de la réponse Loki | mcp | ✅ corrigé |
| [029](029-mcp-bearergate-filtre-seulement-http.md) | MCP : `BearerGate` ne filtre que les scopes `http` | mcp | ✅ corrigé |
| [030](030-vault-master-keys-en-memoire-apres-expiration.md) | Vault : master keys en mémoire au-delà de l'expiration du cookie | vault | ✅ corrigé |
| [031](031-vault-session-id-vide-non-rejete.md) | Vault : `session_id` vide non rejeté | vault | ✅ corrigé |
| [032](032-roles-figes-dans-cookie-revocation-non-prise-en-compte.md) | Rôles figés dans le cookie — révocation Keycloak ignorée | auth | 🔴 ouvert |
| [033](033-construction-chemin-sans-safe-user-path.md) | Construction de chemin sous `/data` sans `safe_user_path` | config/db | ✅ corrigé |
| [034](034-cache-global-peuple-avant-commit.md) | Cache global peuplé avant le commit de la transaction | db/config | 🔴 ouvert |
| [035](035-env-file-read-modify-write-sans-verrou.md) | Écriture `.env` en read-modify-write sans verrou | config | 🔴 ouvert |
| [036](036-reconcile-create-task-non-reference-gc.md) | `reconcile` : `create_task` fire-and-forget non référencé (GC) | devpod | 🔴 ouvert |
| [037](037-port-reserved-fuite-sur-echec-synchrone-up.md) | Port `_reserved` jamais libéré sur échec synchrone de `up()` | devpod/exposure | 🔴 ouvert |
| [038](038-ssh-agent-orphelin-si-parsing-echoue.md) | Fuite de process `ssh-agent` si le parsing échoue | devpod | 🔴 ouvert |
| [039](039-io-bloquante-generation-devcontainer.md) | I/O bloquante synchrone (génération devcontainer) | devpod | 🔴 ouvert |
| [040](040-regex-ws-id-incoherente-service-exposure.md) | Regex `ws_id` incohérentes service vs exposure | devpod/exposure | 🔴 ouvert |
| [041](041-delete-shelve-ordre-incoherent.md) | `delete` propage le 409 de shelve après avoir tué l'`up` | devpod | 🔴 ouvert |
| [042](042-frontend-workspacecreate-erreurs-par-index-key.md) | Frontend : erreurs de source indexées par position + `key={i}` | frontend | 🔴 ouvert |
| [043](043-frontend-terminal-reconstruit-au-changement-langue.md) | Frontend : terminal reconstruit au changement de langue | frontend | 🔴 ouvert |
| [044](044-frontend-noms-session-non-encodes-url.md) | Frontend : noms de session non encodés dans l'URL | frontend | 🔴 ouvert |

## Note de méthode

Les fiches critiques et majeures ont été recoupées avec le code source réel avant rédaction. Les
fiches [013](013-csr-san-trop-permissif-usurpation-noeud.md) et
[014](014-enrolement-noeud-non-atomique-token-reutilisable.md) reposent sur l'analyse détaillée de
l'agent d'audit (lignes précises fournies) et méritent une relecture directe de
`nodes/enroll.py` avant correction.

Les bugs 002, 003, 007, 009, 010, 011, 013, 014, 015, 022, 032, 041 sont classés Fable/Opus (hors
périmètre d'une correction Sonnet directe) — voir la recommandation de modèle par bug donnée en
conversation. Cette passe ne traite que les 31 bugs recommandés pour Sonnet.

**Limite d'environnement** : ce devpod n'a pas Docker. Les tests qui nécessitent une vraie DB
Postgres (fixture `db_conn`, testcontainers) sont écrits normalement mais **skippent** ici
(`pytest.skip("Docker non disponible")`, comportement déjà prévu par la suite existante) — ils
s'exécuteront en CI ou sur toute machine avec Docker. Pour ces bugs, la vérification locale s'appuie
sur ruff + mypy + relecture manuelle du chemin de code, pas sur une exécution réelle du test.
