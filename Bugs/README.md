# Bugs — registre d'audit

Un fichier par bug. Chaque fiche documente un défaut **confirmé par lecture du code**,
avec de quoi le corriger — **sans le corriger ici**.

Audit réalisé le 2026-07-03 sur la branche `dev`, par balayage complet des sous-systèmes
(devpod/exposure, auth/session/vault/secrets, config/DB, MCP, compose/nodes/certificats, frontend).
Les bugs déjà corrigés pendant la session (cookie de session, placeholder Caddy, reconnexion
automatique, cycle de vie des tunnels) ne figurent pas ici.

## Convention

`NNN-<slug>.md` — numéro d'ordre + slug court. Sévérité : critique / majeur / mineur.

## Index

### Critiques

| # | Sujet | Sous-système |
|---|-------|--------------|
| [002](002-fuite-secrets-env-resolver-compose.md) | Fuite de secrets du portail (KEK/session/OIDC) via le résolveur `env://` en compose | secrets/compose |
| [003](003-absence-verrou-lifecycle-workspace.md) | Absence de verrou lifecycle : `up`/`stop`/`delete` concurrents corrompent l'état | devpod |

### Majeurs

| # | Sujet | Sous-système |
|---|-------|--------------|
| [001](001-collision-allocation-ports-openvscode.md) | Collision d'allocation de ports openvscode entre workspaces | devpod/exposure |
| [004](004-culture-non-persistee-userconfig.md) | Champ `culture` de `UserConfig` ni écrit ni relu (perte silencieuse) | config/db |
| [005](005-ws-proxy-websocket-ignore-ws-id-hint.md) | Proxy WebSocket VS Code ignore le `ws_id_hint` → mauvais workspace | exposure |
| [006](006-stop-ignore-returncode-devpod.md) | `stop()` écrit « stopped » même si `devpod stop` a échoué | devpod |
| [007](007-write-status-ressuscite-ligne-supprimee.md) | `_write_status` (upsert) ressuscite une ligne supprimée | devpod/db |
| [008](008-put-me-config-sans-allowlist-secret-ns.md) | `PUT /me/config` sans allowlist : `secret_ns`/`version` réécrivables | config/routes |
| [009](009-lost-update-userconfig-sans-verrou.md) | Lost update : pas de verrou sur load→modify→save de `UserConfig` | config/db |
| [010](010-upserts-check-then-insert-non-atomiques.md) | Upserts check-then-insert non atomiques (UniqueViolation) | db |
| [011](011-ensure-user-db-invente-secret-ns.md) | `ensure_user_db` fabrique un `secret_ns` aléatoire → secrets orphelins | db/secrets |
| [012](012-portal-api-key-comparaison-non-constant-time.md) | Comparaison non constant-time de `portal_api_key` (bearer admin) | auth |
| [013](013-csr-san-trop-permissif-usurpation-noeud.md) | SAN de CSR trop permissif : cert valide pour d'autres nœuds | nodes |
| [014](014-enrolement-noeud-non-atomique-token-reutilisable.md) | Enrôlement non atomique → join token réutilisable | nodes |
| [015](015-course-allocation-ports-compose.md) | Course sur l'allocation de ports compose | compose |
| [016](016-stream-host-command-sous-process-ssh-orphelin.md) | Sous-process ssh non tué à la déconnexion → déploiement orphelin | compose |
| [017](017-mcp-exceptions-non-gerees-echappent-dispatch.md) | MCP : exceptions non gérées échappent au dispatch → trou d'audit | mcp |
| [018](018-frontend-delete-echec-silencieux-apifetch.md) | Frontend : échec silencieux systémique des DELETE (`apiFetch`) | frontend |
| [019](019-frontend-delete-workspace-non-controle.md) | Frontend : `deleteWorkspace` — suppression finale non contrôlée | frontend |
| [020](020-frontend-streams-reader-non-annule.md) | Frontend : streams fetch dont le reader n'est jamais annulé | frontend |

