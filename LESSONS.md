# Lessons apprises

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

## [devpod/service] Profil et recettes : docker-tls uniquement
`_write_devcontainer` n'est appelé que pour les hosts `docker-tls`. Sur SSH, DevPod tourne
sur la VM distante — `--devcontainer-path` y est inexploitable (chemin local du portail).
Profil et recettes sont donc silencieusement ignorés sur SSH. Limitation préexistante, hors
périmètre du chantier 20. Ne pas contourner via `postCreateCommand` (interdit par PITFALLS).
Dégradation gracieuse : si le profil référencé est introuvable au moment du `up`, le workspace
démarre quand même sans profil (warning loggé, pas d'erreur HTTP).
