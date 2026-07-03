# 043 — Frontend : le terminal xterm + WebSocket se reconstruit au changement de langue

- **Sévérité** : mineur
- **Sous-système** : frontend
- **Fichiers** : `features/workspaces/WorkspaceSessionTerminal.tsx:73`, `features/workspaces/WorkspaceSshTerminalWindow.tsx:86`, `features/admin/SshTerminalWindow.tsx:74`
- **Statut** : ouvert

**Symptôme** : terminal ouvert, l'utilisateur change la langue de l'UI. `t` (react-i18next) change
d'identité à chaque changement de langue ; il figure dans le tableau de dépendances de l'effet qui monte
le terminal → l'effet se nettoie (`ws.close()`, `terminal.dispose()`) et recrée tout, **coupant la
connexion en cours**.

**Cause** : `t` en dépendance d'un effet qui ne l'utilise que pour des messages de statut.

**Correction** : sortir `t` de l'effet (via ref) ou ne mettre en dépendances que `wsName`/`session`/
`host.name`.
