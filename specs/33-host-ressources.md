# SPEC — Hosts de catégorie « ressources » & lancement de service depuis la vue Configuration Host

**Composant** : `devpod-ui` (backend + frontend)
**Statut** : Draft (backend implémenté — commit `1b1ae07` ; frontend à faire)
**Dépend de** : spec 26 (galerie Docker Compose), champ `HostConfig.usage` existant, mécanisme de bootstrap SSH déjà en place pour les hosts `type=ssh`.

---

## 1. Contexte & objectif

Certains services (ex. un adaptateur MCP pour SonarQube) doivent tourner en permanence,
consommés par tous les agents, sans être liés à un workspace précis. Un host enregistré dans
devpod-ui appartenait jusqu'ici à l'une de trois catégories (`usage` : `workspaces`, `tests`,
`portail`), et aucune ne correspond à ce besoin :

- `workspaces` : machine Docker qui exécute des containers d'agents.
- `tests` : VM éphémère **possédée par un workspace précis** (table `workspace_test_hosts`),
  détruite quand ce workspace supprime sa VM de test.
- `portail` : la machine qui héberge le portail devpod-ui lui-même.

On ajoute une 4e catégorie, `ressources` : un host permanent, **sans propriétaire**, dédié à
l'hébergement de services compose partagés par l'ensemble des agents.

---

## 2. Décisions d'architecture déjà tranchées (ne pas re-débattre)

1. Le champ `HostConfig.usage` existe déjà et est réellement consommé (labellisation des logs
   Loki via `_ROLE_MAP` dans `compose/service.py`) — on lui ajoute une 4e valeur, on n'invente
   pas un nouveau mécanisme. **Fait** (commit `1b1ae07`).
2. Un host `ressources` n'a **aucun parent** : jamais de ligne dans `workspace_test_hosts`,
   jamais de destruction en cascade liée à la suppression d'un workspace.
3. Il doit être de `type=ssh` (comme les hosts de test) : `_host_for_node()`
   (`compose/service.py`) n'accepte que ce type pour le déploiement de services compose.
4. Les déploiements compose ne filtrent déjà pas par `usage` — aucune modification nécessaire
   côté `deploy()` / `deploy_stream()` / cycle de vie des déploiements.
5. **Pas de vue dédiée « Ressources ».** Les hosts ressources apparaissent dans la même vue
   `AdminHosts.tsx` que les hosts standards et les hosts de test — une catégorie de plus dans
   la même liste, pas une navigation séparée.
6. **Réutilisation par factorisation, pas par duplication.** Le bloc « liste des déploiements +
   lancement de service » qui existe déjà dans la vue workspace (`TestHostBlock.tsx`) est
   extrait en composant partagé, consommé à la fois par la vue workspace et par la nouvelle
   section ressources de `AdminHosts.tsx`.
7. **Périmètre limité aux ressources.** La section « hosts de test » existante dans
   `AdminHosts.tsx` reste en lecture seule (statut affiché, aucune action) : factoriser un
   composant ne veut pas dire l'appliquer partout où il devient disponible. Seule la nouvelle
   section ressources gagne les actions start/stop/restart/logs/lancer.
8. Comportement de `teardown()` (`docker compose down -v` systématique, sans distinction de
   `usage`) : point de vigilance **hors périmètre** de cette spec — dette connue et acceptée,
   à traiter séparément le jour où un service à état est déployé sur un host ressource.

---

## 3. Périmètre

