# 18 — Termix multi-node : SSH par workspace publié sur le node (Modèle B)

> **Statut : spec en cours de cadrage (architecte).** Rien n'est implémenté.
> Remplace l'approche « bastion unique à côté du portail » de la spec 17 par un
> accès SSH **distribué sur les nodes**, avec multi-tenance Termix par utilisateur.

## Objectif

Intégrer automatiquement chaque workspace à Termix (client SSH self-hosted) de
façon **qui passe à l'échelle** : la charge SSH se répartit sur les nodes (là où
tournent déjà le daemon Docker et Alloy), sans goulot sur la machine du portail,
et sans IP de bastion figée dans la config.

## Pourquoi on change (constats)

1. **Un workspace n'a pas d'IP propre** : c'est un conteneur Docker sur un node.
2. **Le bastion unique (spec 17) est un goulot** : tout le SSH transiterait par le
   portail, qui doit en plus parler mTLS à chaque node. (Ce n'était PAS un problème
   de ports : le bastion actuel multiplexe par **clé** sur un seul port 2222.)
3. **L'accès openvscode actuel est portail-centrique** : `host_port` n'est pas
   publié sur le node — c'est un `devpod port-forward` qui tourne **sur le portail**
   (`portail:host_port → conteneur`), et `node_ip` vaut le portail
   (`caddy.portal_host`). La publication d'un port **sur l'IP du node** est donc
   une brique NEUVE à construire.

## Modèle retenu — B : SSH du workspace publié sur un port du node

Chaque workspace expose un **sshd** ; son port est **publié sur l'IP du node**
qui l'héberge. Termix enregistre un host `node_ip:port_alloué`, `authType=key`,
avec une clé dédiée par workspace. Pas de relais par le portail.

```
Termix (instance de l'utilisateur) ──SSH(clé du workspace)──▶ node_ip:port_ws
                                                                 │ (Docker publish)
                                                                 ▼
                                                        sshd du conteneur workspace
```

- **IP = celle du node** (`HostConfig.address`), résolue au provisioning depuis le
  node du workspace. Plus d'IP de bastion dans la config.
- **Port par workspace** : réutilise l'allocateur existant (`exposure/ports.py`,
  `PortRegistry`, tracé dans `workspace_status`) — un **second** port dédié SSH,
  **publié côté node** (nouveau, cf. §Brique neuve).
- **Répartition de charge automatique** : ajouter un node ajoute de la capacité,
  sans recâblage.

### Décisions verrouillées

- **Publication = publish Docker direct sur l'IP du node** (pas de relais/agent
  maison sur le node). DNAT noyau, rien dans le chemin de données, se distribue
  par construction, s'appuie sur une primitive stable → simplicité + pérennité de
  la charge. Pas de bastion côté node : le sshd vit **dans le conteneur**.
