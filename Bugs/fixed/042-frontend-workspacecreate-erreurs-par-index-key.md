# 042 — Frontend : `WorkspaceCreate` — erreurs de source indexées par position + `key={i}`

- **Sévérité** : mineur
- **Sous-système** : frontend
- **Fichier** : `frontend/src/features/workspaces/WorkspaceCreate.tsx:97, 100-118, 277-287`
- **Statut** : corrigé — `sources: SourceEntry[]` remplacé par `sourceRows:
  { id: string; entry: SourceEntry }[]` (id stable généré via un compteur `useRef`, jamais réutilisé).
  `sourceErrors` est désormais `Record<string, string>` indexé par cet id, et `key={row.id}` sur
  `SourceRow` (au lieu de `key={i}`). `sources` (le tableau `SourceEntry[]` soumis à l'API) est
  dérivé via `useMemo(() => sourceRows.map(r => r.entry), [sourceRows])` — aucun changement de
  contrat côté `useWorkspaceOps`. Test ajouté : 3 sources A/B/C, seule B a une erreur, suppression
  de A → l'erreur reste sur B (désormais en première position), ne glisse pas sur C — rouge→vert
  vérifié par `git stash` (reproduit exactement le symptôme décrit).

**Symptôme** : trois sources A/B/C, seule B a une erreur (`sourceErrors = {1: ...}`). L'utilisateur
supprime A. Les sources deviennent [B, C] mais `sourceErrors` garde la clé `1` → l'erreur de B s'affiche
sous C. Combiné à `key={i}` sur `SourceRow`, l'état interne des lignes est aussi réattribué à la mauvaise
source.

**Cause** : identité par index de tableau à la fois pour les clés React et pour la map d'erreurs, alors
que la liste supporte la suppression au milieu.

**Correction** : clé stable par source (id généré) et `sourceErrors` indexé sur cet id.
