# M4 — Enrôlement des nœuds (CA, mTLS, join token)

**Objectif :** ajouter un nœud Docker au portail via un script d'install qui génère sa clé
**localement**, fait signer une CSR par la CA du portail, configure le daemon en mTLS, et s'ajoute à
la config — le tout déclenché par un join token à usage unique.

## Modèle de confiance
- Le portail est la **CA**. `ca/ca.pem` + `ca/ca-key.pem` sont créés en M5 (install portail), pas ici.
- Le portail possède un cert **client** (`certs/portal/`) signé par la CA, qu'il présente aux daemons.
- Chaque nœud a un cert **serveur** signé par la CA, avec l'IP/hostname en SAN. Piège §A-2.
- `tlsverify` côté daemon ⇒ seul un client au cert signé par la CA (= le portail) peut piloter. §A-4.

## Étapes

### M4.1 — Génération du join token (`nodes/enroll.py`, côté portail, admin)
- `POST /admin/nodes/token {node_name, address}` → token aléatoire (32+ octets), stocké **hashé**
  avec TTL court et `node_name`/`address` attendus. Piège §E-27.
- Renvoie la commande prête à copier (voir M4.4).

### M4.2 — Endpoint de signature CSR (`POST /admin/nodes/enroll`)
- Auth par join token (Bearer), consommé à la 1re utilisation (puis invalidé). Piège §E-27.
- Body : CSR PEM générée par le nœud.
- **Validation de la CSR** : CN attendu = `node_name` ; SAN doit contenir l'`address` (IP/hostname)
  déclarée ; refuser tout `basicConstraints CA:TRUE` ou usage non prévu. Piège §E-28.
- Signe avec `ca-key.pem` (validité longue, p.ex. 1825 j — documenter, §E-29).
- Renvoie : cert serveur signé + `ca.pem`.
- Ajoute le host dans `config.yaml` global (`type: docker-tls`, `docker_host: tcp://<address>:2376`),
  écriture atomique. Copie le cert dans `certs/nodes/<node_name>/` pour suivi.

### M4.3 — `scripts/install-node.sh`
Idempotent. Étapes :
1. Installer Docker Engine (apt ; ou get.docker.com).
2. **Forcer NTP** (`timedatectl set-ntp true`) AVANT la génération de cert. Piège §A-3.
3. Générer clé privée serveur **localement** (`openssl genpkey`), créer une CSR avec CN=node_name et
   SAN=IP+hostname. La clé ne quitte jamais le nœud. Piège §A-2, principe « pas de clé en transit ».
4. `curl` la CSR vers `POST /admin/nodes/enroll` avec le join token → récupère cert + ca.pem.
5. Déposer `ca.pem`, `server-cert.pem`, `server-key.pem` (perms 600 sur la clé) dans `/etc/docker/tls/`.
6. Écrire `daemon.json` (`hosts` tcp 2376 + tlsverify + chemins certs).
7. **Drop-in systemd** pour neutraliser `-H fd://` (sinon conflit). Piège §A-1 :
   ```
   mkdir -p /etc/systemd/system/docker.service.d
   printf '[Service]\nExecStart=\nExecStart=/usr/bin/dockerd\n' > .../override.conf
   systemctl daemon-reload && systemctl restart docker
   ```
8. Pare-feu : autoriser 2376 uniquement depuis l'IP du portail / subnet Tailscale. Piège §A-5.
9. Vérification : `docker --tlsverify --tlscacert ... -H tcp://localhost:2376 version` doit réussir
   en local ; le portail teste depuis l'extérieur.

### M4.4 — Commande d'enrôlement affichée à l'admin
```
curl -sSL https://dev.yoops.org/install-node.sh | bash -s -- \
  --portal https://dev.yoops.org --token <join-token> \
  --node-name pve2-docker --address 192.168.1.50
```

## Tests
- Signature : une CSR valide est signée ; une CSR avec CA:TRUE ou SAN manquant est refusée (§E-28).
- Token : réutilisation refusée ; token expiré refusé (§E-27).
- Le host est bien ajouté à `config.yaml` (atomique) après enrôlement.
- (Intégration, manuel) : un nœud réel enrôlé est pilotable par M3 (`devpod up` dessus).

## Definition of Done
- DoD commune + tests verts + un nœud réel enrôlé de bout en bout, vérifié par un `up` M3.

## Pièges spécifiques M4
- §A-1 (systemd vs daemon.json — LE piège qui bloque le restart), §A-2 (SAN), §A-3 (NTP),
  §A-4 (mTLS), §A-5 (firewall), §E-27 (token usage unique), §E-28 (validation CSR), §E-29 (expiration).
- Repli documenté : si la gestion CA pèse, le provider `ssh` (script crée user `devpod` + groupe
  `docker` + authorized_keys) est l'alternative. Ne PAS l'implémenter par défaut ; le mentionner.
