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
  | bash -s -- 9000 --storage vmpool"
```

- `9000` → VMID du template (libre, conventionnellement ≥ 9000 pour les templates)
- `--storage vmpool` → stockage Proxmox où créer le template. Voir les stockages disponibles :
  ```bash
  ssh pve "pvesm status"
  ```
  Si omis, le script auto-détecte dans l'ordre : `local-lvm` > `local-zfs` > `local`.

Le script télécharge l'image Debian 12 cloud, configure le template (cloud-init, guest agent, resize), et le marque `template: 1`. Durée : 5 à 10 min selon la connexion.

**Cette étape est à faire une seule fois par cluster Proxmox.** Conserver le VMID du template — il sera passé en `--template` à l'étape suivante.

---

## Étape 1 — Créer la VM `portail-dev`

Depuis le host Proxmox, choisir un VMID libre (ex : 110).

### Prérequis — clé SSH du poste opérateur sur PVE

Le script `clone-vm-node.sh` injecte **automatiquement** la clé SSH du host PVE
(`/root/.ssh/id_ed25519.pub`, auto-détectée). Pour te connecter à la VM **aussi
depuis ton poste de travail** (et pas seulement depuis PVE), copie ta clé publique
sur PVE et passe-la au script en `--extra-sshkey`.

Choisis le contexte d'où tu pilotes :

<details open>
<summary><b>A — Depuis Windows (PowerShell)</b></summary>

> **Commandes à exécuter dans PowerShell** (pas cmd.exe).

**1 — Vérifier si une clé SSH existe déjà :**

```powershell
Test-Path "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

Si `False`, générer une clé :

```powershell
ssh-keygen -t ed25519 -C "windows-operator" -f "$env:USERPROFILE\.ssh\id_ed25519"
# Appuyer sur Entrée deux fois pour ne pas mettre de passphrase
```

**2 — Copier la clé publique sur PVE :**

```powershell
scp "$env:USERPROFILE\.ssh\id_ed25519.pub" pve:/tmp/operator.pub
```

</details>

<details>
<summary><b>B — Depuis Linux / macOS (bash)</b></summary>

**1 — Vérifier si une clé SSH existe déjà :**

```bash
ls ~/.ssh/id_ed25519.pub
```

Si « No such file », générer une clé :

```bash
ssh-keygen -t ed25519 -C "$USER-operator" -f ~/.ssh/id_ed25519
# Appuyer sur Entrée deux fois pour ne pas mettre de passphrase
```

**2 — Copier la clé publique sur PVE :**

```bash
scp ~/.ssh/id_ed25519.pub pve:/tmp/operator.pub
```

</details>

<details>
<summary><b>C — Directement sur le serveur Proxmox (SSH ou console)</b></summary>

Si tu lances le script **en étant déjà sur PVE** (connecté en `ssh root@pve` ou
via la console Proxmox), la clé root locale (`/root/.ssh/id_ed25519.pub`) est
**auto-détectée** — rien à copier, et `--extra-sshkey` est inutile.

Vérifier qu'une clé existe (sinon en générer une) :

```bash
ls /root/.ssh/id_ed25519.pub || ssh-keygen -t ed25519 -f /root/.ssh/id_ed25519
```

Dans ce cas, **retirer `--extra-sshkey /tmp/operator.pub`** des commandes de
création de VM ci-dessous.

</details>

Pour les cas A et B, vérifier que l'alias `pve` est configuré dans
`~/.ssh/config` (voir Prérequis en début de document).

### Créer la VM

Les commandes ci-dessous se lancent **depuis ton poste** (cas A/B) via l'alias `pve`.
Si tu es **déjà sur PVE** (cas C), retire le préfixe `ssh pve "…"` et exécute le
`curl … | bash …` directement, **sans** `--extra-sshkey`.

**Avec IP fixe** (recommandé — l'IP est connue d'avance) :

```bash
ssh pve "curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/dev/scripts/clone-vm-node.sh \
  | bash -s -- 110 --name portail-dev --template 9000 --storage vmpool \
    --ip 192.168.1.100/24 --gw 192.168.1.1 --extra-sshkey /tmp/operator.pub"
```

