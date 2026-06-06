# Installation environnement DEV — workspace-portal

Procédure d'**initialisation** de la VM portail de test (`portail-dev`) sur Proxmox.
À exécuter **une seule fois** par l'opérateur. Les déploiements ultérieurs passent
ensuite exclusivement par `.\scripts\remote-deploy.ps1 portail-dev` — c'est la commande
que Claude utilise pour livrer et tester ses modifications.

---

## Prérequis

Accès SSH au host Proxmox configuré avec l'alias `pve` dans `~\.ssh\config` :

```
Host pve
    HostName 192.168.1.X
    User root
    IdentityFile ~/.ssh/id_ed25519
```

Vérifier : `ssh pve "hostname"` doit répondre.

### Template de référence Debian 12

Toutes les VMs sont clonées depuis un template. Vérifier qu'il en existe un :

```bash
ssh pve "qm list | grep template"
```

S'il n'en existe pas, le créer avec `create-vm-generic.sh` (opération unique par cluster) :

```bash
ssh pve "curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/dev/scripts/create-vm-generic.sh \
  | bash -s -- 9000"
```

- `9000` → VMID du template (libre, conventionnellement ≥ 9000 pour les templates)

Le script télécharge l'image Debian 12 cloud, configure le template (cloud-init, guest agent, resize), et le marque `template: 1`. Durée : 5 à 10 min selon la connexion.

**Cette étape est à faire une seule fois par cluster Proxmox.** Conserver le VMID du template — il sera passé en `--template` à l'étape suivante.

---

## Étape 1 — Créer la VM `portail-dev`

Depuis le host Proxmox, choisir un VMID libre (ex : 110).

**Avec IP fixe** (recommandé — l'IP est connue d'avance) :

```bash
ssh pve "curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/dev/scripts/clone-vm-node.sh \
  | bash -s -- 110 --name portail-dev --template 9000 --ip 192.168.1.100/24 --gw 192.168.1.1"
```

