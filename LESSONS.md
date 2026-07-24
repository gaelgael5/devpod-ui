# Lessons apprises

## [app/lifespan]
- JAMAIS de synchro auto des recettes au démarrage (`sync_bundled_recipes`) — c'est un choix admin via `POST /admin/recipes/sync`. Demandé 3x, ne pas réintroduire.
- `get_cached_global()` raise si DB vide → crash silencieux du lifespan AVANT le `yield` (boucle de redémarrage sans trace). Utiliser `get_optional_cached_global()` là où `None` est un état valide.

## [backend/ssh-subprocess]
- `openssh-client` absent de l'image → `FileNotFoundError` avalé silencieusement. Toujours l'ajouter au Dockerfile dès qu'on shell out vers `ssh`.
- SSH non-interactif : PATH incomplet (`/usr/sbin` absent) → binaires Proxmox introuvables, erreur masquée par `2>/dev/null`. Préfixer `PATH=/usr/sbin:/usr/bin:$PATH`.
- Toujours vérifier `proc.returncode` après `communicate()` et lever avec stderr — sinon un échec SSH retourne un stdout vide sans erreur visible.
- `resp.json()` doit être appelé DANS le `async with httpx.AsyncClient()`, pas après.
- Docker bridge + IPv6 : le DNS retourne AAAA en premier, urllib3/httpx n'essaient pas IPv4 en fallback (contrairement à curl). Patcher `socket.getaddrinfo` (après les imports, avant toute connexion) pour prioriser AF_INET.

## [frontend]
- lucide-react ≥1.0 a renommé des icônes (`CheckCircle2`→`CircleCheck`, `XCircle`→`CircleX`, `Loader2`→`LoaderCircle`) — import inexistant = composant crashe silencieusement. Vérifier avec `tsc --noEmit`.
- Ne jamais coder un NOM de rôle en dur côté frontend (`roles.includes('admin')`) : c'est une config serveur (oidc_admin_role). Changer la config a cassé toute l'UI admin. Le backend calcule et expose le booléen (`is_admin` dans GET /me). En changeant une valeur configurable, grepper ses anciens littéraux dans TOUT le repo, frontend inclus.
- `DialogFooter` (3 boutons) : `flex-col-reverse` sous 640px tronque le 1er bouton. Utiliser un `div` custom `sm:justify-between`.

## [openvsx]
- Router : `/{ns}/{name}/readme` AVANT `/{ns}/{name}` (sinon "readme" est lu comme `name`). Préfixe `/plugins` (pas `/api/`, incohérent avec le reste). `env_prefix=OPENVSX_` → `monkeypatch.setenv` dans les tests. Cache TTL par-process (à revoir si multi-worker). `q` optionnel sur `/search` → sans lui, top global Open VSX.

## [vault/harpocrate]
- `VaultClient.whoami()` → 404 sur vault.yoops.org (endpoint inexistant). Utiliser `client._resolve_wallet_id()` + reconstruire depuis `client._parsed.*`.
- `PORTAL_VAULT_KEK` a plusieurs consommateurs (vault/pin, secrets/system, mcp/runtime_secrets) — chacun DOIT avoir un `info=` HKDF distinct (domain separation), à préserver pour tout nouveau consommateur.

## [recipes/models]
- Clé YAML à tiret (`memory-volume`) ≠ champ pydantic underscore → `ValidationError` avec `extra="forbid"`. Fix : `model_validator(mode="before")` qui normalise avant validation.

