# Lessons apprises

## [app/lifespan] JAMAIS de synchro automatique des recettes au démarrage
Ne pas appeler `sync_bundled_recipes` / `sync_recipes_to_db` dans le lifespan (ni ailleurs au démarrage). C'est l'admin qui choisit quoi synchroniser, via `POST /admin/recipes/sync`. Demandé 3 fois par l'utilisateur — ne jamais réintroduire.

## [docker] openssh-client manquant dans l'image
`asyncio.create_subprocess_exec("ssh", ...)` lève `FileNotFoundError` si `openssh-client` n'est pas installé. L'exception est avalée silencieusement dans un `except Exception` → la feature (option_script, SSH run) ne fonctionne pas sans erreur visible. Toujours ajouter `openssh-client` dans le Dockerfile dès qu'on utilise SSH côté backend.

## [backend] resp.json() doit être dans le bloc `async with httpx.AsyncClient()`
httpx : appeler `resp.json()` après la fermeture du context manager fonctionne en pratique (corps en mémoire) mais est incorrect. Toujours mettre `return dict(resp.json())` à l'intérieur du `try` dans le `async with`.

## [backend] SSH non-interactif : PATH incomplet sur Proxmox
En SSH non-interactif, `/usr/sbin` n'est pas dans le PATH. `pvesm`, `qm` et autres binaires Proxmox sont introuvables → `2>/dev/null` masque l'erreur et la commande retourne vide. Préfixer avec `PATH=/usr/sbin:/usr/bin:$PATH` dans les `option_script` Proxmox.

## [backend] _ssh_run ne vérifiait pas le code de retour SSH
Un échec SSH (auth, host injoignable, commande absente) retournait stdout vide sans lever d'exception → erreur totalement invisible. Toujours vérifier `proc.returncode` après `communicate()` et lever `RuntimeError` avec le contenu de stderr.

## [frontend] lucide-react v1 a renommé plusieurs icônes
En lucide-react ≥1.0, les icônes suivantes n'existent plus :
- `CheckCircle2` → `CircleCheck`
- `XCircle` → `CircleX`
- `Loader2` → `LoaderCircle`
Un import d'icône inexistante donne `undefined` au runtime → le composant React crashe silencieusement (dialog vide). Vérifier avec `npx tsc --noEmit` ou inspecter `node_modules/lucide-react/dist/lucide-react.d.ts`.

## [frontend] DialogFooter avec 3 boutons : le premier est caché en viewport étroit
`DialogFooter` utilise `flex-col-reverse` sous le breakpoint `sm` (640px). Avec 3 boutons [Test, Cancel, Save], l'ordre visuel devient [Save, Cancel, Test] et Test peut être tronqué si le dialog est haut. Utiliser un `div` custom avec `sm:justify-between` : bouton test à gauche, Cancel+Save à droite.

