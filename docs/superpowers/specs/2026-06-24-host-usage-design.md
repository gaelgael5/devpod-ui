# Host « usage » (workspaces / tests) — design

**Date** : 2026-06-24
**Statut** : validé (brainstorming), prêt à implémenter

## Problème

On veut distinguer les docker hosts destinés aux **workspaces** de ceux réservés aux
**tests**. Seuls les hosts « workspaces » doivent apparaître dans la liste de
sélection à la création d'un workspace.

## Décision

Nouvelle propriété `usage` sur `HostConfig`, valeurs `workspaces` | `tests`, défaut
`workspaces`. Cette tâche **pose la fondation** : le champ, son défaut en dur, et le
filtrage. Le moyen de basculer un host en `tests` viendra plus tard (pas d'UI de choix
pour l'instant).

## Périmètre

**Backend**
- `HostConfig.usage: Literal["workspaces", "tests"] = "workspaces"`.
- Colonne `hosts.usage` (Text, NOT NULL, `server_default="workspaces"`) +
  migration alembic **020** → hosts existants = `workspaces`.
- Mapping DB : `_host_row_to_dict` / `_host_to_row` (global_config) lisent/écrivent
  `usage`.
- `add_host` (POST) : `usage="workspaces"` en dur (non exposé au payload).
- `update_host` (PUT) : **préserve** `usage=existing.usage` (sinon une édition
  repasserait un host `tests` en `workspaces`).

**Frontend**
- Type `HostConfig` (useHosts) : champ `usage?` (lecture seule).
- Création de workspace : le sélecteur de host ne liste que les hosts
  `usage === 'workspaces'` (défaut si absent).
- Renommage du bouton **« Generate host »** (`admin.generate.btn`, fr + en).

## Hors périmètre (étapes ultérieures)

- UI pour marquer un host `tests` (bouton/flux dédié).
- Badge d'usage dans la liste Admin Hosts.
- Tout comportement propre aux hosts `tests` au-delà de l'exclusion de la liste.

## Tests

- Modèle : défaut `workspaces` ; valeur hors énum rejetée.
- Migration : chaînage `019 → 020`, importable.
- Front : filtre du sélecteur (`usage === 'workspaces'`) — logique d'une ligne,
  vérifiée par revue (le composant `WorkspaceCreate` est lourd à monter en test).
