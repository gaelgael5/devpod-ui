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