**Avec DHCP** (l'IP est détectée automatiquement par balayage ARP du subnet et affichée en fin de script) :

```bash
ssh pve "curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/dev/scripts/clone-vm-node.sh \
  | bash -s -- 110 --name portail-dev --template 9000 --storage vmpool \
    --extra-sshkey /tmp/operator.pub"
```

- `110` → VMID de la nouvelle VM (libre, ni VM ni LXC existant)
- `--template 9000` → VMID du template à cloner (voir `qm list`). Si omis, le script prend le premier template disponible.
- `--storage vmpool` → stockage Proxmox cible (ex. `vmpool`, `local-lvm`, `local-zfs`). Si omis, le clone va dans le même stockage que le template.
- `--extra-sshkey /tmp/operator.pub` → injecte aussi la clé du poste opérateur pour un accès SSH direct depuis ton poste. **À omettre dans le cas C** (déjà sur PVE).

Le script affiche le mot de passe console (accès Proxmox noVNC) en étape A.3, détecte
l'IP (A.8), attend que SSH réponde (A.9) puis finalise le hostname (A.11) avant de
rendre la main. Il rafraîchit aussi le `known_hosts` du host PVE pour cette IP.
**Noter l'IP affichée** — elle sera nécessaire à l'étape 3 (`REMOTE_HOST`).

> **known_hosts côté poste opérateur** — Le script ne rafraîchit le `known_hosts` que
> sur PVE. Si tu recrées une VM à une IP déjà connue de **ton poste**, le premier `ssh`
> depuis ton poste affichera `REMOTE HOST IDENTIFICATION HAS CHANGED`. Purger l'ancienne
> empreinte :
> - Windows / Linux / macOS : `ssh-keygen -R 192.168.1.100`

---

## Étape 2 — Cloner le dépôt et tester en local

Le dépôt `gaelgael5/devpod-ui` est **public** : le clone se fait en HTTPS, sans
authentification GitHub. Le déploiement s'exécute **en root** sur la VM.

Se connecter à la VM puis passer root :

```bash
ssh debian@192.168.1.100
sudo -i
```

### 2.1 — Cloner le dépôt

```bash
git clone https://github.com/gaelgael5/devpod-ui.git /opt/workspace-portal
cd /opt/workspace-portal
```

Si le clone réussit, le déploiement fera ensuite un simple `git pull`. Les scripts `.sh`
sont versionnés **avec le bit exécutable** (`100755`) : directement lançables sans `chmod`.

### 2.2 — Test du déploiement depuis la VM

Valider la chaîne complète directement sur la VM, sans passer par le poste opérateur.

**Premier déploiement** (initialise `/data` via `install.sh`, puis build + démarrage) —
à lancer en root, en fournissant le secret OIDC :

```bash
cd /opt/workspace-portal
OIDC_CLIENT_SECRET="<secret Keycloak>" \
PORTAL_BASE_DOMAIN=dev.yoops.org \
PORTAL_EXTERNAL_URL=https://dev.yoops.org \
PORTAL_OIDC_ISSUER=https://security.yoops.org/realms/yoops \
PORTAL_OIDC_CLIENT_ID=workspace-portal \
  ./scripts/deploy-portal.sh dev
```

**Redéploiements suivants** (pull + build + restart + smoke `/health`) — `/data` déjà
initialisé :

```bash
./scripts/dev-deploy.sh dev
```

> `deploy-portal.sh` initialise `/data` (CA, config, `.env`) ; `dev-deploy.sh` **suppose
> `/data` déjà présent** et se contente de rebuild/redémarrer. Lancer `dev-deploy.sh`
> avant le premier `deploy-portal.sh` démarrerait le portail sans configuration
> (`SESSION_SECRET_KEY not set`). Les deux exigent **root**.

Le secret OIDC vient de Keycloak (étape 4). Si Keycloak n'est pas encore configuré,
sauter ce test local et y revenir, ou poursuivre via le déploiement piloté (étapes 3 → 5).

---

## Étape 3 — Configurer le fichier `.env` local

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

## Étape 4 — Configurer Keycloak (si pas déjà fait)

Dans la console admin Keycloak (`https://security.yoops.org/admin`), realm `yoops` :

1. Créer les rôles realm `admin` et `dev`
2. Créer le client OIDC `workspace-portal` (confidentiel, Standard flow, redirect URI `https://dev.yoops.org/auth/callback`)
3. Copier le **Client secret** → c'est la valeur `OIDC_CLIENT_SECRET` du `.env`
4. Créer un utilisateur, lui assigner le rôle `admin`

Guide complet : [`documentations/fr/deploiement-portail.md`](fr/deploiement-portail.md) § Étape 6.

---

## Étape 5 — Premier déploiement (piloté depuis le poste opérateur)

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

## Étape 6 — Vérifier

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