- **Accès SSH = feature injectée par le portail** (comme les fichiers d'agent),
  pas laissée à la devcontainer du user. Elle installe `openssh-server`, pose la
  clé publique du workspace dans le `authorized_keys` de **l'utilisateur du
  workspace**, et configure le sshd.
- **tmux cesse d'être installé par recette** : il devient partie intégrante de
  cette feature injectée (toujours présent, uniforme sur tous les workspaces —
  même logique que Termix). Fin du tmux opt-in par recette.
- **Greffe tmux (contrainte structurante)** : le sshd **log en tant qu'utilisateur
  du workspace** (celui qui possède le socket `/tmp/tmux-<uid>/default`, pas root)
  et son **ForceCommand attache le socket tmux partagé** (`exec tmux new-session
  -A -s <nom>`, la logique de `remote_tmux_command`). Résultat : les sessions du
  portail et l'accès Termix sont **le même serveur tmux** — cohérence
  bidirectionnelle sans synchro, le code sessions existant (sonde `list-sessions`
  sur ce socket) ne bouge pas. Les deux plans de contrôle cohabitent : le portail
  garde `devpod ssh --stdio` (ws_exec/MCP), Termix entre par le sshd direct, tous
  deux sur le même socket.

### Système d'installation extensible (décision verrouillée)

On ne code **pas** une « feature SSH » en dur : on construit un **registre de
composants système de workspace**, injectés par le portail au `up`, dont
`ssh-access` (sshd + tmux) est le **premier**. Ajouter ou changer un élément
demain (agent de monitoring, autre multiplexeur, outil de sécurité…) = enregistrer
un composant, sans toucher au cœur.

Contrat d'un composant (déclaratif) :
- `name` : id stable ; `enabled` ; ordre (tri topologique, comme le registre
  Features de `recipes/`).
- **paquets** à installer (apt / image de base) ;
- **fichiers** à poser (contenu, chemin, perms, owner) ;
- **config** à appliquer (ex. `sshd_config`, ForceCommand d'attache tmux) ;
- **ports** à publier sur l'IP du node (ex. sshd → port alloué) ;
- **secrets / clés** requis (ex. clé du workspace) ;
- **hooks de cycle de vie** : provision / deprovision (ex. host Termix au
  `created`/`deleted`).

Portée future possible : activer/désactiver un composant par user ou par host
(s'appuie sur le volet multi-tenance). `ssh-access` reste toujours actif.

### Brique neuve à construire (le vrai travail de T1)

1. **Registre de composants système** (contrat ci-dessus, tri topologique) + le
   composant `ssh-access` : `openssh-server` + tmux (installés par le composant,
   **pas** l'image de base), `authorized_keys` de l'utilisateur du workspace, sshd
   durci + ForceCommand d'attache tmux, **lancé via `postStartCommand` (`sshd -D`)**
   — rejoué à chaque démarrage.
2. **Publication du port SSH sur l'IP du node** — **résolu (spike, cf. §Spike)** :
   ajouter `--publish 0.0.0.0:<ssh_port>:22` au **`runArgs`** du devcontainer, au
   point d'injection existant (`devpod/service.py::_write_devcontainer`, qui écrit
   déjà `runArgs` pour `--memory`). Publié sur l'interface du node par son daemon
   Docker — **pas** un `port-forward` portail.
3. **Pare-feu du node** ouvert sur la plage de ports SSH allouée.
4. **Retrait de la recette tmux** (migration : ne plus l'installer par recette, le
   composant `ssh-access` en devient la source unique).

Point à vérifier avant de coder (spike, « --help first ») : que **DevPod sache
publier un port hôte** du conteneur au `up` (via `appPort` / `runArgs -p`) et le
binder sur l'interface du node. Si non → passer par le runtime de lancement.

## Volet multi-tenance

1. **Registre d'instances Termix** : `{name, url, apikey_secret, is_default}`
   (config admin) — plusieurs Termix possibles. L'instance **locale au portail**
   (`termix.yoops.org`) y figure.
2. **User → hosts autorisés** (relation N-N) : les nodes sur lesquels un user peut
   créer des workspaces. **Cette liste alimente le sélecteur de host à la création**
   (aujourd'hui les hosts sont globaux, sans portée par user : brique manquante).
3. **User → instance Termix** : dans quel Termix les hosts de ses workspaces sont
   provisionnés.
4. **Page admin « Utilisateurs »** : lister les users ; cocher leurs hosts
   autorisés ; choisir leur instance Termix.

### Décisions multi-tenance verrouillées

- **M1 — modèle** : N instances (par tenant/équipe), user rattaché à **une** ;
  isolation **intra-instance par RBAC Termix** (host partagé au seul compte/rôle du
  user). Pas d'instance dédiée par user.
- **M3 — portée user→hosts (migration)** : à l'introduction, **tous les hosts
  existants accordés à tous les users existants** (zéro régression) ; l'admin
  resserre ensuite. Nouveaux users : aucun host tant que non accordé.
- **M4 — instance par défaut** : flag `is_default` sur le registre. **Les admins
  sont automatiquement rattachés à l'instance locale au portail** ; les autres
  héritent de l'instance `is_default` (ou assignation explicite). User sans
  instance → workspace OK, pas de host Termix (best-effort).
- **Provisioning** : portail → Termix par **apikey admin de l'instance** ; host
  **pré-partagé par `sub`** (ancre OIDC) au compte du user, au provisioning
  (indépendant d'un login préalable).

### M2 — auth user → Termix — VERROUILLÉ : OIDC natif, un client par instance

Chaque instance Termix fait son **OIDC contre Keycloak** avec son **propre
`client_id`** (déclaré dans le realm à la création de l'instance ; le Termix est
configuré avec, comme le Termix de dev l'est déjà). Le compte Termix du user =
son identité OIDC (`sub`). Le forward-auth est écarté (économe mais non confirmé —
on ne prend pas le risque). Le provisioning portail → Termix reste sur l'**apikey
admin** de l'instance ; création d'une instance = déclarer un client Keycloak +
configurer le Termix + enregistrer `{url, apikey_secret}` au registre.

## Modèle de données (esquisse)

- `termix_instance(id, name, url, apikey_secret, created_at)`.
- `user_host_access(login, host_name)` (N-N) — portée des hosts par user.
- `user_termix(login, termix_instance_id)` — instance cible par user.
- `workspace_status` : ajouter `ssh_port` (port SSH alloué/publié) à côté de
  `host_port`.
- État par workspace (secret système `ws-bastion-<ws_id>` existant) : + `node_ip`,
  `ssh_port`, `termix_host_id`, `termix_instance_id`.

## Flux

- **workspace.created / restarted** → alloue/publie le port SSH sur le node,
  résout `node_ip`, (re)crée le host Termix `node_ip:ssh_port` (clé du workspace)
  dans **l'instance Termix du user**, partagé/visible pour lui.
- **workspace.stopped / deleted** → supprime le host Termix + relâche le port +
  ferme la publication. (stopped optionnel : restarted recrée.)
- Toujours via les endpoints service `POST /admin/service/bastion/provision|
  deprovision` (déjà livrés) — c'est leur **résolution interne** (node+port+instance)
  qui change, pas le contrat d'appel des automates.

## Sécurité

- Une **clé par workspace** ; le port n'accepte que cette clé, login conteneur
  restreint (pas de root, pas de forwarding sauf besoin).
- Publier N ports SSH par node élargit la surface : plage dédiée, pare-feu node
  restreint aux instances Termix autorisées (par IP source si possible).
- apikey Termix par instance en **secret système**, jamais dans le repo/logs.
- Isolation par user côté Termix : un user ne voit que ses hosts (instance dédiée
  ou scope/rôle).

## Tranches (DoD par tranche : lint+mypy+tests, pas de secret en clair)

- **T1 — SSH publié par node** : composant `ssh-access` injecté (sshd + tmux, login
  utilisateur du workspace, ForceCommand attache le socket tmux partagé,
  `postStartCommand sshd -D`), clé générée au `up` (pubkey injecté), retrait de la
  recette tmux, second `PortRegistry` (plage 50000-59999, `ssh_port`) + `runArgs
  --publish` sur l'IP du node, pare-feu du node restreint aux IP Termix
  (`install-node.sh`) ; provisioning qui résout `node_ip:ssh_port` et l'enregistre
  dans Termix.
- **T2 — Registre d'instances Termix** (CRUD admin + secret apikey par instance).
- **T3 — Portée user→hosts** + filtrage du sélecteur de host à la création.
- **T4 — User→Termix** + page admin Utilisateurs (hosts autorisés + Termix).
- **T5 — Automates** de provision/deprovision branchés sur la résolution node+port+
  instance ; validation runtime sur test2 puis prod.

## Spike DevPod — RÉSOLU (2026-08-12, test2)

Question : DevPod sait-il publier un port hôte du conteneur au `up`, bindé sur
l'interface du node ? **Oui.** Test isolé (devpod v0.6.15, `DEVPOD_HOME` scratch,
provider docker local de test2, devcontainer minimal `runArgs:["--publish",
"0.0.0.0:38022:8000"]`) → conteneur créé avec
`PortBindings={"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"38022"}]}` et
`0.0.0.0:38022` en LISTEN (docker-proxy). Environnement nettoyé.

**Conclusion T1** : mécanisme = `runArgs --publish 0.0.0.0:<ssh_port>:22`, injecté
là où le portail écrit déjà `runArgs` (`--memory`). Pas de flag `devpod up`
dédié ; `runArgs` est le passthrough `docker run` (conforme spec devcontainer).
Binding `0.0.0.0` + pare-feu du node restreint aux IP Termix (ou binding sur l'IP
LAN du node si on veut être strict).

## Mécanique T1 — décisions verrouillées

- **sshd = composant injecté** (aucune dépendance image de base), lancé via
  `postStartCommand` (`sshd -D`), rejoué à chaque démarrage.
- **Séquencement de la clé** : générée par le portail au `up` **avant le build** ;
  pubkey injecté par le composant dans `authorized_keys` de l'utilisateur du
  workspace ; clé privée → credential Termix en provision post-up. État dans le
  secret système `ws-bastion-<ws_id>`.
- **Ports SSH** : **plage dédiée 50000-59999** (distincte des 40000-49999
  d'openvscode), **second `PortRegistry`**, port **réutilisé au restart**, tracé
  dans `workspace_status.ssh_port`.
- **Pare-feu du node** : plage SSH **restreinte aux IP des instances Termix
  enregistrées** (resync `install-node.sh` quand le registre change) ; sshd durci
  (clé only, ForceCommand tmux, pas de forwarding) en défense en profondeur.

## Points ouverts

Aucun point de cadrage bloquant restant. Cadrage T1–T4 complet. Reste **T5** (les
automates branchés sur la résolution node+port+instance — déjà largement défini).
Détails d'implémentation (schéma exact des tables, forme du contrat de composant)
à préciser au démarrage de chaque tranche via un plan TDD.

## Décisions verrouillées (récapitulatif)

- **Publication du port = `runArgs --publish` du devcontainer** (spike validé sur
  test2, devpod v0.6.15) — point d'injection `_write_devcontainer`.
- **Modèle B** : SSH du workspace publié sur un port du node ; host Termix
  = `node_ip:ssh_port`, clé par workspace.
- **Publish Docker direct** sur l'IP du node (pas de relais maison). Pas de bastion
  côté node : sshd **dans le conteneur**.
- **Accès SSH = feature injectée** par le portail (openssh-server + tmux), login en
  tant qu'utilisateur du workspace, ForceCommand d'attache au **socket tmux
  partagé** → sessions portail et Termix = même serveur tmux.
- **tmux migre de la recette vers la feature injectée** (toujours présent, uniforme).
- **Système d'installation extensible** : registre de **composants système de
  workspace** (contrat déclaratif, tri topologique), `ssh-access` (sshd+tmux) =
  premier composant ; ajouter/changer un élément = enregistrer un composant, sans
  toucher au cœur.
