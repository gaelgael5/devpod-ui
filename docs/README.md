# agflow.docker

Plateforme multi-agent orchestrant des agents IA pour le cycle de vie logiciel.
Stack : FastAPI + PostgreSQL (pgvector) + Redis + Docker Compose.

Voir [docs/architecture.md](docs/architecture.md) pour la stack complète et
[CLAUDE.md](CLAUDE.md) pour les conventions du projet.

## License

**agflow.docker** is distributed under the [PolyForm Noncommercial License 1.0.0](./LICENSE).

You may freely use, modify, and share the source code for **non-commercial purposes** (personal use, research, education, evaluation).

**Commercial use** (SaaS, hosted services, resale, integration in paid products, production use by for-profit entities) requires a separate
commercial license.

See [COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md) for details and to request a commercial license.

Copyright (c) 2026 gaelgael5 &lt;llm.beard.family@gmail.com&gt;. All rights
reserved.

---

## 1 - Pour tester en mode dev

L'installation se fait en trois étapes exécutées sur l'**hôte Proxmox**, puis dans le **container LXC**.

### 1. Créer le container LXC

Sur l'hôte Proxmox, créer et configurer le LXC (Docker-ready, SSH, réseau DHCP).

> `bash <(wget -qO- URL)` est requis ici (pas `bash -c "$(wget ...)"`) car le script reçoit des arguments positionnels (`$1` = CTID, `$2` = nom).

```bash
 bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 203 agflow-docker --docker
```

Remplacer `203` par le CTID souhaité et `agflow-docker` par le nom du container.  
Le flag `--docker` installe Docker automatiquement dans le LXC.


### 🔐 2. Configurer l’accès SSH à GitHub

#### 2.1 Générer une clé SSH

Sur la machine cible :

```bash
pct enter 203
```

```bash
ssh-keygen -t ed25519 -C "deploy-roles"
~/.ssh/id_ed25519
```

Passphrase (Appuyer sur Entrée 3x pour accepter le chemin par défaut) :
- laisser vide pour un serveur (déploiement automatique)
- ou en définir une pour plus de sécurité

Démarrer l’agent SSH et charger la clé
```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

cat ~/.ssh/id_ed25519.pub

```

#### 2.2 paramétrer github

1 - Ajouter la clé dans GitHub
2 - Aller sur GitHub
3 - Settings
4 - (SSH and GPG keys)[https://github.com/settings/keys]
5 - New SSH key
6 - Name : deploy-roles
7 - Coller la clé publique
8 - Cliquer sur Add SSH key


Tester la connexion
```bash
ssh -T git@github.com
```

Cloner le repository
```bash
git clone --branch feat/mom-bus git@github.com:gaelgael5/agflow.docker.git
cd agflow.docker
```



## 3. Paramétrage

Créer et configurer le fichier `.env`
```bash
cp .env.example .env
nano .env
```

Renseigner au minimum ces valeurs :

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | `postgresql://<agflow_user>:<your_password>@postgres:5432/<agflow_db>` |
| `JWT_SECRET` | `openssl rand -hex 32` |
| `ADMIN_EMAIL` | ex: `admin@agflow.local` |
| `ADMIN_PASSWORD_HASH` | `python3 -c "import bcrypt; print(bcrypt.hashpw(b'TONPASSWORD', bcrypt.gensalt()).decode())"` |
| `HARPOCRATE_KEY` | token `hrpv_1_*` fourni par le coffre |
| `HARPOCRATE_URL` | `https://vault.yoops.org` |


## 4. Lancement

Lancer la stack
```bash
bash deploy.sh
```

Affiche les logs
```bash
docker compose -f docker-compose.dev.yml logs --tail=50 backend
docker compose -f docker-compose-dev.yml logs --tail=50 frontend
```

---

## Développement local

```bash
# Dépendances infra (Postgres) sur le LXC
ssh pve "pct exec 202 -- bash -c 'cd /opt/harpocrate && docker compose up -d postgres'"

# Backend (hot-reload)
cd backend && uv run uvicorn app.main:app --reload

# Frontend (proxy Vite -> :8000)
cd frontend && npm run dev
```

```bash

# voir les logs du frontend
docker compose -f /opt/agflow.docker/docker-compose.dev.yml logs -f frontend
# voir les logs du backend
docker compose -f /opt/agflow.docker/docker-compose.dev.yml logs -f backend

```

---

## Configurer le client Keycloak

### 1. Accéder à la console Keycloak

Va sur `https://security.yoops.org/admin/` → realm **yoops** → **Clients** → **Create client**

```env
HARPOCRATE_KEYCLOAK_URL=https://security.yoops.org
HARPOCRATE_KEYCLOAK_REALM=yoops
HARPOCRATE_KEYCLOAK_CLIENT_ID=harpocrate-vault
HARPOCRATE_KEYCLOAK_CLIENT_SECRET=
HARPOCRATE_PUBLIC_URL=https://vault.yoops.org
```

### 2. Onglet "General Settings"

| Champ | Valeur |
|---|---|
| Client type | `OpenID Connect` |
| Client ID | `agflow-docker` |
| Name | `agflow-docker` (optionnel) |

→ **Next**

### 3. Onglet "Capability config"

| Champ | Valeur |
|---|---|
| Client authentication | **ON** (indispensable pour avoir un secret) |
| Authorization | OFF |
| Standard flow | **ON** |
| Direct access grants | OFF |

→ **Next**

### 4. Onglet "Login settings"

| Champ | Valeur |
|---|---|
| Root URL | `http://agflow-docker.home.lan` |
| Home URL | `http://agflow-docker.home.lan` |
| Valid redirect URIs | `http://agflow-docker.home.lan/*` |
| Valid post logout redirect URIs | `http://agflow-docker.home.lan/*` |
| Web origins | `http://agflow-docker.home.lan` |

→ **Save**

### 5. Récupérer le secret

Onglet **Credentials** → copie le **Client secret** → mets-le dans `.env` :

```env
KEYCLOAK_CLIENT_SECRET=<le secret généré par Keycloak>
```

### 6. Rôles (optionnel)

Onglet **Roles** → crée les rôles : `admin`, `operator`, `viewer`

Le backend lit `resource_access.agflow-docker.roles` dans le token JWT pour attribuer le rôle agflow.

### 7. Tester

```bash
docker compose -f docker-compose.dev.yml restart backend
curl http://agflow-docker.home.lan/api/admin/auth/mode
# → {"mode":"keycloak"}
```


#### Étape 3 — Initialiser la stack
```bash
pct exec 202 -- bash -c "$(wget -qLO - https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/setup.sh)"
```