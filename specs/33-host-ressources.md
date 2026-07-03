# SPEC — Hosts de catégorie « ressources » & lancement de service depuis la vue Configuration Host

**Composant** : `devpod-ui` (backend + frontend)
**Statut** : Draft
**Dépend de** : spec 26 (galerie Docker Compose), champ `HostConfig.usage` existant, mécanisme de bootstrap SSH déjà en place pour les hosts `type=ssh`.

---

## 1. Contexte & objectif

Certains services (ex. un adaptateur MCP pour SonarQube) doivent tourner en permanence,
consommés par tous les agents, sans être liés à un workspace précis. Aujourd'hui, un host
enregistré dans devpod-ui appartient à l'une de trois catégories (`usage` : `workspaces`,
`tests`, `portail`), et aucune ne correspond à ce besoin :

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
   pas un nouveau mécanisme.
2. Un host `ressources` n'a **aucun parent** : jamais de ligne dans `workspace_test_hosts`,
   jamais de destruction en cascade liée à la suppression d'un workspace.
3. Il doit être de `type=ssh` (comme les hosts de test) : `_host_for_node()`
   (`compose/service.py`) n'accepte que ce type pour le déploiement de services compose ;
   `type=docker-tls` reste réservé aux hosts `usage=workspaces`.
4. Les déploiements compose ne filtrent déjà pas par `usage` aujourd'hui
   (`_host_for_node` ne regarde que `host.type`) — **aucune modification nécessaire** côté
   `deploy()` / `deploy_stream()` / cycle de vie des déploiements.
5. Le comportement de `teardown()` (`docker compose down -v` systématique, sans distinction de
   `usage`) reste un point de vigilance **hors périmètre** de cette spec — dette connue et
   acceptée, à traiter séparément le jour où un service à état (ex. cache Trivy) est déployé sur
   un host ressource.

---

## 3. Périmètre

### Inclus
- Extension du littéral `usage` : backend (pydantic), type TypeScript frontend.
- Extension de `_ROLE_MAP` (labels Loki) avec l'entrée `ressources`.
- Ajout du champ `usage` au formulaire Ajouter/Éditer un host (`AdminHosts.tsx`), pour permettre
  de créer un host `ressources` manuellement.
- Nouvelle section dans `AdminHosts.tsx` listant les hosts `usage=ressources`, affichant pour
  chacun ses déploiements compose (statut, ports) et un bouton **« Lancer un service »** ouvrant
  `ServiceLaunchDialog` — repris de la vue workspace, pas réécrit.
- Généralisation mineure de `ServiceLaunchDialog` : le prop `wsName` (qui ne sert qu'à suggérer
  un nom de service par défaut) devient `namingHint`, optionnel.

### Hors périmètre (cette itération)
- Durcissement de `teardown()` (`-v` conditionnel par `usage`) — dette déjà identifiée (§2.5).
- Script Proxmox dédié à la création d'une VM ressource : on réutilise le flux existant
  (formulaire « Ajouter un host » + bootstrap SSH), identique à celui déjà utilisé pour les
  hosts de test et les hosts standards de type `ssh`.
- Curation/autorisation différenciée par profil MCP sur les services tournant sur un host
  ressource (relève de la spec 23, passerelle MCP — pas de cette spec).

---

## 4. Modèle de données — modifications

### Backend — `config/models.py`
```python
class HostConfig(BaseModel):
    ...
    # Destination du host : workspaces, tests, portail (machine du portail), ou
    # ressources (service partagé permanent, sans workspace propriétaire).
    usage: Literal["workspaces", "tests", "portail", "ressources"] = "workspaces"
```

### SQL — `db/tables.py`
Colonne `hosts.usage` déjà `text NOT NULL DEFAULT 'workspaces'` : **aucune migration de
schéma nécessaire**, seule la validation applicative (Literal Pydantic) change.

### `compose/service.py`
```python
_ROLE_MAP: dict[str, str] = {
    "portail": "portail",
    "workspaces": "workspace",
    "tests": "test",
    "ressources": "ressource",
}
```

### Frontend — `features/admin/useHosts.ts`
```ts
export interface HostConfig {
  ...
  // Corrige au passage l'absence de 'portail', déjà un oubli existant côté type TS.
  usage?: 'workspaces' | 'tests' | 'portail' | 'ressources'
}
```

---

## 5. Backend — API

