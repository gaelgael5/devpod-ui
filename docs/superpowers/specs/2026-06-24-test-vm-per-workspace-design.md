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
| **B** | Paramétrage host de test (admin) : valeurs par défaut des `args` par hyperviseur, sauf l'identifiant | A | à venir |
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
