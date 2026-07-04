# 020 — Frontend : streams fetch dont le reader n'est jamais annulé (fuite + backend qui streame dans le vide)

- **Sévérité** : majeur (fuite de ressource)
- **Sous-système** : frontend
- **Fichiers** :
  - `features/admin/GenerateHostDialog.tsx:398-403` + `useProxmoxScript.ts:96-123` (`useExecuteScript`)
  - `features/compose/components/ServiceLaunchDialog.tsx:172-186` (`DeployForm`), fermeture non gardée `270-273`
  - `features/admin/useHosts.ts:124-151` (`useDestroyVm`)
- **Statut** : corrigé — les 3 sites créent désormais un `AbortController`, le passent en
  `signal` à `apiFetch`, et annulent (`controller.abort()` + `reader.cancel()`) dans le cleanup
  de l'effet du composant/hook (`useEffect` de démontage) — approche retenue plutôt que le garde
  de fermeture de dialog, car elle couvre aussi la navigation/le démontage hors interaction
  utilisateur directe. `useExecuteScript` et `useDestroyVm` annulent aussi tout stream précédent
  en cas d'appel concurrent à `execute()`. Tests ajoutés (rouge→vert vérifié par `git stash`) :
  `ServiceLaunchDialog.test.tsx` (signal abandonné au démontage pendant le streaming),
  `useProxmoxScript.test.tsx`, `useDestroyVm.test.tsx` (idem, au niveau hook).

## Symptôme

Pendant un streaming de logs (génération de host, déploiement compose, destroy VM), l'utilisateur
ferme le dialog (Échap). Le composant se démonte mais la boucle `while(true){ await reader.read() }`
continue dans le hook détaché : la connexion HTTP reste ouverte et le backend continue de streamer
dans le vide.

## Cause racine

Aucun `AbortController` passé au `fetch`, aucun `reader.cancel()` dans un cleanup d'effet. Les
dialogs de streaming ne protègent pas la fermeture pendant le stream (contrairement à
`AddTestVmDialog.tsx:59` qui fait `if (!o && !create.running)`).

## Piste de correction

Créer un `AbortController`, passer `signal` à `apiFetch`, et `abort()` / `reader.cancel()` dans le
cleanup de l'effet appelant — **ou** protéger la fermeture du dialog pendant le streaming comme le
fait déjà `AddTestVmDialog`.
