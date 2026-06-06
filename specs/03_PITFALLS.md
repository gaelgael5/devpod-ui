# 03 — Pièges (lecture obligatoire avant tout milestone)

Ce fichier liste les pièges transverses. Chaque milestone répète les pièges qui lui sont propres.
Sur Sonnet, **traiter chaque piège comme une exigence, pas un conseil.**

---

## §A. Docker daemon distant + TLS

1. **`hosts` dans `daemon.json` vs systemd.** Sur Debian/Ubuntu, l'unité systemd lance
   `dockerd -H fd://`. Mettre `"hosts": [...]` dans `daemon.json` provoque
   `unable to configure the Docker daemon ... conflicting options`. **Fix obligatoire** : drop-in
   `/etc/systemd/system/docker.service.d/override.conf` :
   ```
   [Service]
   ExecStart=
   ExecStart=/usr/bin/dockerd
   ```
   puis `systemctl daemon-reload && systemctl restart docker`. Le `ExecStart=` vide est requis pour
   réinitialiser la directive avant de la redéfinir.
2. **SAN du certificat serveur.** Le cert du nœud DOIT contenir en SAN l'IP/hostname exact utilisé
   dans `docker_host` (`tcp://192.168.1.50:2376`). Sinon `x509: certificate is valid for X, not Y`.
   Inclure IP **et** hostname si les deux peuvent servir.
3. **Horloge.** TLS rejette les certs si l'horloge dérive. Installer/forcer NTP sur chaque nœud
   AVANT de générer les certs. Symptôme trompeur : `certificate has expired or is not yet valid`.
4. **`tlsverify` ⇒ mTLS.** Le daemon n'accepte que les clients porteurs d'un cert signé par la CA.
   Le portail doit présenter son cert CLIENT (`DOCKER_CERT_PATH` → `ca.pem`+`cert.pem`+`key.pem`).
   Noms de fichiers EXACTS attendus par le client Docker : `ca.pem`, `cert.pem`, `key.pem`.
5. **Pare-feu.** N'ouvrir 2376 qu'à l'IP du portail (ou au subnet Tailscale). Un 2376 en
   `tlsverify` reste une API root distante : ne jamais l'exposer largement.
6. **Version API Docker.** Si le client (embarqué via DevPod) est plus récent que le daemon du nœud,
   `client version X is too new`. Documenter une version Docker minimale pour les nœuds, ou fixer
   `DOCKER_API_VERSION`.

## §B. DevPod CLI

7. **Flags non garantis.** Les flags `devpod up` dérivent entre versions. **Toujours** exécuter
   `devpod version` et `devpod up --help` dans l'environnement cible et adapter. Ce corpus décrit
   l'intention (`--ide openvscode`, ne pas auto-ouvrir, récupérer le port), pas un contrat figé.
8. **`DEVPOD_HOME` par appel.** DevPod stocke providers + état dans son home. Si non isolé par user,
   les workspaces et providers se mélangent. Passer `DEVPOD_HOME=/data/users/<login>/devpod` dans
   l'environnement de CHAQUE subprocess. Vérifier que le dossier existe avant l'appel.
9. **Provider à initialiser par DEVPOD_HOME.** Comme l'état est isolé, le provider `docker` doit être
   ajouté/configuré pour chaque `DEVPOD_HOME` (ou réutilisé via un home "template" copié). Ne pas
   supposer qu'un `provider add` global suffit.
10. **`devpod up` est long et streame.** Build d'image + clone = minutes. **Ne jamais bloquer la
    boucle asyncio FastAPI.** Lancer via `asyncio.create_subprocess_exec`, streamer stdout/stderr
    vers `logs/`, suivre l'état dans `routes/` ou un fichier de statut. Le HTTP POST répond
    immédiatement (202 + id), l'UI poll le statut.
11. **openvscode-server n'a AUCUNE auth.** Le port ouvert par DevPod donne un accès code-exec total.
    Il DOIT être derrière le proxy authentifiant. Ne jamais exposer le port directement ni via
    cloudflare-manager sans passer par Caddy+OIDC.
12. **Récupération du port.** Selon version, le port openvscode peut être lu via
    `devpod list --output json`, `docker inspect` du conteneur du workspace, ou un mapping de port
    fixé par le portail. Préférer **fixer** le mapping (le portail choisit le port hôte et le passe),
    plutôt que parser un format de sortie instable. Voir M6.
13. **`--id` obligatoire et namespacé.** Sans `--id`, DevPod dérive l'id du source → collisions entre
    users. Imposer `--id <login>-<name>`, DNS-safe.
14. **Auto-shutdown.** L'idle timeout arrête le conteneur ; le re-`up` doit être idempotent et
    rapide. Tester le cycle up→idle→stop→up.

## §C. FastAPI / OIDC

15. **Subprocess bloquant.** Tout `subprocess.run` synchrone gèle un worker. Utiliser l'API asyncio.
16. **Validation OIDC.** Valider la signature de l'ID token contre le JWKS Keycloak, **cacher le
    JWKS** et gérer la rotation des clés (refetch sur `kid` inconnu). Tolérance d'horloge (`leeway`)
    pour `exp`/`iat`. Utiliser state + nonce + PKCE. Ne pas faire confiance aux claims sans
    vérifier `iss` et `aud`.
