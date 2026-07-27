# Lessons apprises — max 50 lignes : consolider dans une leçon existante plutôt qu'ajouter.

## [backend]
- Pas de synchro auto des recettes au démarrage — choix admin (`POST /admin/recipes/sync`), demandé 3x.
- `get_cached_global()` raise si DB vide → crash lifespan avant le yield ; `get_optional_cached_global()` quand None est valide.
- Shell-out ssh : `openssh-client` dans l'image, `PATH=/usr/sbin:...`, vérifier `returncode`+stderr après `communicate()` ; httpx : `resp.json()` DANS le `async with` ; bridge IPv6 → patcher `socket.getaddrinfo` (AF_INET d'abord, pas de fallback httpx).
- Auth locale possible (`allow_local_auth`) : un user local n'a PAS de `users.sub` → ne jamais supposer un sub (OBO).
- `PORTAL_VAULT_KEK` : un `info=` HKDF distinct par consommateur (domain separation) ; `VaultClient.whoami()` n'existe pas sur vault.yoops.org (`_resolve_wallet_id()` + `_parsed.*`).

## [frontend]
- lucide-react ≥1.0 a renommé des icônes — import inexistant = crash silencieux, vérifier `tsc --noEmit`.
- Jamais de nom de rôle en dur (config serveur) : le backend expose `is_admin` ; en changeant une valeur configurable, grepper ses littéraux dans TOUT le repo.
- `DialogFooter` 3 boutons : `flex-col-reverse` tronque sous 640px → div custom `sm:justify-between`.

## [devpod/service]
- `--devcontainer-path` : devpod préfixe `content/` et efface `{workspace_dir}` → uploader dans `workspaces/.devpod-portal-dc/{ws_id}/` + chemin relatif `../../`.
- Clés/env : clé SSH host à chemin STABLE (`{user_devpod_dir}/keys/{slug}.pem`, pas de tempfile) ; tout `devpod ssh --stdio` exige `workspace_env()` (DEVPOD_HOME + DOCKER_*).
- Profil/recettes seulement pour docker-tls (SSH : `--devcontainer-path` inexploitable) ; champ `appPort` (pas `appPorts`) — les champs inconnus sont ignorés en silence.
- Bind mount / postCreateCommand = CONSTRUCTION du conteneur seulement (`--recreate`) : toute config rejouable au restart doit être ÉCRITE dans le conteneur via `ws_exec` (spec 35b), jamais delete+recreate.
- `git clone` HTTPS authentifié en postCreate = panic devpod v0.6.15 (GitCredentials, workspace nil en setup) → clone post-readiness via `ws_exec` (`http.extraHeader`) ; clones inline durcis `GIT_ASKPASS=/bin/false -c credential.helper=`.

## [mcp]
- Backends `transport=internal` : `monitor_backend_once` doit aussi resync (`ensure_devpod_backend`), pas seulement renvoyer up.
- Secrets : `get_backend_key`/`list_backend_keys` omettent la valeur — fetcher dédié `get_backend_key_secret` ; `mcp_apikey_grant.backend_key_id` nullable (backend public).
- Client mcp 1.28 : `streamable_http_client` + `create_mcp_http_client(timeout=Timeout(read=300.0))` ; `/mcp`→`/mcp/` (307) ; pas de push `list_changed` (polling front).
- `fetch_primitives` DOIT suivre `nextCursor` (les list_* sont paginés) sinon `prune_absent` efface la queue du catalogue ; les stubs de test portent la vraie signature.
- `call_tool` en échec → `CallToolResult(isError=True)`, pas d'exception ; `read_resource`/`get_prompt`/`list_*` → `McpError`.
- Pièges test/DI : défaut `open_session_fn=None` résolu call-time (un défaut-objet fige le monkeypatch) ; `Annotated[str, Path(...)]` par paramètre (jamais un `Path()` partagé) ; FastMCP annonce toujours 3 capabilities → stub manuel.
- Sécurité à moitié livrée = bug invisible : livrer détection + chemin de sortie + message distinct EN MÊME TEMPS ; un état bloquant silencieux se re-logge à chaque passe (quarantaine spec 23).

## [spa/exposure]
- Routes backend visitées par navigateur → `_BACKEND_NAV_PATHS` (sinon fallback SPA = faux 404) ; ne jamais tester une API dans la barre d'adresse (même fallback) — DevTools/curl.
- `vs-dev.yoops.org` 1 niveau (wildcard `*.yoops.org`) ; `COOKIE_DOMAIN=yoops.org` ; SessionMiddleware fige `security_flags` au `__init__` (property ignorée) — valider par `curl -D-`.
- Config JSON Caddy : placeholder inconnu remplacé par du vide en silence (forme complète `{http.request.uri}`) ; routes dynamiques perdues au restart → expose() les recrée ; wildcard DNS tunnel posé manuellement.
- `workspace_host` = IP LAN du PORTAIL (tous les tunnels y convergent), pas l'hôte des workspaces ; en DHCP, hostname re-résolu via `net.resolve_ipv4`.

## [config/api]
- JAMAIS `save_global()` depuis un process externe (cache bootstrap vide → écrase la config réelle) : API admin du portail qui tourne, sinon UPDATE SQL ciblé + restart.
- Modèle+DB ≠ configurable : vérifier que la route PUT existe ; avant un nouveau champ, vérifier qu'un existant ne porte pas la valeur ; update partiel via `model_fields_set` (jamais les défauts DTO).
- Router : routes littérales AVANT paramétrées (`/x/readme` avant `/x/{name}`) ; `/data/.env` : doubler `$` (`$$`) ; clé YAML à tiret → `model_validator(mode="before")` ; `EVENT_TYPES` → sync `events/schemas.py` + 2 tests figés.

## [observability/deploy]
- Alloy `faro.receiver` n'écoute que `/collect` → `handle_path /faro/*` (retire le préfixe) ; les filtres `logs_query` doivent suivre les labels réellement posés par Alloy.
- `docker compose` interpole TOUT le YAML avant toute commande (var manquante = tout bloqué → `docker exec` brut) ; sync des templates builtin gatée sur `version` : bumper à chaque modif de contenu.
- Cloudflare : bundle JS périmé possible après redeploy (hard refresh d'abord) ; 502 brandé sur UN chemin = routage Tunnel, pas l'app (curl direct pour isoler). L'ordre des étapes d'un script de deploy est une sémantique.

## [tests]
- `TestClient` : tout appel reste DANS le `with` (sinon post-shutdown, fuite d'event loop vers le test suivant) ; un test rouge peut tester un comportement disparu — grep le code réel d'abord.
- WebSocket : la session stub pose `auth_time` (sinon 4001 avant toute logique) ; sortir du `with websocket_connect` annule le handler ; pont PTY testé avec un vrai subprocess inerte (`sleep`).
- test1 : `uv sync --extra dev` obligatoire (sinon tests DB skippés silencieusement) — exiger des PASSED explicites ; tables FK `users.login` → seeder `users` d'abord ; `(await coro)["k"]`, pas `await coro["k"]`.