### Inclus
- Extension du littéral `usage` : backend (pydantic), type TypeScript frontend. **Fait.**
- Extension de `_ROLE_MAP` (labels Loki) avec l'entrée `ressources`. **Fait.**
- Extraction de `DeploymentRow` (rendu d'un déploiement + ses actions) depuis `TestHostBlock.tsx`
  vers un composant partagé.
- Extraction de `HostServicesBlock` (liste des déploiements + bouton « Lancer un service » +
  `ServiceLaunchDialog`) depuis `TestHostBlock.tsx` vers un composant partagé, réutilisé par
  `TestHostBlock.tsx` (vue workspace) et la nouvelle section ressources (vue admin).
- Généralisation de `ServiceLaunchDialog` : le prop `wsName` devient `namingHint`, optionnel.
- Nouvelle section dans `AdminHosts.tsx` listant les hosts `usage=ressources` : en-tête minimal
  (nom, adresse, edit/delete/bootstrap-ssh déjà existants) + `HostServicesBlock`.
- Ajout du champ `usage` au formulaire Ajouter/Éditer un host.

### Hors périmètre (cette itération)
- Toute action (start/stop/restart/logs/lancer) sur la section « hosts de test » existante de
  `AdminHosts.tsx` — reste en lecture seule, décision explicite (§2.7).
- Vue dédiée « Ressources » séparée de `AdminHosts.tsx` — explicitement écartée (§2.5).
- Durcissement de `teardown()` (`-v` conditionnel par `usage`) — dette déjà identifiée (§2.8).
- Script Proxmox dédié à la création d'une VM ressource : on réutilise le flux existant
  (formulaire « Ajouter un host » + bootstrap SSH).

---

## 4. Modèle de données — modifications (fait, commit `1b1ae07`)

- `HostConfig.usage: Literal["workspaces", "tests", "portail", "ressources"] = "workspaces"`
  (`config/models.py`).
- `HostCreateRequest.usage` idem (`routes/admin.py`).
- `_ROLE_MAP["ressources"] = "ressource"` (`compose/service.py`).
- Type TS `HostConfig.usage` aligné sur les 4 valeurs (`features/admin/useHosts.ts`) — corrige
  au passage l'oubli de `'portail'`, absent côté TS avant ce changement.
- Aucune migration SQL : colonne `hosts.usage` déjà `text NOT NULL DEFAULT 'workspaces'`.

---

## 5. Backend — API

Aucun nouvel endpoint requis :
- `POST /admin/hosts` / `PUT /admin/hosts/{name}` acceptent déjà `usage` dans le payload.
- `POST /admin/hosts/{name}/bootstrap-ssh` (activation clé SSH portail) inchangé.
- `GET /admin/hosts/{name}/deployments` (lecture) existe déjà, utilisé par la section hosts de
  test actuelle — **non réutilisé** pour la section ressources (voir §6, qui a besoin des
  actions, pas seulement de la lecture).

---

## 6. Frontend — plan d'implémentation détaillé

### 6.1 `features/compose/components/DeploymentRow.tsx` (nouveau)
Extraction de `ServiceRow` + `DeploymentLogsDialog`, copiés tels quels depuis
`TestHostBlock.tsx` (statut, ports, actions start/stop/restart/logs/delete, dialogue de logs).
Dépendances inchangées : `useDeploymentAction`, `useDeleteDeployment`, `useDeploymentLogs`,
`ComposeDeployment`, `DeploymentStatus`.

### 6.2 `features/compose/components/HostServicesBlock.tsx` (nouveau)
```ts
interface Props {
  nodeId: string
  nodeLabel: string
  namingHint?: string
  deployments: ComposeDeployment[]
}
```
Rend : la liste des déploiements (via `DeploymentRow`), ou le message vide
(`compose.empty.deployments`), + le bouton « Lancer un service » (icône `PlayCircle`) ouvrant
`ServiceLaunchDialog` avec `nodeId`, `nodeLabel`, `namingHint`.

### 6.3 `features/compose/components/ServiceLaunchDialog.tsx`
- `wsName: string` → `namingHint?: string`.
- Nom par défaut : `template.first_service ? (namingHint ? \`${template.first_service}-${namingHint}\` : template.first_service) : ''`.
- Le reste du composant (sélection de template, formulaire, streaming) est inchangé.

### 6.4 `features/workspaces/TestHostBlock.tsx`
- Retire `ServiceRow`/`DeploymentLogsDialog` (déplacés en 6.1) et le bloc liste+bouton+dialogue
  actuel (déplacé en 6.2).
- Remplace ce corps par :
  ```tsx
  <HostServicesBlock
    nodeId={host.name}
    nodeLabel={host.alias}
    namingHint={wsName}
    deployments={deployments}
  />
  ```
- En-tête inchangé (alias `testN`, ouverture SSH depuis le container, suppression) : ces
  éléments n'ont pas de sens pour un host ressource et restent spécifiques à ce composant.

### 6.5 `features/admin/AdminHosts.tsx`
- Répartition des hosts :
  ```ts
  const wsHosts       = hosts.filter(h => h.usage === 'workspaces' || h.usage === 'portail')
  const testHosts     = hosts.filter(h => h.usage === 'tests')       // inchangé, lecture seule
  const resourceHosts = hosts.filter(h => h.usage === 'ressources')  // nouveau
  ```
- Nouvelle section (simple liste, **pas** de regroupement par utilisateur/workspace — un host
  ressource n'a pas de propriétaire, contrairement à `TestHostsGroupedSection`) : pour chaque
  host, en-tête minimal (nom, adresse, boutons edit/delete/bootstrap-ssh déjà factorisés dans
  `AdminHosts`) + `<HostServicesBlock nodeId={host.name} nodeLabel={host.name} namingHint={host.name} deployments={...} />`.
  Les déploiements viennent de `useDeployments()` (le hook compose général, pas
  `useHostDeployments`/`HostDeployment` qui est en lecture seule et ne porte pas les actions).
- Section `TestHostsGroupedSection` : **aucun changement** (§2.7 — hors périmètre).
- Formulaire Ajouter/Éditer (`EMPTY`, `form`, `handleSubmit`) : ajout d'un `<Select>` pour
  `usage` avec les 4 valeurs (`workspaces` par défaut).

### 6.6 i18n (`i18n/fr.json`, `i18n/en.json`)
Nouvelles clés : `admin.resourceHosts.sectionTitle`, `admin.resourceHosts.empty`,
`admin.form.usage` + labels des 4 valeurs de `usage`.

---

## 7. Contraintes & conventions

- Fichiers ≤ 300 lignes ; découper si nécessaire.
- TypeScript strict, pas de `any`.
- Commits conventionnels en français, branche `dev` exclusivement.
- Réutilisation stricte : `ServiceLaunchDialog`, `DeploymentRow`, `HostServicesBlock` sont des
  points d'implémentation uniques, partagés entre vue workspace et vue admin — jamais dupliqués.

---

## 8. Critères d'acceptation

1. Je peux créer un host `type=ssh`, `usage=ressources` depuis le formulaire « Ajouter un host ».
2. Une fois le bootstrap SSH effectué, ce host apparaît dans une section de `AdminHosts` dédiée
   aux ressources — dans la même vue que les hosts standards et les hosts de test, pas une vue
   séparée.
3. Depuis cette section, le bouton « Lancer un service » ouvre le même dialogue que sur la vue
   workspace (sélection de template + paramètres + streaming), et le déploiement réussi
   apparaît avec statut/ports et les actions start/stop/restart/logs/down.
4. La section « hosts de test » de `AdminHosts` reste strictement inchangée (lecture seule).
5. Les logs Loki de ce déploiement portent `ROLE=ressource`.
6. Un host `usage=ressources` n'apparaît dans aucune vue liée à un workspace (pas d'alias
   `testN`, aucune ligne dans `workspace_test_hosts`).
7. `TestHostBlock.tsx` (vue workspace) fonctionne à l'identique après le passage par
   `HostServicesBlock` — aucune régression de comportement visible.

---

## 9. Points à confirmer à l'implémentation

- Filtrage serveur (`GET /admin/hosts?usage=`) vs filtrage client (actuel) : rester cohérent
  avec l'existant (filtrage client) tant que le nombre de hosts reste modeste.
- `teardown()` avec `-v` systématique (§2.8) : point de vigilance pour tout service à état
  déployé sur un host ressource — à traiter dans une spec dédiée le jour où un tel cas se
  présente (ex. Trivy en mode serveur).
