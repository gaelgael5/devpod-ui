# Spec — Accès SSH aux machines de test depuis la WorkspaceCard

Date : 2026-06-25
Statut : validé (design), à planifier

## Contexte

Les machines de test (`HostConfig` avec `usage="tests"`) sont créées via
`POST /me/workspaces/{ws}/test-vm` et attachées à un workspace (table
`workspace_test_hosts`). À la création, une clé SSH est générée **dans le container**
du workspace ; sa pubkey est injectée dans `/root/.ssh/authorized_keys` de la VM. La VM
n'est donc joignable en `root` **que depuis le container**, par clé (aucun mot de passe
dans le flux). Le mot de passe root est conservé chiffré pour un secours hors-bande.

Aujourd'hui :
- l'alias écrit dans `~/.ssh/config` du container est le nom complet du host
  (`host-test-114-1`) ;
- aucun endpoint ne liste les machines de test d'un workspace ;
- aucun accès SSH utilisateur (la route `/admin/hosts/{name}/ssh` est admin-only et
  s'appuie sur un cert d'enrôlement que les VM de test n'ont pas) ;
- aucun flux de suppression de machine de test (`remove_test_host` n'est jamais appelé).

## Objectifs

1. L'alias dans `~/.ssh/config` du container est `testN` (`test1`, `test2`, …).
2. L'utilisateur ouvre une session SSH sur une machine de test depuis la `WorkspaceCard`,
   via un bouton/menu, en **rebond par le container** (réutilise la clé du container).
3. Suppression complète d'une machine de test (détruit la VM + nettoyage), avec libération
   de l'alias et nettoyage du `~/.ssh/config`.

Hors scope : modifier le flux de création (hormis l'attribution d'alias), persister le
mot de passe `debian`/`ci_password`, le terminal admin existant.

## Décisions actées

- **Connexion** : rebond via le container (`ssh root@<ip>` par clé du container), pas de
  mot de passe dans le flux. Login `root`.
- **Numérotation des alias** : plus petit numéro libre du workspace ; réutilisé après
  suppression. Les machines vivantes ne changent jamais d'alias. L'alias est **stocké**.
- **UI** : menu déroulant « SSH test » dans la `WorkspaceCard`, rendu uniquement s'il
  existe ≥ 1 machine. Chaque entrée ouvre le terminal ; une corbeille supprime (avec
  confirmation).
- **Suppression** : détruit réellement la VM (`destroy_script`) puis nettoie côté portail.

## Architecture

### 1. Modèle de données — alias persistant

- Migration Alembic : colonne `alias TEXT` (nullable) sur `workspace_test_hosts`.
- **Backfill** : pour chaque `(login, workspace_name)`, numéroter les machines existantes
  `test1…testN` dans un ordre stable (tri par `host_name`).
- Fonction pure `next_test_alias(used: Iterable[str]) -> str` : rend `test{k}` où `k` est
  le plus petit entier ≥ 1 dont `test{k}` n'est pas dans `used`.
- `assign_test_host(login, ws, host_name, alias, conn)` : stocke l'alias.
  Une lecture des alias déjà utilisés du workspace alimente `next_test_alias`.

Note : l'alias (plus petit libre) est indépendant du suffixe `<N+1>` du **nom** de la VM
(qui reste `len(test_hosts)+1`, et reste unique via le `vmid`). Les deux peuvent diverger
après une suppression — c'est attendu.

### 2. Alias `testN` dans `~/.ssh/config` (container)

`build_container_ssh_config_cmd` change de signature : `(alias, ip)` au lieu de
`(host_name, ip)`. Le bloc et ses marqueurs sont délimités **par alias** :

```
# >>> portal test-vm test1 >>>
Host test1
    HostName <ip>
    User root
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
# <<< portal test-vm test1 <<<
```

Idempotent par alias (un `sed -i` retire un éventuel bloc `test1` avant de réécrire) →
réutiliser `test1` écrase proprement l'ancien bloc.

Nouvelle fonction symétrique `build_container_ssh_config_remove_cmd(alias)` : un `sed -i`
qui supprime le bloc délimité de cet alias (idempotent, no-op si absent).

`_init_vm_ssh` reçoit l'alias et l'utilise pour le message et l'écriture du bloc.

### 3. Endpoint — lister les machines de test

`GET /me/workspaces/{name}/test-hosts` (`require_user`).
- Valide le nom de workspace (regex existante) et vérifie que le workspace appartient à
  l'utilisateur.
- Joint `workspace_test_hosts` (alias) et `cfg.hosts` (adresse, vmid).
- Retourne, trié par numéro d'alias :
  `[{ "alias": "test1", "name": "host-test-114-1", "ip": "192.168.10.160", "vmid": "114" }]`.
  L'`ip` est dérivée de `host.address` (`<user>@<ip>` → `<ip>`).

### 4. Accès SSH — rebond via le container

Extension du WebSocket existant `/me/workspaces/{name}/ssh` avec le paramètre
`?ssh_test=<host_name>` :
- Le backend vérifie que `host_name` ∈ test-hosts du workspace courant
  (`workspace_test_hosts` filtré sur `(login, workspace_name)`) **et** que le host a
  `usage="tests"`. Échec → fermeture WebSocket avec un code dédié (ex. 4004/4022, comme
  `ssh_proxy`).
- L'IP est résolue **côté serveur** depuis `cfg.hosts` ; le client ne fournit qu'un
  `host_name` validé regex. Aucune donnée de connexion ne vient du client.
- La commande lancée dans le PTY devient :
  `ssh -tt -o StrictHostKeyChecking=accept-new root@<ip>`
  (au lieu du shell/tmux). Tout le reste — allocation PTY, resize, ProxyCommand devpod,
  frontend xterm — est réutilisé tel quel.

Pas de tmux côté VM : la session est directe ; fermer la fenêtre termine la session.

### 5. Suppression d'une machine de test

`DELETE /me/workspaces/{ws}/test-vm/{host_name}` (`require_user`).
- Vérifie que `(login, ws, host_name)` ∈ `workspace_test_hosts` — sinon 404.
- Séquence résiliente (chaque étape best-effort + log, on poursuit sur échec partiel, à
  l'image de `delete_host`) :
  1. Lire l'alias (avant de retirer l'association).
  2. Détruire la VM : `_run_destroy_script(cfg, host_cfg)` (réutilisé) → script de
     destruction avec le `vmid` du host.
  3. Nettoyer `~/.ssh/config` : `run_ssh_capture(login, "{login}-{ws}",
     build_container_ssh_config_remove_cmd(alias))`.
  4. Supprimer le secret root : `delete_system_secret("host.<name>.root-password", conn)`.
  5. Retirer l'association : `remove_test_host(host_name, conn)` → libère l'alias.
  6. Retirer le `HostConfig` de `cfg.hosts` puis `save_global_db`.
- Réponse 204.

### 6. Frontend

- Hook `useTestHosts(wsName)` → `GET /me/workspaces/{wsName}/test-hosts`
  (queryKey `['me','workspaces',wsName,'test-hosts']`, enabled quand le workspace tourne).
- Hook `useDeleteTestHost(wsName)` → `DELETE …/test-vm/{host_name}`, invalide la query
  ci-dessus ; toast succès/erreur.
- Composant `TestHostsMenu` (calqué sur `InitializersMenu`) : bouton « SSH test » rendu
  seulement si `testHosts.length > 0`. Chaque entrée affiche `alias — ip` :
  - clic → ouvre `WorkspaceSshTerminalWindow` avec `testHost={name}` ;
  - icône corbeille → confirmation → `useDeleteTestHost`.
- `WorkspaceSshTerminalWindow` : nouveau prop optionnel `testHost?`. Quand présent,
  l'URL devient `…/ssh?ssh_test=<testHost>` (et le titre/entête reflète l'alias/host).
- `WorkspaceCard` : monte `TestHostsMenu` près du bouton « Test VM », gère l'état
  d'ouverture du terminal pour une machine de test sélectionnée.

## Flux de données — bouton SSH

```
WorkspaceCard (running) → useTestHosts(ws) → GET /me/workspaces/{ws}/test-hosts
   → [{alias, name, ip, vmid}]
Menu « SSH test » (si ≥1) → clic test1 → WorkspaceSshTerminalWindow testHost=host-test-114-1
   → WS /me/workspaces/{ws}/ssh?ssh_test=host-test-114-1
   → backend: host ∈ test-hosts(login,ws) & usage=tests ? sinon close 4004/4022
   → résout ip depuis cfg.hosts → PTY: ssh -tt root@<ip> → VM
```

## Gestion des erreurs

- Host hors workspace (rebond ou DELETE) → rejet (close WebSocket / 404). Aucune IP
  fournie par le client.
- VM injoignable au rebond → l'erreur `ssh` s'affiche dans le terminal (comportement
  terminal standard).
- Suppression : échec d'une étape (ex. destroy_script, nettoyage ssh) loggé, le flux
  continue ; l'objectif est que l'état portail soit toujours nettoyé.
- Aucune machine de test → menu masqué (pas d'appel ni d'état d'erreur visible).

## Sécurité

- Le client ne fournit jamais d'IP ni de cible de connexion, seulement un identifiant
  (`host_name`/nom de workspace) validé regex ; le backend résout l'IP en base.
- Contrôle d'ownership systématique : `(login, workspace_name, host_name)` dans
  `workspace_test_hosts` pour le rebond comme pour la suppression.
- `StrictHostKeyChecking=accept-new` (cohérent avec l'existant).
- Le mot de passe root reste chiffré et n'entre jamais dans le flux SSH ; il est supprimé
  à la destruction.

## Tests (TDD)

Backend (parties pures + routes mockées) :
- `next_test_alias` : plus petit numéro libre, réutilisation après trou.
- `build_container_ssh_config_cmd(alias, ip)` : bloc/alias, idempotence par alias,
  quoting des valeurs.
- `build_container_ssh_config_remove_cmd(alias)` : retire le bon bloc, no-op si absent.
- `GET /test-hosts` : ownership (workspace d'un autre user → 404), tri par alias, mapping
  ip.
- Rebond `?ssh_test=` : host hors workspace → rejet ; host valide → commande
  `ssh … root@<ip>` construite.
- `DELETE …/test-vm/{host}` : ownership → 404 ; ordre des étapes ; alias libéré
  (réattribué à la création suivante).

Frontend (Vitest + RTL) :
- `TestHostsMenu` : masqué si aucune machine, listé sinon ; clic ouvre le terminal avec
  l'URL `?ssh_test=…`.
- Suppression : confirmation puis invalidation de la query.
- `WorkspaceSshTerminalWindow` : `testHost` → URL `?ssh_test=`.

## Limitations assumées

- Machines créées **avant** cette livraison : leur bloc `~/.ssh/config` garde l'ancien
  alias (`host-test-…`). Le bouton SSH fonctionne quand même (connexion par IP) ; le
  backfill leur donne un alias `testN` en base pour l'affichage et le menu.

## Addendum — re-résolution d'IP (machines DHCP)

Les VM de test sont en DHCP : l'IP figée à la création (`host.address`) peut devenir
périmée. Le nom DNS (`HostConfig.name` = hostname cloud-init) est stable et enregistré
dans le DNS local (DDNS du DHCP). On ajoute une re-résolution **manuelle** par bouton.

### Décisions
- Résolution **côté portail** (`getaddrinfo`) — confirmé que le resolver du portail voit
  le DNS local.
- Domaine local en **config globale** : `ServerConfig.local_domain` (ex. `home.lan`),
  éditable depuis l'admin. Vide → on résout le nom seul.
- Bouton manuel pour cette itération ; la re-résolution **auto sur échec** du rebond
  (PTY interactif) est hors scope (le portail n'intercepte pas proprement l'échec
  à mi-session).

### Backend
- `ServerConfig.local_domain: str = ""` : modèle, colonne `global_config.local_domain`,
  migration, mapping load/write, `GET/PUT /admin/config`.
- Fonctions pures : `build_resolve_fqdn(name, local_domain)` (`<name>.<domain>` ou
  `<name>`), `replace_host_ip(old_address, new_ip)` (préserve `<user>@`).
- `POST /me/workspaces/{ws}/test-vm/{host_name}/resolve-ip` (require_user) : ownership →
  `fqdn` → `loop.getaddrinfo(fqdn, None, AF_INET)` → 1ʳᵉ IPv4. Échec → 502
  (`Unresolvable: <fqdn>`). Met à jour `host.address`, `save_global_db`, réécrit le bloc
  `~/.ssh/config` du container (best-effort). Retourne `{ "ip", "fqdn" }`.

### Frontend
- `useResolveTestHostIp(wsName)` → POST, invalide `test-hosts`, toast.
- `TestHostsMenu` : action « Résoudre l'IP » par machine.
- Admin config : champ « Domaine local (DNS) ».

## Fichiers concernés (indicatif)

- Backend : `db/test_hosts.py`, nouvelle migration Alembic, `db/tables.py`,
  `devpod/vm_init.py`, `routes/test_vm.py`, `routes/workspace_ssh.py`.
- Frontend : `features/workspaces/useTestVm.ts` (ou nouveau hook), `WorkspaceCard.tsx`,
  `WorkspaceSshTerminalWindow.tsx`, nouveau `TestHostsMenu.tsx`, `i18n/{en,fr}.json`.