## [devpod/service]
- `--devcontainer-path` : Go `filepath.Join` préfixe TOUJOURS `content/`, même un chemin absolu ; `{workspace_dir}` est effacé par devpod. Uploader dans `workspaces/.devpod-portal-dc/{ws_id}/` (frère, non effacé) + chemin relatif `../../`.
- Clé SSH host dans un tempfile → supprimée avant que `devpod ssh --stdio` (ProxyCommand) en ait besoin = timeout silencieux. Écrire dans `{user_devpod_dir}/keys/{slug}.pem` (chemin stable).
- Profil/recettes : seulement pour `docker-tls` (sur SSH, `--devcontainer-path` est inexploitable — limitation connue, pas de contournement via `postCreateCommand`).
- Tout `devpod ssh --stdio` exige `DEVPOD_HOME` + `DOCKER_*` — utiliser `workspace_env()`, jamais un env minimal.
- devcontainer.json : le champ est `appPort`, pas `appPorts` — un champ inconnu est ignoré en silence par DevPod, vérifier contre la spec avant usage.
- Un bind mount / `postCreateCommand` ne s'applique qu'à la CONSTRUCTION du conteneur : `devpod up` par défaut réutilise le conteneur existant (`--recreate` requis pour reconstruire). Toute config qui doit s'appliquer sur un simple `restart` doit être ÉCRITE dans le conteneur (`ws_exec`/`devpod ssh`), pas livrée par mount. Ne jamais proposer delete+recreate quand la contrainte utilisateur est « restart maximum » (spec 35b : livraison par écriture conteneur).
- Un `git clone` HTTPS exigeant une auth dans le `postCreateCommand` fait PANIQUER le serveur git-credentials de devpod v0.6.15 (`tunnelserver.GitCredentials`, `workspace` nil en phase setup) → tout le workspace tombe en `failed`. Cloner ces sources POST-readiness via `ws_exec` (auth par `http.extraHeader`, jamais le tunnel devpod) ; pour les clones qui restent en postCreate, désactiver le helper (`GIT_ASKPASS=/bin/false -c credential.helper=`) pour un échec propre au lieu du panic.

## [mcp]
- Backends `transport=internal` (devpod) : leur catalogue n'était resync qu'au bootstrap/nouveau user, jamais par le monitor périodique ni le bouton probe — un no-op déguisé en "toujours up". `monitor_backend_once` doit aussi resync les internes (`ensure_devpod_backend`), pas juste renvoyer `up`.
- `get_backend_key`/`list_backend_keys` omettent `secret_value_local` par hygiène — `resolve_grant_key` a besoin d'un fetcher dédié (`get_backend_key_secret`), ne pas élargir `_KEY_COLS`.
- `streamablehttp_client` est `@deprecated` en mcp 1.28 → utiliser `streamable_http_client` + `create_mcp_http_client(headers=, timeout=Timeout(read=300.0))` (read timeout long sinon les call_tool streamés SSE sont coupés).
- `app.mount("/mcp", asgi)` redirige `/mcp`→`/mcp/` (307) — cibler le slash final ou `follow_redirects=True`.
- Push serveur→client (`list_changed`) hors d'atteinte en mcp 1.28 (pas d'API publique pour les `ServerSession` internes) — polling/TTL côté frontend à la place.
- `fetch_primitives` DOIT suivre `nextCursor` (`list_tools/resources/prompts` sont paginés) : ne lire que la page 1 + `prune_absent` = queue du catalogue effacée à chaque probe (bug registre fédéré partiel docflow `create_document`/`set_document_parent`). Tout stub de session en test doit porter la vraie signature `list_tools(cursor, *, params)`.
- `call_tool` qui lève → `CallToolResult(isError=True)`, PAS d'exception client ; `read_resource`/`get_prompt`/`list_*` propagent en `McpError`. Adapter les assertions de test en conséquence.
- Paramètre par défaut `open_session_fn: Any = open_session` fige l'objet à la définition → `monkeypatch.setattr` inopérant. Défaut `None` + résolution call-time.
- `_ID = Path(...)` partagé entre params de noms différents (`key_id`/`apikey_id`) fige l'alias sur le premier → 422 sur les suivants. Utiliser `Annotated[str, Path(...)]` par paramètre, jamais un objet `Path()` partagé.
- `FastMCP` annonce toujours les 3 capabilities (tools/resources/prompts) même avec un seul `@srv.tool()` — inutilisable pour tester une logique capability-aware ; construire une session stub à la main.
- `mcp_apikey_grant.backend_key_id` doit être nullable (backend public sans clé) — vérifier après toute migration touchant cette contrainte (symptôme : 500 muet au premier grant public).

- Un mécanisme de sécurité à moitié implémenté = bug invisible : la quarantaine anti rug-pull (spec 23) posait un flag collant SANS route d'approbation ni erreur dédiée → « unknown tool » trompeur pendant 24 h (create_document). Toujours livrer détection + chemin de sortie + message distinct EN MÊME TEMPS ; un état bloquant silencieux doit se re-logger à chaque passe, pas seulement à la pose.

## [spa]
- Toute route backend visitée directement par le navigateur (OAuth redirects, `/.well-known/*`, `/mcp`) doit être dans `_BACKEND_NAV_PATHS` (spa.py), sinon le fallback SPA (`Accept: text/html`) la masque → faux 404 React Router. NE PAS y mettre les vraies pages React.
- Corollaire diagnostic : ne jamais tester une route API en la tapant dans la barre d'adresse du navigateur — `Accept: text/html` déclenche ce même fallback et donne un faux négatif. Utiliser DevTools Network (vraie requête `fetch`) ou `curl`.

