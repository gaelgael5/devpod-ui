# 044 — Frontend : noms de session non encodés dans l'URL

- **Sévérité** : mineur
- **Sous-système** : frontend
- **Fichier** : `features/workspaces/useWorkspaceSessions.ts:13, 38, 58`
- **Statut** : ouvert

**Symptôme** : `WorkspaceTerminals` laisse l'utilisateur éditer librement le nom de session. Un nom
contenant `/`, un espace ou `#` casse le chemin `/me/workspaces/${wsName}/sessions/${sessionName}`
(création et suppression). `wsName` n'est pas encodé ici non plus, alors qu'il l'est partout ailleurs
(`useTestVm.ts:24`, `WorkspaceSshTerminalWindow.tsx:61`).

**Correction** : `encodeURIComponent` sur `wsName` et `sessionName` ; valider le nom de session côté UI
comme les noms de workspace (`NAME_RE`).
