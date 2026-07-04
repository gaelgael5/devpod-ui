# 019 — Frontend : `deleteWorkspace` — la suppression finale de la config n'est pas contrôlée

- **Sévérité** : majeur
- **Sous-système** : frontend
- **Fichier** : `frontend/src/features/workspaces/useWorkspaceOps.ts:104-111`
- **Statut** : corrigé — le second appel (`DELETE /me/workspaces/${name}`) passe désormais par
  `apiFetchVoid` (au lieu de `apiFetch` sans contrôle de `res.ok`), donc une erreur y propage
  correctement vers `onError` de la mutation au lieu de se résoudre en succès. Tests ajoutés
  (`useWorkspaceOps.test.tsx`) : séquence complète réussie (204 sur les deux appels), et second
  appel en échec (500) → `isError`.

## Symptôme

L'utilisateur supprime un workspace : toast de succès, cache invalidé, mais le workspace
**réapparaît** dans la liste (config non supprimée), tandis que l'étape de recovery (shelve) a bien
été appliquée. État partiel.

## Cause racine

La séquence enchaîne `/delete?shelve=` (recovery) puis `DELETE /me/workspaces/${name}` (ligne 110).
Ce second appel est un `await apiFetch(...)` **sans `res.ok`** — même défaut que
[018](018-frontend-delete-echec-silencieux-apifetch.md), mais au milieu d'une séquence à deux
appels : si le second échoue (500), la mutation se résout quand même en succès.

## Piste de correction

Vérifier `res.ok` (ou utiliser `apiFetchVoid`) sur le second appel et propager l'erreur pour que la
mutation passe en `onError`.