### Mineurs

| # | Sujet | Sous-système |
|---|-------|--------------|
| [021](021-proxmox-password-clair-renvoye-api.md) | Mot de passe Proxmox stocké/renvoyé en clair | proxmox |
| [022](022-ssrf-dns-rebinding-compose-sources.md) | SSRF résiduelle : DNS rebinding (TOCTOU) | compose_sources |
| [023](023-proxmox-fetch-spec-sans-ssrf.md) | Fetch de spec proxmox sans contrôle SSRF | proxmox |
| [024](024-proxmox-substitute-non-quote-resubstitution-token.md) | Substitution shell non quotée + re-substitution du token | proxmox/test_vm |
| [025](025-mcp-io-bloquante-operations-yaml.md) | MCP : I/O fichier synchrone bloquant | mcp |
| [026](026-mcp-transaction-db-pendant-probe-reseau.md) | MCP : transaction DB tenue pendant l'I/O réseau du probe | mcp |
| [027](027-mcp-injection-logql-non-echappee.md) | MCP : injection LogQL par interpolation non échappée | mcp |
| [028](028-mcp-deserialisation-loki-non-validee.md) | MCP : désérialisation non validée de la réponse Loki | mcp |
| [029](029-mcp-bearergate-filtre-seulement-http.md) | MCP : `BearerGate` ne filtre que les scopes `http` | mcp |
| [030](030-vault-master-keys-en-memoire-apres-expiration.md) | Vault : master keys en mémoire au-delà de l'expiration du cookie | vault |
| [031](031-vault-session-id-vide-non-rejete.md) | Vault : `session_id` vide non rejeté | vault |
| [032](032-roles-figes-dans-cookie-revocation-non-prise-en-compte.md) | Rôles figés dans le cookie — révocation Keycloak ignorée | auth |
| [033](033-construction-chemin-sans-safe-user-path.md) | Construction de chemin sous `/data` sans `safe_user_path` | config/db |
| [034](034-cache-global-peuple-avant-commit.md) | Cache global peuplé avant le commit de la transaction | db/config |
| [035](035-env-file-read-modify-write-sans-verrou.md) | Écriture `.env` en read-modify-write sans verrou | config |
| [036](036-reconcile-create-task-non-reference-gc.md) | `reconcile` : `create_task` fire-and-forget non référencé (GC) | devpod |
| [037](037-port-reserved-fuite-sur-echec-synchrone-up.md) | Port `_reserved` jamais libéré sur échec synchrone de `up()` | devpod/exposure |
| [038](038-ssh-agent-orphelin-si-parsing-echoue.md) | Fuite de process `ssh-agent` si le parsing échoue | devpod |
| [039](039-io-bloquante-generation-devcontainer.md) | I/O bloquante synchrone (génération devcontainer) | devpod |
| [040](040-regex-ws-id-incoherente-service-exposure.md) | Regex `ws_id` incohérentes service vs exposure | devpod/exposure |
| [041](041-delete-shelve-ordre-incoherent.md) | `delete` propage le 409 de shelve après avoir tué l'`up` | devpod |
| [042](042-frontend-workspacecreate-erreurs-par-index-key.md) | Frontend : erreurs de source indexées par position + `key={i}` | frontend |
| [043](043-frontend-terminal-reconstruit-au-changement-langue.md) | Frontend : terminal reconstruit au changement de langue | frontend |
| [044](044-frontend-noms-session-non-encodes-url.md) | Frontend : noms de session non encodés dans l'URL | frontend |

## Note de méthode

Les fiches critiques et majeures ont été recoupées avec le code source réel avant rédaction. Les
fiches [013](013-csr-san-trop-permissif-usurpation-noeud.md) et
[014](014-enrolement-noeud-non-atomique-token-reutilisable.md) reposent sur l'analyse détaillée de
l'agent d'audit (lignes précises fournies) et méritent une relecture directe de
`nodes/enroll.py` avant correction.
