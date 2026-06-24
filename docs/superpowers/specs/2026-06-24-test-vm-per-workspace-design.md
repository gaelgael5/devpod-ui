# VM de test éphémère attachée à un workspace — design

**Date** : 2026-06-24
**Statut** : vision validée ; lot A implémenté ; lots B→H à venir

## Vision

Permettre à un utilisateur de provisionner, depuis son workspace, une **VM de test
éphémère** : il appuie sur « Add VM for Test » sur la `WorkspaceCard`, choisit un
hyperviseur, renseigne le minimum (l'identifiant unique de la machine), le script de
création se déroule, et la VM (host `usage=tests`) est **attachée au workspace**.
Cette VM est joignable en SSH (root) depuis le container du workspace, et **détruite
avec le workspace**.

## Décomposition en lots

| # | Brique | Dépend de | Statut |
|---|--------|-----------|--------|
| **A** | Marquer le `vmid` dans la spec JSON (`identifier: true`) + helper backend | — | **fait** |
| **B** | Paramétrage host de test (admin) : valeurs par défaut des `args` **par type d'hyperviseur**, sauf l'identifiant | A | **fait** |
| **C+D** | « Add VM for Test » sur `WorkspaceCard` : choix hyperviseur → vmid → `execute` → host `usage=tests` **enregistré et associé au workspace** (table) | A, B | **fait** |
| **E** | Init SSH de la VM : clé container (pubkey) + login/mot de passe root | C, D | **fait** |
| **F** | Lifecycle : suppression du workspace ⇒ destruction de la VM (`destroy_script`) | D | à venir |
| **G** | Affichage : VM de test sous le workspace propriétaire dans Host admin | D | à venir |
| **H** | Session SSH root depuis le container vers la VM | E | à venir |

## Décisions d'architecture (validées)

- **D — association par table dédiée** (pas un champ sur `HostConfig`) : une VM de test
  appartient à un workspace ; la table relie `(login, workspace) → host`.
- **H — sécurité allégée** : la VM est marquée `tests` et **éphémère**. Une compromission
  n'est pas critique → on ne sur-conçoit pas l'isolation réseau de l'accès SSH root.

## Lot A — marquer le vmid (implémenté)

**Convention.** Dans la spec JSON d'un hyperviseur, l'arg identifiant porte
`"identifier": true`. Sémantique : champ **unique par machine**, non pré-remplissable,
à saisir/générer à chaque création. Un seul arg par spec le porte. Générique (non
couplé au mot « vmid »).

**Implémentation.**
- `scripts/proxmox-clone-vm-node.json` : `"identifier": true` ajouté sur `NEW_VMID`.
- `portal.routes.proxmox.find_identifier_arg(spec) -> str | None` : retourne le nom de
  l'arg marqué (parcourt aussi les groupes `sub` via `_flatten_args`). Point d'entrée
  consommé par les lots B et C.
- La spec est déjà renvoyée telle quelle au front (`get_hypervisor_script`), donc le
  flag est exposé sans changement d'API.

**Tests** (`tests/test_proxmox_spec.py`) : arg top-level, absent → None, dans un `sub`,
spec vide, flag `false` ignoré.

**Pas de changement de comportement visible** — pure fondation.

## Lot B — paramétrage host de test (par type d'hyperviseur)

**Granularité : par type.** Un seul réglage partagé par tous les nodes d'un même type
d'hyperviseur. La spec (`args`) est déjà attachée au type via `add_script`.

**Implication — pas de résolution dynamique.** Les options déroulantes (`STORAGE`,
`TEMPLATE_VMID`…) sont résolues par SSH **sur un node précis** ; un paramétrage *par
type* n'a pas de node, donc on n'exécute **pas** les `option_script`. Le formulaire
affiche les options **statiques** de la spec (typiquement `auto`) et l'admin laisse
`auto` ou saisit une valeur. Un réglage par type fixe surtout les valeurs communes
(`CI_USER`, `MEMORY`, `CORES`, réseau) ; storage/template restent `auto` (résolus au
runtime sur le node réel, lot C). L'arg `identifier` (vmid) est **exclu** du paramétrage.

### Backend

- **Modèle** : `HypervisorType.test_host_params: dict[str, str] = {}` (pydantic,
  `extra="forbid"`).
- **DB** : colonne `hypervisor_types.test_host_params` (JSONB, `server_default='{}'`) +
  migration alembic **021** ; mapping `global_config` (`_ht_*_to_row` / `_row_to_dict`).
- **Spec brute par type** : `GET /admin/hypervisor-types/{name}/script` → télécharge la
  spec via `add_script` **sans** résolution SSH. Factoriser le `_fetch_spec` actuel
  (qui part d'un node) pour accepter directement un `HypervisorType`.
- **Sauvegarde** : `PUT /admin/hypervisor-types/{name}/test-params` body `{params: {...}}`
  → met à jour `test_host_params` du type. (Les clés inconnues / l'arg `identifier`
  sont ignorées côté serveur par robustesse.)

### Frontend

- **Bouton** « Paramétrage host de test » en haut de l'écran Hosts (`AdminHosts`).
- **Dialog** : sélection d'un **type d'hyperviseur** → chargement de sa spec (sans
  options dynamiques) → formulaire des `args` **hors `identifier`**, pré-rempli depuis
  `test_host_params`, → sauvegarde.
- **Composant** `HypervisorArgsForm` : créé **neuf** (autonome, contrôlé) plutôt
  qu'extrait de `GenerateHostDialog` — éviter de charcuter un composant de ~460 lignes
  sans test. `GenerateHostDialog` l'adoptera au lot C (où l'on touche déjà la création).
- **Hooks** : `useHypervisorTypeScript(name)` (GET spec), `useSaveTestParams()` (PUT).
- **i18n** fr + en (`admin.testHostParams.*`).

### Tests

- Backend : `HypervisorType.test_host_params` défaut `{}` ; rejet d'un type extra ;
  l'endpoint de sauvegarde écrit bien le dict (mock conn, pattern `test_admin_hosts`).
- Front : `HypervisorArgsForm` rend les `args`, **exclut** l'arg `identifier`, remonte
  les valeurs saisies (Vitest).

### Hors périmètre lot B

- La résolution dynamique des options par node (reste `auto`).
- L'usage de `test_host_params` à la création (c'est le lot C).