Aucun nouvel endpoint requis pour la création : le flux existant fonctionne déjà pour tout host
`type=ssh`, quel que soit `usage` :
- `POST /admin/hosts` (création, formulaire) — le payload `HostCreatePayload` gagne un champ
  `usage` optionnel (défaut serveur `workspaces` si absent, comme aujourd'hui).
- `POST /admin/hosts/{name}/bootstrap-ssh` (activation de la clé SSH portail, condition
  préalable à tout déploiement compose) — inchangé.

Le filtrage des hosts `ressources` pour l'affichage se fait **côté client**, en cohérence avec
la façon dont `AdminHosts.tsx` filtre déjà `testHosts` depuis la même liste `useHosts()` — pas
de nouveau paramètre de requête tant que le nombre de hosts reste modeste (cf. §9).

---

## 6. Frontend

### 6.1 `AdminHosts.tsx` — répartition des hosts

```ts
const wsHosts       = hosts.filter(h => h.usage === 'workspaces' || h.usage === 'portail')
const testHosts     = hosts.filter(h => h.usage === 'tests')
const resourceHosts = hosts.filter(h => h.usage === 'ressources')
```

Nouvelle section `ResourceHostsSection`, calquée sur `TestHostsGroupedSection` mais **sans**
le regroupement par utilisateur/workspace — un host ressource n'a pas de propriétaire. Une
carte par host : barre d'en-tête (nom, adresse, actions edit/delete/bootstrap-ssh déjà
factorisées) + liste des déploiements compose + bouton « Lancer un service ».

### 6.2 Réutilisation de `ServiceLaunchDialog`

Le point d'entrée `PlayCircle` → `ServiceLaunchDialog` de `TestHostBlock.tsx` est directement
réutilisable : l'appel réel (`POST /api/compose/deployments/stream`) ne prend que `template_id`,
`node_id`, `name`, `env_values` — aucune dépendance à la notion de workspace. Seul le prop
`wsName` sert à préremplir un nom de service par défaut (`${first_service}-${wsName}`) ; il est
généralisé en `namingHint` optionnel, alimenté par le nom du host lui-même en l'absence de
workspace.

```ts
interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  nodeId: string
  nodeLabel: string
  /** Utilisé pour suggérer le nom du service déployé ; optionnel. */
  namingHint?: string
}
```

### 6.3 Nouveau composant `ResourceHostCard.tsx`

Extraction d'un composant proche de `TestHostBlock.tsx` mais sans les éléments liés à
l'alias/workspace (pas d'alias `testN`, pas de bouton « ouvrir SSH depuis le container », pas de
suppression liée à un workspace) : nom du host, adresse, statut des déploiements compose,
actions edit/delete déjà existantes dans `AdminHosts`, + bouton « Lancer un service » ouvrant
`ServiceLaunchDialog`.

---

## 7. Contraintes & conventions

- Fichiers ≤ 300 lignes ; découper `ResourceHostCard.tsx` si nécessaire.
- TypeScript strict, pas de `any`.
- Commits conventionnels en français, branche `dev` exclusivement.
- Réutilisation stricte : ne pas dupliquer `ServiceLaunchDialog`, `ParametersForm`, ni la
  logique de streaming — un seul point d'implémentation partagé entre la vue workspace et la
  nouvelle section ressources de la vue admin.

---

## 8. Critères d'acceptation

1. Je peux créer un host `type=ssh`, `usage=ressources` depuis le formulaire « Ajouter un host ».
2. Une fois le bootstrap SSH effectué (clé portail injectée), une section « Ressources »
   apparaît dans `AdminHosts` listant ce host.
3. Depuis cette section, un bouton « Lancer un service » ouvre le même dialogue de sélection de
   template + paramètres que sur la vue workspace ; le déploiement réussi apparaît dans la liste
   avec son statut, ses ports, et les actions start/stop/restart/logs/down.
4. Les logs Loki de ce déploiement portent `ROLE=ressource`.
5. Un host `usage=ressources` n'apparaît dans aucune vue liée à un workspace (pas d'alias
   `testN`, aucune ligne dans `workspace_test_hosts`).

---

## 9. Points à confirmer à l'implémentation

- Filtrage serveur (`GET /admin/hosts?usage=`) vs filtrage client (actuel) : rester cohérent
  avec l'existant (filtrage client) tant que le nombre de hosts reste modeste ; à revisiter si
  le nombre de hosts croît significativement.
- `teardown()` avec `-v` systématique (§2.5) : point de vigilance pour tout service à état
  déployé sur un host ressource — à traiter dans une spec dédiée le jour où un tel cas se
  présente (ex. Trivy en mode serveur).