## [openvsx] Cache TTL par-process
Avec plusieurs workers uvicorn, chaque worker a son propre cache. Acceptable pour un proxy Open VSX (pas d'état métier), mais à documenter si on passe à un déploiement multi-worker.

## [openvsx] Ordre routes FastAPI
Déclarer `/{ns}/{name}/readme` AVANT `/{ns}/{name}` dans le router, sinon FastAPI interprète "readme" comme valeur du paramètre `name`.

## [openvsx] Préfixe routes
Adapter `/api/plugins` en `/plugins` pour cohérence avec les autres routes du projet (aucun autre router n'utilise de préfixe `/api/`).

## [openvsx] env_prefix pydantic-settings
`OpenVsxSettings` utilise `OPENVSX_` — si un test lit ces variables d'env, utiliser `monkeypatch.setenv` pour garantir l'isolation (pas `os.environ` direct).

## [plugins] GET /api/plugins/search : q est désormais optionnel (min_length=1 si présent). Sans q, la clé `query` est absente de la requête Open VSX → l'API renvoie le top global trié par sortBy.

## [vault] `whoami()` du SDK harpocrate retourne 404 sur vault.yoops.org
`VaultClient.whoami()` appelle `GET /v1/api-keys/{id}` — endpoint inexistant sur vault.yoops.org. Utiliser `client._resolve_wallet_id()` qui appelle `GET /v1/api-keys/{id}/wallet-id` et retourne un 200 si le token est valide. Reconstruire la réponse depuis `client._parsed.api_key_id` et `client._parsed.permissions`.

## [docker] Docker bridge + IPv6 : urllib3 échoue sans fallback IPv4
En réseau Docker bridge, l'IPv6 n'est pas routé. Le DNS retourne des AAAA en premier ; urllib3/httpx tentent IPv6 et abandonnent sans essayer IPv4 (contrairement à curl). Fix : patcher `socket.getaddrinfo` au démarrage du process Python pour retourner les entrées AF_INET en premier quand `family=0`. Placer le patch après tous les imports (ruff E402) mais avant toute connexion runtime — urllib3 ne met pas `getaddrinfo` en cache à l'import.

## [recipes/models] Clé YAML avec tiret ≠ champ pydantic avec underscore
`memory-volume` (YAML) est vu comme champ inconnu par pydantic (`extra="forbid"`) → `ValidationError`. `RecipeMeta.model_validate()` échoue partout (galerie, sync, devcontainer). Fix : `model_validator(mode="before")` qui normalise `memory-volume` → `memory_volume` avant validation.

## [devpod/service] `--devcontainer-path` : Go filepath.Join préfixe TOUJOURS content/
DevPod fait `filepath.Join(content_dir, path)` en Go. Même un chemin absolu est préfixé par `content/` (Go ≠ Python : le '/' initial n'est pas traité comme racine). Seul un chemin relatif avec `../` peut échapper à `content/`. De plus, `{workspace_dir}` est entièrement effacé par "Delete old workspace". Solution : uploader dans `workspaces/.devpod-portal-dc/{ws_id}/` (répertoire frère, non effacé) et passer `../../.devpod-portal-dc/{ws_id}/devcontainer.json`.

## [devpod/service] Clé SSH host : temp file = timeout SSH post-devpod-up
`EXTRA_FLAGS=-i /tmp/devpod-host-xxx.pem` stocke le chemin d'un fichier temporaire supprimé dans le `finally` après `devpod up`. Le ProxyCommand `devpod ssh --stdio {ws_id}` échoue ensuite silencieusement (timeout 30 s) pour toute connexion SSH (_ssh, tmux, sessions). Le port-forward fonctionne car c'est une connexion persistante établie avant la suppression. Fix : écrire la clé à `{user_devpod_dir}/keys/{slug}.pem` (chemin stable, jamais supprimé par le guard `startswith(tempfile.gettempdir())`).

## [devpod/service] Profil et recettes : docker-tls uniquement
`_write_devcontainer` n'est appelé que pour les hosts `docker-tls`. Sur SSH, DevPod tourne
sur la VM distante — `--devcontainer-path` y est inexploitable (chemin local du portail).
Profil et recettes sont donc silencieusement ignorés sur SSH. Limitation préexistante, hors
périmètre du chantier 20. Ne pas contourner via `postCreateCommand` (interdit par PITFALLS).
Dégradation gracieuse : si le profil référencé est introuvable au moment du `up`, le workspace
démarre quand même sans profil (warning loggé, pas d'erreur HTTP).

## [mcp] Consommateurs de PORTAL_VAULT_KEK : info HKDF distinct obligatoire
`PORTAL_VAULT_KEK` est dérivée par plusieurs consommateurs (vault/pin, secrets/system → `portal-system-vault`, mcp/runtime_secrets → `mcp-backend-key-v1`). Chacun DOIT utiliser un `info=` HKDF distinct (domain separation) pour ne jamais produire la même sous-clé. Préserver cet invariant pour tout futur consommateur.

## [mcp/runtime] resolve_grant_key exige secret_value_local — pas via get_backend_key
`get_backend_key`/`list_backend_keys` omettent `secret_value_local` (hygiène : le blob chiffré ne sort jamais d'un listing/registre). `resolve_grant_key` en a besoin → le runtime (Plan 2) doit ajouter un fetcher dédié `get_backend_key_secret(conn, backend_id, key_id)` qui sélectionne `storage_type, secret_value_local, secret_value_vault_ref`. NE PAS élargir `_KEY_COLS`.

## [mcp/runtime] streamablehttp_client est @deprecated en mcp 1.28
`mcp.client.streamable_http.streamablehttp_client` porte `@deprecated` et émet un `DeprecationWarning` à l'appel (casse la sortie pristine). Utiliser `streamable_http_client(url, http_client=create_mcp_http_client(headers=, timeout=httpx.Timeout(connect_s, read=300.0)))`. Importer `create_mcp_http_client` du module public `mcp.client.streamable_http` (pas du privé `_httpx_utils`) avec `# type: ignore[attr-defined]` (module sans `__all__`). Préserver un read timeout long (300s) sinon les call_tool streamés (SSE) sont coupés. Le SDK ne ferme PAS un http_client fourni (`client_provided`) → pas de double-close.

## [mcp/server] Starlette mount redirect 307 : /mcp → /mcp/
`app.mount("/mcp", asgi)` redirige `/mcp` → `/mcp/` avec un 307. Les clients MCP doivent cibler `/mcp/` (slash final) ou suivre les redirections (`follow_redirects`). Tests in-process httpx : `follow_redirects=True` + URL avec slash final dans `streamable_http_client`.

## [mcp/server] push serveur→client list_changed HORS D'ATTEINTE en mcp 1.28
Aucune API publique pour pousser `send_tool_list_changed` aux clients depuis une tâche de fond : `StreamableHTTPSessionManager._server_instances` = transports HTTP (privé), jamais les `ServerSession` (internes à `Server.run()`). `server.request_context.session` n'existe QUE dans un handler. Recevoir les notif backend→gateway exige des sessions LONGUES (pool, incompatible open_session stateless) = sous-projet à part. → Notifications différées ; alternative = polling frontend court. Refresh catalogue TTL + health-ping périodique (dict mémoire) = faisables proprement via `asyncio.create_task` dans le lifespan.

## [mcp/server] call_tool wrappe les exceptions en isError ; read_resource/get_prompt non
Un `@server.call_tool()` qui lève → le SDK renvoie `CallToolResult(isError=True)` (lowlevel/server.py `except Exception: _make_error_result`), PAS d'exception côté client. Mais `read_resource`/`get_prompt`/`list_*` propagent l'erreur en `McpError` côté client. Tester les assertions en conséquence (isError pour call_tool, pytest.raises(McpError) pour les autres).

## [mcp/server] open_session_fn=open_session en défaut capture l'objet → monkeypatch inopérant
Un paramètre `open_session_fn: Any = open_session` fige l'objet à la définition ; `monkeypatch.setattr("portal.mcp.X.open_session", fake)` n'a alors aucun effet (le défaut tient l'ancien objet). Pour rendre patchable : défaut `None` + résolution call-time `fn = open_session_fn if open_session_fn is not None else open_session` (lookup du global au moment de l'appel).

## [spa] Routes backend atteintes par le navigateur : exclure du SPAMiddleware
Une route backend visitée directement par le navigateur (GET + `text/html`) — redirections OAuth `/oauth/authorize`, métadonnées `/.well-known/*`, transport `/mcp` — est masquée par le fallback SPA (index.html) si elle n'est pas dans `_BACKEND_NAV_PATHS` (spa.py) → React Router affiche 404. Y ajouter tout nouvel endpoint backend navigable. NE PAS y mettre les vraies pages React (ex. `/oauth/consent`).

## [mcp/db] mcp_apikey_grant.backend_key_id : nullable (backend public sans clé)
Un grant vers un backend MCP public (sans clé d'auth, ex. DeepWiki « No key ») a `backend_key_id=NULL`. La 018 le déclarait nullable, mais d'anciennes bases l'ont créé NOT NULL (fichier corrigé après application → divergence DB/modèle). La 028 réaligne (DROP NOT NULL). Symptôme : IntegrityError dans `set_grant` → 500 muet (rollback) au premier grant sans clé (le flow OAuth). Tout grant (apikey statique OU token OAuth) vers un backend public en dépend.

## [git] Vérifier la branche AVANT tout commit ou push
Tout le code va sur `dev`. `main` est réservé aux humains — jamais de commit ni de push sur `main` directement, même si l'utilisateur dit "committe" ou "pousse". Toujours vérifier `git branch --show-current` avant d'écrire du code ou de committer. Si la branche courante n'est pas `dev`, switcher avant d'agir. Ne jamais proposer `git checkout -b feat/...`.

## [exposure/cloudflare] Wildcard DNS tunnel : une commande, une fois, en dehors du portail
Décision d'architecture retenue (§F-32) : un seul CNAME wildcard `*.dev.yoops.org` → tunnel Cloudflare, posé manuellement sur la machine `cloudflare-manager` avec `cloudflared tunnel route dns <tunnel> "*.dev.yoops.org"`. Le portail ne gère pas ce DNS — il gère uniquement les routes Caddy par workspace via l'API admin. Sans ce wildcard, tous les sous-domaines `ws-*.dev.yoops.org` retournent `NXDOMAIN` (ERR_NAME_NOT_RESOLVED). Procédure documentée dans `documentations/fr/deploiement-portail.md` § Étape 9.

## [mcp/runtime] FastMCP annonce TOUJOURS les 3 capabilities
Un `FastMCP` avec seulement des `@srv.tool()` annonce quand même `tools` ET `resources` ET `prompts` dans ses capabilities. Donc `get_server_capabilities()` via un serveur FastMCP ne sert PAS à tester une logique capability-aware (ex. `advertised_kinds`, prune par kind). Construire `ServerCapabilities(tools={})` à la main, ou une session stub (`get_server_capabilities` + `list_tools`), pour représenter un backend tools-only réel.
