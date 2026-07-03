# 018 — Frontend : échec silencieux systémique sur les mutations DELETE (`apiFetch` sans contrôle de `.ok`)

- **Sévérité** : majeur
- **Sous-système** : frontend
- **Fichiers** :
  - `frontend/src/shared/api/client.ts:42-49` (cause racine : `apiFetch` ne lève que sur 401)
  - `features/admin/useHosts.ts:73` (`useDeleteHost`), `features/admin/useAdminProxmox.ts:26` (`deleteNode`)
  - `features/git-credentials/useGitCredentials.ts:70-73`, `features/certificates/api.ts:76-79`, `features/secrets/api.ts:95-98`
  - `features/mcp/api.ts:156, 209-213, 270-272, 326-328, 351-355`
  - `features/vault/api.ts:72` (`useVaultReset`), `93-95` (`useDeleteVaultKey`)
- **Statut** : ouvert

## Symptôme

Un DELETE qui échoue côté backend (403/404/409/500) fait disparaître l'item un instant, puis il
**réapparaît** après refetch, **sans aucun message d'erreur** à l'utilisateur.

## Cause racine

`apiFetch` ne lève que sur 401 ; pour tout autre statut il **retourne la `Response` sans vérifier
`res.ok`**. Ces mutations utilisent `apiFetch(...)` directement comme `mutationFn` sans tester
`res.ok`. React Query considère la promesse résolue → `onSuccess` s'exécute, `invalidateQueries`
relance le fetch, `onError` ne se déclenche jamais.

Le motif **propre** existe déjà dans le repo : `useDeleteSession`, `deleteTemplate`,
`deleteDeployment`, `useDeleteTestHost` testent bien `res.ok`.

**Cas aggravé — `useVaultReset`** (`vault/api.ts:69-74`) : son `onSuccess` fait
`qc.setQueryData(status(), { status: 'setup_required' })`. Sur un DELETE échoué, l'UI affiche
« coffre réinitialisé » alors que le coffre est intact — désynchronisation à portée sécurité.

## Piste de correction

Router ces DELETE via `apiFetchVoid` (qui appelle `throwApiError` sur `!res.ok`) au lieu de
`apiFetch`. Un seul changement supprime ~12 échecs silencieux d'un coup.

## Vérifié

Confirmé : `client.ts` ne lève que sur 401 (constaté en contexte cette session).
