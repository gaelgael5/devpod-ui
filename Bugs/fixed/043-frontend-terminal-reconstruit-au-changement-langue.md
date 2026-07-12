# 043 — Frontend : le terminal xterm + WebSocket se reconstruit au changement de langue

- **Sévérité** : mineur
- **Sous-système** : frontend
- **Fichiers** : `features/workspaces/WorkspaceSessionTerminal.tsx:73`, `features/workspaces/WorkspaceSshTerminalWindow.tsx:86`, `features/admin/SshTerminalWindow.tsx:74`
- **Statut** : corrigé — les 3 composants lisent désormais `t` via une `tRef` tenue à jour par un
  `useLayoutEffect` sans dépendance (exécuté à chaque rendu, avant peinture), au lieu de dépendre
  directement de `t` dans l'effet qui monte le terminal/WebSocket. Le tableau de dépendances de cet
  effet ne contient plus que `wsName`/`session`/`host.name`(+ `startId`/`shell`/`testHost` selon le
  composant) — `t` n'y figure plus. **Note technique** : l'assignation directe `tRef.current = t`
  dans le corps du composant est interdite par la règle ESLint `react-hooks/refs` de ce projet
  (« Cannot update ref during render ») ; le correctif utilise un `useLayoutEffect` sans tableau de
  dépendances (exécuté après chaque rendu, avant que le navigateur peigne) pour rester conforme.
  Test ajouté (`SshTerminalWindow.test.tsx`) : `i18n.changeLanguage('fr')` après le montage ne
  déclenche ni `terminal.dispose()` ni la fermeture du WebSocket — rouge→vert vérifié par
  `git stash`. Le même correctif a été appliqué mécaniquement aux deux autres fichiers cités (code
  identique dupliqué trois fois).

**Symptôme** : terminal ouvert, l'utilisateur change la langue de l'UI. `t` (react-i18next) change
d'identité à chaque changement de langue ; il figure dans le tableau de dépendances de l'effet qui monte
le terminal → l'effet se nettoie (`ws.close()`, `terminal.dispose()`) et recrée tout, **coupant la
connexion en cours**.

**Cause** : `t` en dépendance d'un effet qui ne l'utilise que pour des messages de statut.

**Correction** : sortir `t` de l'effet (via ref) ou ne mettre en dépendances que `wsName`/`session`/
`host.name`.