## [tests]
- `TestClient` : tout appel (`client.get(...)`) fait APRÈS la sortie du bloc `with TestClient(app) as client:` s'exécute post-lifespan-shutdown (`dispose_engine()` déjà passé) → reconnexion d'engine liée à une event loop mourante, fuite vers le test suivant (`attached to a different loop`). Toujours garder les appels DANS le `with`.
- Avant de chasser un test rouge : vérifier s'il teste un comportement disparu (signature changée, champ renommé) plutôt que de le réparer mécaniquement — grep le code réel d'abord.
- WebSocket TestClient : la session injectée doit poser `auth_time` (sinon `session_within_max_age` → 4001 avant toute validation) ; la sortie du `with websocket_connect` ANNULE le handler — provoquer l'étape à tester (ex. écho reçu) avant de fermer. Pont PTY : le tester avec un subprocess réel inerte (`sleep`) qui tient le slave — l'écho vient du tty, un fake à pipes donne un EOF immédiat.

## [git]
- Tout le code va sur `dev`, jamais `main` (même si "committe"/"pousse" sans préciser). Vérifier `git branch --show-current` avant tout commit. Ne jamais proposer `git checkout -b feat/...`.

## [exposure]
- Proxy VS Code : `vs-dev.yoops.org` (1 niveau, couvert par le wildcard `*.yoops.org`) — 2 niveaux (`*.dev.yoops.org`) hors Cloudflare Universal SSL. `COOKIE_DOMAIN=yoops.org` obligatoire. Placeholders `{http.reverse_proxy.header.*}` non fiables dans la config JSON Caddy (routes handle_response) — les éviter.
- Wildcard DNS tunnel (`*.dev.yoops.org`) posé une fois, manuellement, hors du portail — sans lui tous les sous-domaines `ws-*` sont NXDOMAIN.
- Cookie de session : surcharger un attribut (`domain`) de `SessionMiddleware` en property ne sert à rien — Starlette fige tout dans `security_flags` au `__init__`, la property n'est jamais lue. Vérifier le mécanisme de la version installée de la lib, et valider par le comportement observable (`curl -D-` sur le Set-Cookie), pas par la valeur calculée en interne.
- Config JSON Caddy (API admin) : les raccourcis Caddyfile (`{uri}`, `{path}`) n'existent pas — un placeholder inconnu est remplacé par du vide, silencieusement. Toujours la forme complète (`{http.request.uri}`). Les routes dynamiques sont perdues à chaque restart de Caddy (pas de `--resume`) : un expose() doit les recréer.
- `workspace_host` n'est PAS l'hôte des workspaces : tous les tunnels SSH convergent sur le conteneur portail (`node_ip = caddy.portal_host = "portal"`), c'est donc l'IP LAN du portail — une seule valeur couvre N nœuds. En DHCP, le mettre en hostname et le re-résoudre via `<host>.<local_domain>` (`net.resolve_ipv4`). Ne jamais prioriser `node_ip` (nom Docker interne) devant lui dans les fallbacks URL directe.

## [admin/config]
- JAMAIS `save_global()` depuis un process externe (`docker exec python`) : `load_global()` y retombe sur la config bootstrap VIDE (cache jamais réchauffé) → le save écrase toute la config réelle (hosts effacés sur test1, 2026-07-06). Toute mutation de config passe par l'API admin du portail qui tourne ; à défaut, UPDATE SQL ciblé + restart.
- Un modèle pydantic + persistance DB ne veut pas dire qu'un réglage est configurable : vérifier qu'une route PUT existe réellement avant de supposer qu'un admin peut le changer (ex. `logs.enabled`/`loki_push_url` avaient le modèle + la DB mais aucune route d'écriture — seule la lecture existait).
- Avant d'ajouter un nouveau champ de config, vérifier qu'un champ existant ne porte pas déjà la même valeur sous un autre nom (`workspace_host` couvrait déjà "IP directe du host").

## [compose/env]
- Tout `$` écrit dans `/data/.env` doit être doublé (`$$`) — sinon un hash bcrypt est tronqué par l'interpolation docker-compose (`Invalid salt`).

