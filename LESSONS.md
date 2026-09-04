# Lessons apprises — max 50 lignes : consolider dans une leçon existante plutôt qu'ajouter.

## [workflow]
- « Enchaîne jusqu'au bout » N'EST PAS un feu vert pour des choix d'archi contestés (ex. bastion dans le portail vs à côté ; provisioning en dur vs via automates). Verrouiller EXPLICITEMENT chaque décision d'archi avant de coder, même sous pression d'avancer — l'utilisateur est architecte.
- Ne JAMAIS expliquer un comportement runtime par déduction : lire les logs Loki d'abord (corrigé 2x sur Termix — le « nettoyage » supposé était en fait admin=False + une course de clics). Un état IHM ≠ l'état serveur : croiser les deux avant de conclure.

## [backend]
- Pas de synchro auto des recettes au démarrage — choix admin (`POST /admin/recipes/sync`), demandé 3x.
- `get_cached_global()` raise si DB vide → crash lifespan avant le yield ; `get_optional_cached_global()` quand None est valide.
- Shell-out ssh : `openssh-client` dans l'image, `PATH=/usr/sbin:...`, vérifier `returncode`+stderr après `communicate()` ; httpx : `resp.json()` DANS le `async with` ; bridge IPv6 → patcher `socket.getaddrinfo` (AF_INET d'abord, pas de fallback httpx).
- Auth locale possible (`allow_local_auth`) : un user local n'a PAS de `users.sub` → ne jamais supposer un sub (OBO).
- Toute variable lue par un `finally` s'initialise AVANT le `try` (sinon UnboundLocalError qui REMPLACE l'erreur réelle) ; un `except` qui logge `str(exc)` sans `exc_info` rend la panne indiagnosticable.
- `PORTAL_VAULT_KEK` : un `info=` HKDF distinct par consommateur (domain separation) ; `VaultClient.whoami()` n'existe pas sur vault.yoops.org (`_resolve_wallet_id()` + `_parsed.*`).