**Avec DHCP** (l'IP est détectée automatiquement via guest agent et affichée en fin de script) :

```bash
ssh pve "curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/dev/scripts/clone-vm-node.sh \
  | bash -s -- 110 --name portail-dev --template 9000"
```

- `110` → VMID de la nouvelle VM (libre, ni VM ni LXC existant)
- `--template 9000` → VMID du template à cloner (voir `qm list`). Si omis, le script prend le premier template disponible.
- `--storage vmpool` → stockage Proxmox cible (ex. `vmpool`, `local-lvm`, `local-zfs`). Si omis, le clone va dans le même stockage que le template.

Le script attend que SSH réponde avant de rendre la main, puis affiche l'IP de la VM.
**Noter l'IP affichée** — elle sera nécessaire à l'étape 2 (`REMOTE_HOST`).

---

## Étape 2 — Configurer le fichier `.env` local

```powershell
Copy-Item scripts\.env.portail-dev.remote-deploy.example scripts\.env.portail-dev.remote-deploy
notepad scripts\.env.portail-dev.remote-deploy
```

> `scripts\.env.portail-dev.remote-deploy` est gitignored — ne jamais le committer.

Renseigner au minimum :

```dotenv
REMOTE_HOST=192.168.1.100        # IP de la VM créée à l'étape 1
OIDC_CLIENT_SECRET=              # Keycloak → Clients → workspace-portal → Credentials
```

Le reste a des valeurs par défaut adaptées au test :

```dotenv
REMOTE_USER=root
REMOTE_KEY=~\.ssh\id_ed25519
BRANCH=dev
APP_DIR=/opt/workspace-portal
COMPOSE_FILE=deploy/docker-compose.yml
DEPLOY_SCRIPT=./scripts/deploy-portal.sh
PORTAL_BASE_DOMAIN=dev.yoops.org
PORTAL_EXTERNAL_URL=https://dev.yoops.org
PORTAL_OIDC_ISSUER=https://security.yoops.org/realms/yoops
PORTAL_OIDC_CLIENT_ID=workspace-portal
```

---

## Étape 3 — Configurer Keycloak (si pas déjà fait)

Dans la console admin Keycloak (`https://security.yoops.org/admin`), realm `yoops` :

1. Créer les rôles realm `admin` et `dev`
2. Créer le client OIDC `workspace-portal` (confidentiel, Standard flow, redirect URI `https://dev.yoops.org/auth/callback`)
3. Copier le **Client secret** → c'est la valeur `OIDC_CLIENT_SECRET` du `.env`
4. Créer un utilisateur, lui assigner le rôle `admin`

Guide complet : [`documentations/fr/deploiement-portail.md`](fr/deploiement-portail.md) § Étape 6.

---

## Étape 4 — Premier déploiement

```powershell
.\scripts\remote-deploy.ps1 portail-dev
```

Le script se connecte en SSH sur la VM et exécute `deploy-portal.sh`, qui :

1. Clone le repo (`BRANCH=dev`) dans `/opt/workspace-portal`
2. Initialise `/data` (CA mTLS, `config.yaml`, `.env`) via `install.sh`
3. Injecte `OIDC_CLIENT_SECRET` dans `/data/.env`
4. Build l'image Docker et démarre la stack (`portal` + `caddy`)
5. Smoke test sur `/health` (timeout 60 s)

Affiche en fin d'exécution les 80 dernières lignes de logs.

---

## Étape 5 — Vérifier

```bash
# Health check direct
curl http://192.168.1.100:8080/health
# → {"status":"ok"}
```

Ouvrir `https://dev.yoops.org` dans un navigateur — le portail redirige vers Keycloak.
Se connecter avec le compte admin → la page d'accueil du portail doit s'afficher.

---

## Workflow ensuite

L'init est terminée. Deux modes de livraison selon qui redéploie :

### Opérateur — depuis la VM directement

```bash
ssh root@192.168.1.100
cd /opt/workspace-portal
./scripts/dev-deploy.sh        # pull + build + restart + smoke test
```

Ou pour une branche spécifique :
```bash
./scripts/dev-deploy.sh dev
```

### Claude — depuis Windows

Claude exécute le redéploiement via :

```powershell
.\scripts\remote-deploy.ps1 portail-dev
```

C'est la commande que Claude utilise après chaque modification pour valider sur la VM.
Pas de `scp`, pas de build local poussé à la main.

---

## Dépannage

### `Permission denied (publickey)` à la connexion SSH

La clé de l'opérateur n'est pas dans `/root/.ssh/authorized_keys` de la VM.
Le script `clone-vm-node.sh` injecte automatiquement la clé par défaut (`~/.ssh/id_ed25519.pub`
du host PVE). Si la clé locale Windows est différente, l'ajouter manuellement :

```bash
ssh pve "ssh root@192.168.1.100 'cat >> ~/.ssh/authorized_keys'" < ~/.ssh/id_ed25519.pub
```

### `/health` ne répond pas après 60 s

```powershell
.\scripts\remote-deploy.ps1 portail-dev -LogLines 200
```

Ou directement sur la VM :
```bash
ssh root@192.168.1.100 "docker compose -f /opt/workspace-portal/deploy/docker-compose.yml logs --tail=100 portal"
```

| Log | Cause | Fix |
|---|---|---|
| `SESSION_SECRET_KEY not set` | `/data/.env` absent ou vide | Vérifier le volume dans `docker-compose.yml` |
| `invalid_client` / `401` | `OIDC_CLIENT_SECRET` incorrect | Récupérer le bon secret dans Keycloak |
| `redirect_uri_mismatch` | URI callback absente du client | Ajouter `https://dev.yoops.org/auth/callback` dans Keycloak |

### Reset complet

⚠ Régénère la CA — tous les nœuds enrôlés devront être ré-enrôlés.

```bash
ssh root@192.168.1.100 "
  docker compose -f /opt/workspace-portal/deploy/docker-compose.yml down --remove-orphans
  rm -rf /data
"
.\scripts\remote-deploy.ps1 portail-dev
```

### Supprimer la VM

```bash
ssh pve "qm stop 110 && qm destroy 110 --purge"
```