## Lot C+D — création d'une VM de test attachée au workspace

**Qui.** Tout utilisateur, pour **son** workspace (endpoints `/me`). Le backend détient
les credentials ; l'utilisateur ne fournit que **l'hyperviseur** et le **vmid**. Tous
les autres `args` viennent de `test_host_params` du type (figés). require_user.

**Le vmid.** Seul paramètre saisi : l'utilisateur le choisit parmi les **IDs libres**
résolus par l'`option_script` de l'arg `identifier` sur le node (résolution SSH, comme
`get_hypervisor_script`). Le dialog n'affiche que ce champ.

**Association — table `workspace_test_hosts`** : `(id, login, workspace_name,
host_name, created_at)`, unique `(login, workspace_name, host_name)`. Migration **022**.
Module `db/test_hosts.py` (assign / list par workspace / list par host / delete).

**Host créé.** `usage=tests`, mapping `result JSON → HostConfig` porté **côté backend**
(`map_result_to_host`, testable). Enregistré en config (`save_global_db`) puis associé.

### Backend

- `GET /me/test-hypervisors` : nodes utilisables (type avec `add_script` **et**
  `test_host_params` non vide). Retourne `[{name, type, label}]`.
- `GET /me/test-hypervisors/{name}/script` : spec du node **résolue** (réutilise la
  logique SSH de `get_hypervisor_script`) — le front n'affiche que l'arg `identifier`.
- `POST /me/workspaces/{ws}/test-vm` (StreamingResponse) : body `{hypervisor, vmid}`.
  Construit `args = type.test_host_params + {identifier_arg: vmid}`, exécute le script
  (stream SSH), puis — **après** le stream — parse le dernier JSON, crée le host
  `usage=tests`, persiste l'association, et émet une ligne finale de statut.
- Validations : workspace appartient au user ; `vmid` numérique ; l'hyperviseur a un
  type avec `add_script` + `test_host_params`.

### Frontend

- Bouton **« Add VM for Test »** sur `WorkspaceCard` (workspace running).
- Dialog : choix hyperviseur → champ vmid (options résolues) → bouton créer → **logs**
  de création streamés → succès/erreur.
- Hooks `useTestHypervisors`, `useTestVmScript`, `useCreateTestVm` (stream).
- i18n fr + en (`workspaces.testVm.*`).

### Tests

- Backend : `map_result_to_host` (ssh/docker, vmid, usage=tests) ; module association
  (assign/list) sur mock ; validation vmid.
- Front : le dialog n'affiche que l'arg identifier ; déclenche la création.

### Hors périmètre (lots suivants)

- **E** init SSH · **F** destruction avec le workspace · **G** affichage sous le
  workspace · **H** session SSH root depuis le container.

## Lot E — init SSH de la VM (clé container + login/mot de passe root)

Enchaîné **à la fin** du `POST /me/workspaces/{ws}/test-vm`, après l'enregistrement et
l'association du host. Deux accès configurés sur la VM :

1. **Clé du container (juste-à-temps).** Le portail se connecte au container du
   workspace (canal SSH existant), génère la paire si absente
   (`[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519 -q`),
   et lit la **pubkey**. La privée ne quitte jamais le container.
2. **Login/mot de passe root.** Le portail génère un mot de passe aléatoire
   (`secrets.token_urlsafe`).

**Injection dans la VM** (portail → SSH PVE → SSH VM, comme `bootstrap_host_ssh`) :
- ajoute la **pubkey container** dans `/root/.ssh/authorized_keys` (idempotent) ;
- définit le mot de passe root (`chpasswd`), via le `ciuser` + `sudo`.

**Restitution.** Le mot de passe est **stocké dans Harpocrate** (`store_system_secret`,
slug lié au host de test) **et** émis dans le flux de création — l'UI l'affiche une fois
à l'utilisateur, avec l'IP et `root` comme login.

**Sécurité.** Mot de passe root sur une VM marquée `tests` et éphémère : risque assumé
(décision H).

### Découpage / parties testables

- Génération du script d'injection (pur : pubkey + password → commandes shell), avec
  échappement sûr du mot de passe → testable.
- L'orchestration SSH multi-hop n'est exerçable que sur serveur (PVE + VM).

### Frontend

- À la fin du dialog « Add VM for Test » : afficher **login `root`**, **IP**, **mot de
  passe** (copiable), avec mention « notez-le ».