## [api]
- Update partiel : ne jamais écraser un spec stocké avec les défauts du DTO. Fusionner via `req.model_fields_set` — seuls les champs explicitement envoyés priment.

## [observability/alloy-caddy]
- `faro.receiver` (Alloy) n'écoute QUE sur `/collect`, aucun préfixe configurable côté composant — un `reverse_proxy /faro/collect* alloy:PORT` transmet le chemin complet et prend un 404. Utiliser `handle_path /faro/* { reverse_proxy alloy:PORT }` pour retirer le préfixe public avant de proxier.
- `docker compose` (même `exec`/`logs` sur UN service) interpole tout le YAML avant d'exécuter quoi que ce soit — une var requise manquante pour un service sans rapport bloque TOUTES les commandes compose. Contournement diagnostic : `docker exec <container>`/`docker logs <container>` (docker brut, ignore le compose file).
- Sync des templates compose builtin (`compose_bootstrap.py`) gatée sur un simple `version` string : modifier le contenu (ex. `extra_files`) SANS bumper la version → la resynchro ne se déclenche jamais sur les déploiements existants, silencieusement, aucune erreur ni log.

## [deploy/cloudflare]
- Cloudflare (edge + navigateur) peut servir un bundle JS périmé un moment après un redeploy backend réussi sur dev.yoops.org — hard refresh (Ctrl+Shift+R) avant de conclure qu'un fix ne marche pas.
- Un 502 Cloudflare "brandé" (Ray ID, page HTML complète) sur UN chemin précis pendant que le reste du domaine fonctionne = problème de routage du Tunnel Cloudflare, pas de l'app. Isoler via curl direct (bypass Caddy puis bypass tunnel) avant de creuser côté code — si backend+Caddy répondent proprement en direct, c'est hors périmètre du dépôt (config tunnel/cloudflare-manager).

## [mcp/logs_query]
- Les filtres structurés de `logs_query` (host/role/project/service/unit/job) doivent suivre les labels RÉELLEMENT posés par Alloy (`external_labels`/`extra_log_labels`) — une nouvelle source de logs (ex. `job=faro` pour le frontend) est invisible pour un agent si le filtre ET la description de l'outil ne la mentionnent pas explicitement. Vérifier en conditions réelles (cache réchauffé via `warm_global_cache`, pas un script isolé) avant de considérer l'outil fonctionnel.

## [tests/test1]
- Sur test1, `uv sync` SANS `--extra dev` → testcontainers/docker absents → les tests DB skippent SILENCIEUSEMENT (affichent « Docker non disponible » alors que Docker est là). Toujours `uv sync --extra dev`, et exiger des PASSED explicites (`-v | grep PASSED`) plutôt qu'un exit code — piégé deux fois dans la même session.
- `await coro["k"]` subscripte la coroutine (précédence), pas le résultat : écrire `(await coro)["k"]`. Invisible tant que le test skip localement — encore une raison de valider les tests DB sur test1 avant de conclure.
- Tables avec FK vers `users.login` (profiles, mcp_profile, user_services…) : tout test DB doit seeder la ligne `users` d'abord (pattern `_seed_user` de test_profiles.py).
- Stub `_test/login` des tests websocket : poser `request.session["auth_time"] = int(time.time())` en plus de `["user"]`, sinon `session_within_max_age` (plafond bug 032) ferme le WS en 4001 « Session expired » AVANT toute logique — symptôme trompeur d'échec d'auth.

## [deploy]
- En fusionnant des scripts, l'ORDRE des étapes est une sémantique : le check « port 80 libre ? » n'a de sens qu'APRÈS le down de la stack (sinon notre propre Caddy se détecte comme conflit et 8090 se persiste dans .env → front mort). Vérifier les dépendances implicites entre étapes avant de déplacer un bloc.

## [events]
- Ajouter un type dans `EVENT_TYPES` (models.py) impose 3 synchronisations sinon crash à l'import (garde `schemas.py`) : dataSchema dans `events/schemas.py`, plus les tests figés `tests/events/test_models.py` et `tests/routes/test_event_schemas.py` (préférer dériver d'`EVENT_TYPES` que coder le compte en dur).

## [auth]
- Le portail N'EST PAS OIDC-only : `allow_local_auth` + `local_user`/`local_password_hash` (bcrypt) donnent un login local (première connexion / bootstrap admin, et fallback si OIDC absent). Conséquence OBO : un user local n'a PAS de `users.sub` → aucune identité à propager. Ne pas supposer qu'un user a un sub.