17. **Mapping des rôles.** Le claim de rôles Keycloak est souvent imbriqué (`realm_access.roles`).
    Lire via le chemin configuré, pas en dur. Un user sans rôle connu → 403, pas un crash.
18. **Path traversal — CRITIQUE.** `workspace.name`, `login`, noms de recipes sont utilisés dans des
    chemins de fichiers, des `--id`, des hostnames. Un `name` = `../../etc` est une RCE/escalade.
    Valider par regex stricte ET refuser tout `.` `/` `\` `..`. Construire les chemins avec
    `Path(base) / safe_name` puis vérifier `resolved.is_relative_to(base)`.
19. **Sessions.** Cookies signés, `Secure`, `HttpOnly`, `SameSite=Lax`. Clé de signature depuis
    `.env`, jamais en dur.
20. **Concurrence par workspace.** Deux `up` simultanés sur le même `<login>-<name>` corrompent
    l'état. Verrou par `ws_id` (fichier lock ou `asyncio.Lock` par id).

## §D. Secrets

21. **Jamais en build arg / ENV de Dockerfile.** Les `ARG`/`ENV` persistent dans les layers et
    `docker history`. Les secrets arrivent en `remoteEnv`/`containerEnv` (runtime) ou mount.
22. **Isolation = préfixe imposé.** En scope user, le résolveur préfixe `base_path/secret_ns/`. Une
    référence user contenant `/`, `..`, ou un autre GUID doit être REJETÉE (sinon un user lit le
    coffre d'un autre). Tester ces cas explicitement.
23. **Pas de log de secret.** Logger une config résolue est une fuite. Wrapper `Secret` avec repr
    masqué ; redaction dans les handlers de log.
24. **Perms fichiers.** `.env`, `secrets.yaml`, clés privées → `chmod 600`, propriétaire = user du
    conteneur. `ca-key.pem` → 600, jamais lisible par le groupe.

## §E. CA & enrôlement

25. **`install.sh` idempotent mais NE régénère PAS la CA.** Relancer l'install ne doit pas écraser
    `ca/`. Une nouvelle CA invalide TOUS les nœuds enrôlés. Garder : `if [ -f ca/ca.pem ]; then skip`.
26. **Protection de `ca-key.pem`.** C'est la racine de confiance de tout le mTLS. Perms 600, inclus
    dans le backup mais le backup doit être chiffré (cf. §Backup). Jamais dans l'image, jamais loggé.
27. **Join token à usage unique + TTL.** Un token d'enrôlement réutilisable = n'importe qui enrôle un
    nœud. Token aléatoire, stocké hashé, consommé à la 1re utilisation, expiration courte.
28. **Validation de la CSR.** Le portail ne signe que des CSR cohérentes (CN/SAN attendus, pas de
    flags CA). Ne pas signer aveuglément ce que le nœud envoie.
29. **Expiration des certs.** Choisir une validité longue (p.ex. 5 ans nœud/client) OU prévoir la
    rotation. Documenter la date. Un cert expiré coupe silencieusement un nœud.

## §F. Caddy / Cloudflare / exposition

30. **TLS wildcard.** `*.dev.yoops.org` nécessite un cert wildcard (DNS-01 via Cloudflare). Le HTTP-01
    ne couvre pas les wildcards. Configurer le challenge DNS dans Caddy.
31. **Reload des routes = race.** Modifier la config Caddy par rechargement complet peut couper des
    sessions actives. Préférer l'**API admin** de Caddy (ajout/suppression de route atomique) plutôt
    que réécrire le Caddyfile + reload.
32. **Ingress Cloudflare Tunnel.** Le wildcard doit être routé par le tunnel vers Caddy. Vérifier que
    cloudflare-manager pose bien une règle (ou un wildcard unique `*.dev.yoops.org` → Caddy, plus
    simple qu'un hostname par workspace).
33. **Ordre auth → proxy.** Caddy valide l'OIDC AVANT de proxifier vers openvscode. Un workspace ne
    doit jamais être joignable si la couche auth tombe (fail closed, pas fail open).

## §G. État, backup, restore

34. **Écritures atomiques.** Un crash pendant l'écriture d'un `config.yaml` corrompt la source de
    vérité unique. Toujours `tempfile` dans le même dossier + `os.replace` (atomique sur même FS).
35. **Backup = `/data` mais restore ≠ workspaces vivants.** Le backup restaure config, CA, clés,
    `DEVPOD_HOME`. Il NE restaure PAS les conteneurs workspaces (ils vivent dans les daemons des
    nœuds). Après restore sur un nouvel hôte : les workspaces doivent être re-`up`. DEVPOD_HOME peut
    référencer des conteneurs/ids absents → prévoir une commande de réconciliation (lister vs réel).
    **Documenter clairement cette limite** : « backup facile » ≠ « reprise transparente des sessions ».
36. **Chiffrer le backup.** Il contient `ca-key.pem`, les clés SSH git, éventuellement `secrets.yaml`.
    Un `tar` en clair sur un partage = fuite totale. Chiffrer (age/gpg) avant stockage.
37. **Verrou backup.** Sauvegarder pendant une écriture de config → archive incohérente. Quiescer ou
    s'appuyer sur les écritures atomiques + snapshot FS si dispo.
