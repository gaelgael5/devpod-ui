# Documentation produit — Workspace Portal

Portail web self-hosted de workspaces de développement : on s'authentifie (OIDC
Keycloak), on paramètre des environnements devcontainer, et on obtient un **VS Code
dans le navigateur**, sans rien installer sur son poste. L'orchestration s'appuie
sur DevPod ; les workspaces sont des conteneurs Docker sur des nœuds distants
pilotés en mTLS.

## Parties

| # | Partie | Pour qui | Contenu |
|---|--------|----------|---------|
| 1 | [Manuel utilisateur](manuel-utilisateur.md) | Développeurs (rôle `dev`) | Se connecter, créer et utiliser un workspace, VS Code navigateur, sessions SSH, skills, kiosque, secrets, VM de test, messagerie inter-agents |
| 2 | [Guide administrateur](guide-administrateur.md) | Admins (rôle `admin`) | Nœuds & mTLS, hôtes/hyperviseurs, recipes, réseau & exposition, OIDC, compose templates, kiosque global, observabilité, gouvernance des skills |
| 3 | [Installation & exploitation](installation-exploitation.md) | Ops / self-host | Prérequis, `install.sh`, docker-compose, `.env`, migrations, backup/restore, mise à jour, dépannage démarrage |
| 4 | [Architecture & concepts](architecture.md) | Tech | Vue d'ensemble, identité OIDC, orchestration DevPod, secrets (Harpocrate/vault), skills (grants/placements/gateway), événements & messagerie, persistance |
| 5 | [Référence API & MCP](reference-api-mcp.md) | Intégrateurs | Endpoints REST `/me/*`, outils MCP `devpod`, catalogue d'événements |
| 6 | [Guide développeur](guide-developpeur.md) | Contributeurs | Stack, layout du code, conventions, tests (pytest/vitest/e2e), workflow `dev` |
| 7 | [FAQ & dépannage](faq-depannage.md) | Tous | Cas concrets (crash-loop vs fenêtre de boot, sessions, captures…) |

> **Conventions** : les écrans sont illustrés par des captures (`images/`) ; les
> schémas sont en [Mermaid](https://mermaid.js.org/) (rendus par GitHub). Le
> texte reste autoportant — les illustrations appuient le propos, sans le
> remplacer.
