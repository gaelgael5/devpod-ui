# M5 — Installation du portail (CA, image, compose)

**Objectif :** packager le portail en image Docker (DevPod CLI embarqué, **aucun secret dedans**),
fournir un `install.sh` qui initialise `/data` (dont la CA), génère le premier `config.yaml`, et
démarre via `docker compose` avec Caddy.

## Étapes

### M5.1 — Dockerfile (`deploy/Dockerfile`)
- Base Python 3.12 slim. Installer le binaire `devpod` (télécharger la release Linux ; pinner la
  version). Installer `openssl`, `docker` client (CLI seulement). App + deps.
- **Rien de secret** : pas d'API key, pas de clé TLS, pas de `.env`. Tout vient du volume `/data` et
  des variables d'env au runtime. Piège §D-21, principe 2.
- L'image est générique et publiable.

### M5.2 — `scripts/install.sh` (sur l'hôte du portail)
Idempotent, mais **ne régénère jamais la CA**. Piège §E-25.
1. Cloner le repo, créer `/data` si absent.
2. **CA** : si `/data/certs/ca/ca.pem` absent → générer CA (`ca-key.pem` perms 600). Sinon, skip.
   §E-25/26.
3. **Cert client portail** : si absent → générer clé + CSR + signer par la CA → `/data/certs/portal/`
   (`ca.pem`,`cert.pem`,`key.pem`). C'est ce que le portail présente aux daemons.
4. Générer `/data/config.yaml` initial si absent (valeurs depuis prompts ou env d'install).
5. Générer `/data/.env` (perms 600) : `OIDC_CLIENT_SECRET`, clé de session, `HARPOCRATE_API_KEY`
   (peut être vide → inline), `CFM_API_KEY`. Jamais commité, jamais dans l'image.
6. `docker compose up -d`.

### M5.3 — `docker-compose.yml`
- Service `portal` : monte `/data:/data`, lit `/data/.env`, expose en interne (pas en clair sur le LAN).
- Service `caddy` : monte la config, API admin sur le réseau interne (`http://caddy:2019`), volume
  pour les certs ACME. TLS wildcard `*.dev.yoops.org` via DNS-01 Cloudflare. Piège §F-30.
- Réseau interne commun ; seul Caddy est exposé (via cloudflare-manager/tunnel).
- `cloudflare-manager` : service existant, référencé (pas redéployé ici).

### M5.4 — Caddyfile / bootstrap
- Route racine `dev.yoops.org` → portail (avec auth OIDC gérée par le portail lui-même).
- Bloc wildcard `*.dev.yoops.org` → géré dynamiquement par l'API admin (les routes workspaces sont
  ajoutées en M6). Prévoir l'`authforward`/validation OIDC sur ces routes. Piège §F-33.

### M5.5 — Backup/restore
- Script `scripts/backup.sh` : `tar` de `/data` → **chiffré** (age/gpg) car contient `ca-key.pem`,
  clés SSH, éventuellement secrets inline. Piège §G-36, §G-37.
- `scripts/restore.sh` : déchiffre, restaure `/data`, **puis** documente/exécute une réconciliation :
  les workspaces ne sont pas relancés automatiquement (ils vivaient dans les daemons). Lister
  `devpod list` par user vs réalité, proposer un re-`up`. Piège §G-35. **Afficher un avertissement
  explicite** : restore = config/identité/CA, pas les sessions de travail en cours.

## Tests
- `install.sh` ré-exécuté : CA inchangée (comparer empreinte), pas d'écrasement de config.
- Image : `docker history` ne révèle aucun secret ; `grep` sur les layers vide.
- Compose monte bien `/data` ; portail démarre et lit `.env`.

## Definition of Done
- DoD commune + install de bout en bout sur une VM propre → portail accessible via Caddy + OIDC,
  un nœud (M4) enrôlable, un `up` (M3) fonctionnel.

## Pièges spécifiques M5
- §E-25/26 (CA non régénérée, protégée), §D-21 (image sans secret), §F-30 (wildcard DNS-01),
  §F-33 (fail closed), §G-35/36/37 (limites restore, chiffrement, cohérence backup).
- Piège : LXC vs VM. En LXC il faut le nesting + cgroups pour Docker, et le Docker-in-Docker de
  certaines recipes devient fragile. Recommander une **VM dédiée** pour le portail et les nœuds.