## [frontend]
- Bug d'IHM signalé : demander l'URL AVANT de diagnostiquer. Un « copier-coller cassé dans le terminal » a été analysé comme openvscode alors que c'était le terminal du portail (`FullscreenTerminal`). Ensuite, lire Loki (`job="faro"`, préfixes `terminal_diag`) plutôt que supposer : `mouseTrackingMode="any"` ⇒ le TUI capte la souris, la sélection xterm exige Maj.
- Typecheck local = `tsc -b` (comme `npm run build`), PAS `tsc --noEmit` : avec project references (tsconfig.app.json), `--noEmit` sur la racine ne traverse rien et laisse passer des erreurs (`exactOptionalPropertyTypes`, narrowing d'optional chaining) qui cassent le build Docker.
- lucide-react ≥1.0 a renommé des icônes — import inexistant = crash silencieux, vérifier `tsc -b`.
- Jamais de nom de rôle en dur (config serveur) : le backend expose `is_admin` ; en changeant une valeur configurable, grepper ses littéraux dans TOUT le repo.
- `DialogFooter` 3 boutons : `flex-col-reverse` tronque sous 640px → div custom `sm:justify-between`.

## [bastion/termix]
- Les effets d'une (dé)association se diffent sur les instances EFFECTIVES (`resolve_instances_for_user`, vide = héritage du défaut), jamais sur les explicites — sinon deprovision puis resync (qui ré-hérite le défaut) se contredisent dans la même requête (« serveur de test qui réapparaît »). Termix nomme les comptes OIDC d'après `name_path` (défaut upstream `name`, re-sync à chaque login), PAS l'email : tout matching `username=email` exige `name_path=email` côté SSO — détecté via `GET /users/oidc-config/admin` et remonté en warning. Les `termix_warnings` du PUT doivent être AFFICHÉS (toast) : best-effort invisible = bug invisible.
- Termix stocke à 0 TOUT flag omis au POST host (`x ? 1 : 0`) : envoyer explicitement `enableSsh`+`connectionType` (le gate réel de l'app iOS, modèle multi-protocole) ET `enableTerminal`/`enableFileManager`. Tout changement du payload `create_host` ⇒ bump `_REC_V` (provision.py) : les recs de version antérieure ne sont plus « same » → recréation unique des hosts existants au prochain sync.

## [devpod/service]
- `--devcontainer-path` : devpod préfixe `content/` et efface `{workspace_dir}` → uploader dans `workspaces/.devpod-portal-dc/{ws_id}/` + chemin relatif `../../`.
- Clés/env : clé SSH host à chemin STABLE (`{user_devpod_dir}/keys/{slug}.pem`, pas de tempfile) ; tout `devpod ssh --stdio` exige `workspace_env()` (DEVPOD_HOME + DOCKER_*).
- Profil/recettes seulement pour docker-tls (SSH : `--devcontainer-path` inexploitable) ; champ `appPort` (pas `appPorts`) — les champs inconnus sont ignorés en silence.
- Bind mount / postCreateCommand = CONSTRUCTION du conteneur seulement (`--recreate`) : toute config rejouable au restart doit être ÉCRITE dans le conteneur via `ws_exec` (spec 35b), jamais delete+recreate.
- `git clone` HTTPS authentifié en postCreate = panic devpod v0.6.15 (GitCredentials, workspace nil en setup) → clone post-readiness via `ws_exec` (`http.extraHeader`) ; clones inline durcis `GIT_ASKPASS=/bin/false -c credential.helper=`.
- État devpod CLIENT = `$DEVPOD_HOME/contexts/<ctx>/workspaces/<id>` ; `agent/contexts/...` n'existe que sur le NŒUD (le chercher côté portail = sonde toujours fausse → `devpod up` complet à chaque restart). Toute sonde de fond (`warm_tunnel`, sonde tmux) DOIT être dédupliquée par ws_id ET amortie après échec : sans back-off, un nœud lent reçoit un handshake de plus tous les 8 s et ne s'en sort jamais. Vérifier un chemin devpod contre le binaire (déposer un `workspace.json` bidon et regarder si `devpod list` le voit), jamais de mémoire.

## [mcp]
- Backends `transport=internal` : `monitor_backend_once` doit aussi resync (`ensure_devpod_backend`), pas seulement renvoyer up.
- Secrets : `get_backend_key`/`list_backend_keys` omettent la valeur — fetcher dédié `get_backend_key_secret` ; `mcp_apikey_grant.backend_key_id` nullable (backend public).
- Client mcp 1.28 : `streamable_http_client` + `create_mcp_http_client(timeout=Timeout(read=300.0))` ; `/mcp`→`/mcp/` (307) ; pas de push `list_changed` (polling front).
- `fetch_primitives` DOIT suivre `nextCursor` (les list_* sont paginés) sinon `prune_absent` efface la queue du catalogue ; les stubs de test portent la vraie signature.
- `call_tool` en échec → `CallToolResult(isError=True)`, pas d'exception ; `read_resource`/`get_prompt`/`list_*` → `McpError`.
- Pièges test/DI : défaut `open_session_fn=None` résolu call-time (un défaut-objet fige le monkeypatch) ; `Annotated[str, Path(...)]` par paramètre (jamais un `Path()` partagé) ; FastMCP annonce toujours 3 capabilities → stub manuel.
- Sécurité à moitié livrée = bug invisible : livrer détection + chemin de sortie + message distinct EN MÊME TEMPS ; un état bloquant silencieux se re-logge à chaque passe (quarantaine spec 23).
- Un blob (patch, archive) stocké dans un article Docflow ne se recopie JAMAIS à la main : POSTer `doc__get_document` sur la gateway en JSON-RPC depuis un script (jeton dans `.mcp.json`, `User-Agent` non-python sinon Cloudflare rend 1010) et écrire le résultat sur disque. Corruption d'un caractère localisable par force brute contre l'empreinte de la partie — d'où l'intérêt d'empreintes PAR PARTIE, pas seulement globales. Tunnel HS (CF 1033) : le portail reste joignable en LAN (`http://192.168.10.164:8080/mcp/`).

## [spa/exposure]
- Routes backend visitées par navigateur → `_BACKEND_NAV_PATHS` (sinon fallback SPA = faux 404) ; ne jamais tester une API dans la barre d'adresse (même fallback) — DevTools/curl.
- `vs-dev.yoops.org` 1 niveau (wildcard `*.yoops.org`) ; `COOKIE_DOMAIN=yoops.org` ; SessionMiddleware fige `security_flags` au `__init__` (property ignorée) — valider par `curl -D-`.
- Config JSON Caddy : placeholder inconnu remplacé par du vide en silence (forme complète `{http.request.uri}`) ; routes dynamiques perdues au restart → expose() les recrée ; wildcard DNS tunnel posé manuellement.
- `workspace_host` = IP LAN du PORTAIL (tous les tunnels y convergent), pas l'hôte des workspaces ; en DHCP, hostname re-résolu via `net.resolve_ipv4`.

## [config/api]
- JAMAIS `save_global()` depuis un process externe (cache bootstrap vide → écrase la config réelle) : API admin du portail qui tourne, sinon UPDATE SQL ciblé + restart.
- Modèle+DB ≠ configurable : vérifier que la route PUT existe ; avant un nouveau champ, vérifier qu'un existant ne porte pas la valeur ; update partiel via `model_fields_set` (jamais les défauts DTO).
- Router : routes littérales AVANT paramétrées (`/x/readme` avant `/x/{name}`) ; `/data/.env` : doubler `$` (`$$`) ; clé YAML à tiret → `model_validator(mode="before")` ; `EVENT_TYPES` → sync `events/schemas.py` + 2 tests figés. Op longue (provisioning) en `StreamingResponse` = le travail s'annule à la déconnexion client (mobile/4G surtout) → tâche de fond détachée + `job_id` + polling ; une mutation ne doit JAMAIS dépendre du maintien de la connexion.

## [observability/deploy]
- Alloy `faro.receiver` n'écoute que `/collect` → `handle_path /faro/*` (retire le préfixe) ; les filtres `logs_query` doivent suivre les labels réellement posés par Alloy.
- `docker compose` interpole TOUT le YAML avant toute commande (var manquante = tout bloqué → `docker exec` brut) ; sync des templates builtin gatée sur `version` : bumper à chaque modif de contenu.
- Cloudflare : bundle JS périmé possible après redeploy (hard refresh d'abord) ; 502 brandé sur UN chemin = routage Tunnel, pas l'app (curl direct pour isoler). L'ordre des étapes d'un script de deploy est une sémantique.
- Avant de conclure qu'un correctif **frontend** « ne marche pas » : prouver que le bundle SERVI le contient — MAIS le build Vite **code-split**. Le terminal (route lazy) vit dans un **chunk séparé** (`useVisualViewportHeight-*.js`), PAS dans `index-*.js`. Greper `index-*.js` donne un faux « 0 » : j'ai conclu à tort « déploiement périmé » pendant des heures alors que le code était bien déployé. Méthode juste : `curl .../index-*.js` puis extraire le nom du chunk du composant (`grep -oE 'useVisualViewportHeight-[^"]+\.js'`), OU greper `dist/assets/*.js` en local pour trouver quel chunk porte ma chaîne, puis greper CE chunk sur le serveur. Une sonde `console.warn('terminal_diag:…')` visible dans Faro reste le test le plus sûr que le code tourne. Ne pas confondre l'env déployé (`dev-deploy.sh` → compose dev, test1 `:8081`) et l'env regardé (`dev.yoops.org` → prod `:8080`).

## [tests]
- Front : vérifier avec `tsc -b` (ou `npm run build`), pas `tsc --noEmit` — l'incrémental de `--noEmit` rate des erreurs (ex. type utilisé non importé) que le build/dev-deploy rejette, même si vitest/eslint passent.
- `TestClient` : tout appel reste DANS le `with` (sinon post-shutdown, fuite d'event loop vers le test suivant) ; un test rouge peut tester un comportement disparu — grep le code réel d'abord. Ne jamais piper pytest dans `tail` (perd la liste des FAILED) : rediriger `grep '^FAILED'` dans un fichier, diff vs baseline pour prouver zéro régression. WebSocket : la session stub pose `auth_time` (sinon 4001 avant toute logique) ; sortir du `with websocket_connect` annule le handler ; pont PTY testé avec un vrai subprocess inerte (`sleep`).
- Sans Docker local, `TEST_DATABASE_URL=postgresql+asyncpg://postgres:devpodtests@192.168.10.250:55432/portal_tests` (le `pg-tests` de test1) dé-skippe ~560 tests : un skip n'est pas un succès. Portail en local : le cookie de session porte `domain=.dev.yoops.org`, donc un jar curl sur `127.0.0.1` ne le rejoue pas — extraire `Set-Cookie` et le repasser en `-b`.
- test1 : `uv sync --extra dev` obligatoire (sinon tests DB skippés silencieusement) — exiger des PASSED explicites ; tables FK `users.login` → seeder `users` d'abord ; `(await coro)["k"]`, pas `await coro["k"]`.

## [infra/pve]
- `pve` (192.168.10.41) porte TOUTES les VM (110 portail, 104 host-dev-01, 105/106 nœuds de test) + 10 LXC ; `pve2` (.79) n'a que la VM 500. Un reset de pve tue toutes les sessions tmux des workspaces (rien ne les restaure) : avant de suspecter le portail, vérifier l'hyperviseur — `journalctl --list-boots`, `last -x | grep -E "shutdown|reboot"` (boot SANS ligne `shutdown` = reset brutal), `journalctl -b -1 -n 50`, `pvesh get /nodes/pve/tasks`.
- Sondes posées le 27/08/2026 sur pve (persistées, survivent au reboot) : netconsole → pve2 `/var/log/netconsole-remote.log`, `flight-recorder.service` (temp/tensions/charge toutes les 30 s via `/dev/kmsg`), rasdaemon, lm-sensors. `console_loglevel=4` ⇒ seuls les messages de priorité ≤ 3 partent en netconsole (tester avec `echo "<3>test" > /dev/kmsg`, un `<6>` n'arrive jamais). Après crash : `tail -50 /var/log/netconsole-remote.log` (sur pve2) + `ras-mc-ctl --errors` + `journalctl -b -1`.
- Cluster en versions mélangées (pve 8.3.0 / pve2 9.1.9) : les 2160 `RRD update error: unknown/wrong key pve-*-9.0/...` par heure sont ce bruit-là, permanent depuis des semaines, jamais un incident. Dépôts Proxmox en `enterprise` sans souscription (401) ⇒ pve n'est plus mis à jour depuis 11/2024 ; basculer sur `pve-no-subscription` avant tout `pve8to9` (l'outil n'existe qu'à partir de pve-manager 8.4).
