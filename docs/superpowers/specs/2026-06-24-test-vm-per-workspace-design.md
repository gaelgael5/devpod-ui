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
| **C** | « Add VM for Test » sur `WorkspaceCard` : choix hyperviseur → champs restants → `execute` → host `usage=tests` | A, B | à venir |
| **D** | Association VM ↔ workspace via une **table** dédiée | C | à venir |
| **E** | Bootstrap SSH automatique de la VM créée | C, D | à venir |
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
