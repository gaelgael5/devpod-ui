# 17 — Bastion SSH workspace → Termix

Donne à un client SSH externe (Termix) l'accès shell à un workspace devpod, **sans
exposer le workspace** et sans toucher aux nœuds. Un **bastion** (sshd dans l'image
portail) relaie chaque session vers `devpod ssh --stdio <ws_id>`.

## Pourquoi un bastion
Le SSH d'un workspace n'est joignable **que** par `devpod ssh --stdio` (tunnel CLI
DevPod + mTLS nœuds) : aucun `host:port` SSH réel, le pare-feu des nœuds n'ouvre que
2376, `host_port` = openvscode HTTP derrière Caddy. Termix, client SSH brut, n'a rien
où atterrir. Le bastion est la seule « porte » joignable ; il escorte la session vers
le bon workspace.

```
Termix ──SSH(clé dédiée)──▶ Bastion sshd (image portail, :2222)
                              │ ForceCommand (authorized_keys)
                              ▼
                            ws-bastion <login> <ws_id>  →  devpod ssh --stdio <ws_id>
                              ▼
                            sshd du conteneur workspace (agent devpod)
```

## Composants
- **sshd bastion** (`deploy/bastion_sshd_config`, `deploy/portal-entrypoint.sh`) : dans
  le conteneur portail (réutilise devpod + `/data` + mTLS). **Opt-in** via
  `PORTAL_BASTION_ENABLED=1`. Host key persistée `/data/bastion/ssh_host_ed25519_key`
  (jamais régénérée). Durci : clé publique only, `PermitRootLogin forced-commands-only`,
  aucun forwarding.
- **wrapper** `deploy/ws-bastion <login> <ws_id>` : revalide, exporte le `DEVPOD_HOME`
  du user, `exec devpod ssh <ws_id>`.
- **authorized_keys** (`portal/bastion/authorized_keys.py`) : **1 ligne par workspace**
  `command="…/ws-bastion <login> <ws_id>",<restrictions> <pubkey>`. L'autorisation est
  **implicite** (une clé ne joint que SON workspace) → aucun resolver d'identité.
- **provisioning** (`portal/bastion/provision.py`, `termix_client.py`) : au cycle de vie
  du workspace, déclare l'accès côté Termix.

## Flux
- **workspace.created / restarted** → génère (1 fois) une clé ed25519, pose la pubkey
  dans `authorized_keys`, crée côté Termix un **credential** (clé privée) + un **host**
  (`TERMIX_BASTION_HOST:PORT`, `authType=key`, `credentialId`) partagé au **rôle**
  `TERMIX_ROLE`. Idempotent (recreate = réutilise la clé).
- **workspace.deleted** → retire la ligne + supprime host/credential Termix + le secret.
- **best-effort** : toute erreur (Termix down, config incomplète) est loguée, **jamais**
  propagée au cycle de vie du workspace.
- **réconciliation horaire** : `reconcile_orphans()` supprime le provisioning des
  workspaces disparus (source de vérité = `workspace_status`).

État par workspace = secret système `ws-bastion-<ws_id>` (JSON chiffré KEK :
`{login, key, host_id, cred_id}`) → idempotence + cleanup.

## Configuration (`/data/.env`)
```ini
PORTAL_BASTION_ENABLED=1              # active le sshd bastion
TERMIX_API_URL=https://termix.yoops.org   # URL externe (appels API de provisioning)
TERMIX_BASTION_HOST=192.168.10.164   # IP/host que Termix vise en SSH (IP LAN portail)
TERMIX_BASTION_PORT=2222
TERMIX_ROLE=devpod-users             # rôle Termix cible du partage (créé dans l'UI Termix)
TERMIX_APIKEY_SECRET=termix-apikey   # slug du SECRET SYSTÈME portant l'apikey tmx_ admin
```
Prérequis Termix : créer le rôle `devpod-users` (UI RBAC) ; les users portent ce rôle
(assignation manuelle ou `OIDC_ROLE_MAP` groupe Keycloak → rôle) pour voir leurs hosts.

## Modèle de sécurité
- **Réseau** : bastion sur `:2222` ; joignable Termix (LAN) + distant via Tailscale
  (subnet router OPNsense). Pas de Cloudflare (inadapté au TCP/SSH).
- **Auth** : clé publique uniquement, **une clé par workspace** ; la clé ne peut lancer
  QUE `ws-bastion <login> <ws_id>` (ForceCommand). Root autorisé en forced-commands-only.
- **Anti-injection** : `login`/`ws_id` strictement validés (regex) avant d'entrer dans la
  commande forcée. authorized_keys en 0600, `/data/bastion` en 0700.
- **Secrets** : clé privée dans un secret système (KEK) ; apikey Termix (admin, tous
  droits) en secret système, jamais dans le repo/logs.
- **Frontière par-utilisateur** : posée par la possession de la clé (par-workspace) + le
  **RBAC Termix** (qui voit quel host). Un Termix compromis = accès aux ws provisionnés
  (accepté ; l'alternative « authz réseau par user » n'a pas été retenue).

## Runbook
**Activer / valider (test1)**
1. `dev-deploy.sh` (rebuild image).
2. Poser la config `/data/.env`, créer le rôle Termix, `docker restart deploy-portal-1`.
3. `docker logs deploy-portal-1 | grep bastion` → « bastion sshd démarré sur :2222 ».
4. Créer/relancer un workspace → il apparaît dans Termix (partagé au rôle) et se connecte.

**Dépannage** (logs structurés)
- `bastion_provisioned` : OK (host_id renseigné).
- `bastion_provision_failed` : voir l'exception. Si le **partage** manque (host créé, pas
  de rôle) → vérifier `TERMIX_ROLE` existe côté Termix.
- Si `host_id`/`cred_id` restent nuls → forme de réponse `id` de Termix différente :
  ajuster `_extract_id` (`termix_client.py`) aux champs réels (`id`/`hostId`/`credentialId`).
- `bastion_orphans_reconciled` : nettoyage d'orphelins effectué.

**Désactiver** : retirer `PORTAL_BASTION_ENABLED` de `/data/.env` + restart. Le sshd ne
démarre plus ; le provisioning devient no-op (config lue mais bastion inerte).

## Point à confirmer au runtime
Les formes de réponse Termix (`POST /credentials`, `POST /host`) n'ont pas été testées
contre le Termix réel : `_extract_id` parse `id`/`hostId`/`credentialId` de façon
tolérante — à ajuster au premier test si besoin.
