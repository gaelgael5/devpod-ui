# DevPod Portal — Manuels utilisateur

> Documentation générée automatiquement le 2026-07-05 à partir de captures d'écran
> réelles de l'application (branche `dev`, environnement de test).

Le portail DevPod vous permet de créer et piloter des environnements de développement
(workspaces) dans votre navigateur : chaque workspace est un devcontainer complet avec
VS Code web, terminal, secrets et outillage préinstallé — sans rien installer sur votre poste.

## Sommaire

| Chapitre | Contenu |
|----------|---------|
| [Démarrage rapide](00-demarrage-rapide.md) | Tutoriel bout-en-bout : de la connexion au premier workspace |
| [1. Premiers pas](01-premiers-pas.md) | Connexion, interface, menu utilisateur, coffre (PIN), thème et langue |
| [2. Workspaces](02-workspaces.md) | Créer, démarrer, arrêter un workspace ; groupes ; VS Code ; sessions terminal |
| [3. Recettes & profils VS Code](03-recettes-et-profils.md) | Catalogue de recettes, profils d'extensions VS Code |
| [4. Services & Sécurité](04-services-et-securite.md) | Vault, certificats, secrets, credentials Git, MCP, services, règles d'automatisation, journal d'événements |
| [5. Docker Compose](05-docker-compose.md) | Déployer des services annexes depuis la galerie Compose |
| [6. Administration](06-administration.md) | Hôtes Docker, galeries, hyperviseurs, OIDC, réseau, logs centralisés (rôle `admin` requis) |
| [7. FAQ & dépannage](07-faq-depannage.md) | Questions récurrentes et résolution des problèmes courants |

## Autres manuels

- [Manuel d'exploitation](../exploitation/manuel-exploitation.md) — installation,
  nœuds, sauvegarde/restauration, mise à jour (admin système).
- [Guide agents IA / MCP](../agents_mcp/guide-agents-mcp.md) — piloter les workspaces
  via la passerelle MCP, messagerie inter-agents, règles.

## Conventions

- Les captures d'écran se trouvent dans le dossier [`images/`](images/).
- Les chapitres 1 à 5 concernent tous les utilisateurs (rôle `dev`).
- Le chapitre 6 nécessite le rôle `admin` : les entrées correspondantes n'apparaissent
  dans le menu que si votre compte a ce rôle.
