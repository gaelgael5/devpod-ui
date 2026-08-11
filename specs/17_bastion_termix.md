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
- **sshd bastion** (`deploy/bastion_sshd_config`, `portal/bastion/runtime.py`) : dans le
  conteneur portail (réutilise devpod + `/data` + mTLS). **Démarré/arrêté à chaud par
  l'app** selon `GlobalConfig.bastion.enabled` (écran admin) — pas d'`.env`, pas
  d'entrypoint. Host key persistée `/data/bastion/ssh_host_ed25519_key` (jamais
  régénérée). Durci : clé publique only, `PermitRootLogin forced-commands-only`, aucun
  forwarding.
- **wrapper** `deploy/ws-bastion <login> <ws_id>` : revalide, exporte le `DEVPOD_HOME`
  du user, `exec devpod ssh <ws_id>`.
- **authorized_keys** (`portal/bastion/authorized_keys.py`) : **1 ligne par workspace**
  `command="…/ws-bastion <login> <ws_id>",<restrictions> <pubkey>`. L'autorisation est
  **implicite** (une clé ne joint que SON workspace) → aucun resolver d'identité.
- **provisioning** (`portal/bastion/provision.py`, `termix_client.py`) : orchestration
  idempotente exposée par les **endpoints service** `POST /admin/service/bastion/
  provision|deprovision` (clé API admin, audités) — appelés par les **automates**.

## Flux — piloté par les automates (aucun câblage direct)
Le cycle de vie n'appelle plus le provisioning : les events `workspace.*` sont écrits
dans le **journal durable `app_event`** (dans la transaction de la mutation) et des
**automates à curseur** (épic synchro Termix) appellent les endpoints service :
- automate **provision** : `workspace.created` + `workspace.restarted` +
  `workspace.updated` (backfill/injection de test) → `POST …/bastion/provision`
  body `{"login": "{subject.login}", "ws_id": "{subject.ws_id}"}` — génère (1 fois)
  la clé ed25519, pose la pubkey dans `authorized_keys`, crée côté Termix un
  **credential** + un **host** (`host:port` config, `authType=key`) et (re)partage au
  **rôle** configuré. Si Termix a perdu le host (base réinitialisée), il est recréé.
- automate **deprovision** : `workspace.deleted` → `POST …/bastion/deprovision` —
  retire la ligne + supprime host/credential Termix (404 tolérés) + le secret d'état.
- **erreurs honnêtes** : 409 config incomplète, 502 échec Termix → le run de
  l'automate est `failed`, visible et **rejouable** depuis l'écran automates.
- **rattrapage / réconciliation** : plus de tâche au boot — `workspace.deleted` étant
  journalisé transactionnellement, le curseur le consomme même après un down du
  portail ; le peuplement initial passe par le bouton **backfill** de l'écran automates.

État par workspace = secret système `ws-bastion-<ws_id>` (JSON chiffré KEK :
`{login, key, host_id, cred_id}`) → idempotence + cleanup.

## Configuration — écran admin (pas d'`.env`)
Tout se règle dans l'IHM : **Admin → Bastion Termix** (`/admin/bastion`), persisté dans
`GlobalConfig.bastion` (DB). Champs : `enabled`, `api_url` (URL externe Termix), `host`
+ `port` (cible SSH que Termix vise = IP LAN portail:2222), `role` (rôle Termix cible du
partage), `apikey_secret` (slug du secret système portant l'apikey tmx_).
- **`enabled`** démarre/arrête le sshd bastion **à chaud** (l'app gère le process ;
  `PUT /admin/bastion-config` applique le toggle sans redéploiement).
- Le **provisioning** Termix ne s'active que si `api_url` + `host` + `role` sont posés.

Prérequis Termix : créer le rôle `devpod-users` (UI RBAC) + un **secret système**
(picker de secrets des automates) contenant l'apikey `tmx_` ; les users portent ce rôle
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
2. Créer le rôle Termix + le secret système apikey, puis **Admin → Bastion Termix** :
   activer + saisir URL/hôte/port/rôle → Enregistrer (le sshd démarre à chaud).
3. `docker logs deploy-portal-1 | grep bastion_sshd_started`.
4. **Automates** (éditeur pleine page ou primitive MCP `automation_rule_upsert`) :
   poser un secret système `portal-api-key` (= `PORTAL_API_KEY` du portail) puis
   créer les deux règles — l'auth des endpoints service est
   `Authorization: Bearer <PORTAL_API_KEY>` (`require_admin_or_api_key`), et
   l'anti-SSRF impose une **URL publique** (l'`external_url`, pas une IP LAN).
   Headers des deux règles :
   `[{"name": "Authorization", "secret_ref": "${system://portal-api-key}", "value_prefix": "Bearer "}]`.

   Règle `bastion-provision` — `workspace.created` + `workspace.restarted` +
   `workspace.updated` (ce dernier = backfill/injection de test) :
   ```json
   {"version": 1, "blocks": [{"label": "provision", "filter": null, "calls": [{
     "name": "provision",
     "url": "https://dev.yoops.org/admin/service/bastion/provision",
     "http_method": "POST",
     "body_template": "{\"login\": \"{subject.login}\", \"ws_id\": \"{subject.ws_id}\"}"
   }], "blocks": []}]}
   ```

   Règle `bastion-deprovision` — `workspace.deleted` :
   ```json
   {"version": 1, "blocks": [{"label": "deprovision", "filter": null, "calls": [{
     "name": "deprovision",
     "url": "https://dev.yoops.org/admin/service/bastion/deprovision",
     "http_method": "POST",
     "body_template": "{\"login\": \"{subject.login}\", \"ws_id\": \"{subject.ws_id}\"}"
   }], "blocks": []}]}
   ```
   ⚠️ `{subject.login}` (propriétaire), PAS `{event.actor}` : le backfill émet
   `actor=admin`. Puis **backfill** pour peupler les workspaces existants.
5. Créer/relancer un workspace → il apparaît dans Termix (partagé au rôle) et se connecte.

**Dépannage** (écran automates + logs structurés)
- Run `ok` + `bastion_provisioned` : OK (host_id renseigné).
- Run `failed` HTTP 409 : config bastion incomplète (Admin → Bastion Termix).
- Run `failed` HTTP 502 : voir le détail (réponse Termix dans l'aperçu du run). Si le
  **rôle** manque → le créer dans l'UI RBAC Termix, puis **rejouer** le run.
- « réponse sans id exploitable » → forme de réponse Termix différente : ajuster
  `_extract_id` (`termix_client.py`) aux champs réels (`id`/`hostId`/`credentialId`).

**Désactiver** : **Admin → Bastion Termix**, décocher + Enregistrer → le sshd s'arrête à
chaud et le provisioning devient no-op.

## Contrat API Termix
Contrat de référence : `ag-flow/ressources/contracts/termix/termix-hosts.openapi.json`
(hosts sous `/host/db/host`, credentials sous `/credentials`, partage
`POST /rbac/host/{id}/share`) — `termix_client.py` est aligné dessus. Les corps y
sont volontairement permissifs (Termix ne documente pas ses schémas) :
`_extract_id` parse `id`/`hostId`/`credentialId` de façon tolérante — les formes
de réponse réelles restent à confirmer au premier run (aperçu dans l'historique
de l'automate).
