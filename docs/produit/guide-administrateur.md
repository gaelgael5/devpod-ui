# Guide administrateur

Réservé aux comptes portant le rôle **`admin`** (routes `/admin/*`, protégées par
`AdminGuard`). L'admin gère l'infrastructure : nœuds, hôtes, réseau, OIDC,
recipes, compose, observabilité et gouvernance des skills.

## Sommaire

1. [Nœuds Docker & mTLS](#1-nœuds-docker--mtls)
2. [Hôtes & hyperviseurs (Proxmox)](#2-hôtes--hyperviseurs-proxmox)
3. [Recipes & sources](#3-recipes--sources)
4. [Réseau & exposition](#4-réseau--exposition)
5. [OIDC & rôles](#5-oidc--rôles)
6. [Types d'agents](#6-types-dagents)
7. [Templates Compose & Jinja](#7-templates-compose--jinja)
8. [Kiosque global](#8-kiosque-global)
9. [Observabilité & logs](#9-observabilité--logs)
10. [Gouvernance des skills](#10-gouvernance-des-skills)

---

## 1. Nœuds Docker & mTLS

`/admin/hosts` — inventaire des nœuds Docker distants sur lesquels tournent les
workspaces.

> 🖼️ _Capture à venir (écran admin Hosts)._

- **Enrôler** un nœud : générer un **join token** (usage unique, TTL court,
  stocké hashé), puis exécuter `install-node.sh` sur la machine (voir
  [Installation](installation-exploitation.md#enrôler-un-nœud-docker)).
- Le certificat mTLS a un **SAN = IP/hostname exacts** ; aucun daemon n'est
  piloté sans `tlsverify`.

---

## 2. Hôtes & hyperviseurs (Proxmox)

`/admin/hypervisors` et `/admin/hypervisor-types` — déclaration des hyperviseurs
Proxmox et de leurs **types** (paramètres de VM de test figés par l'admin).

> 🖼️ _Capture à venir._

Ces réglages alimentent la fonction **VM de test** côté utilisateur (l'utilisateur
ne choisit que l'hyperviseur et le vmid ; le reste est imposé par le
`test_host_params` du type).

---

## 3. Recipes & sources

`/admin/recipes` — catalogue des **recipes** (features devcontainer) et
`/admin/profile-sources` / sources de recettes — dépôts d'où elles proviennent.
Les recipes sont proposées aux utilisateurs à la création d'un workspace.

> 🖼️ _Capture à venir._

---

## 4. Réseau & exposition

`/admin/network` — configuration de l'exposition : Caddy (admin API), domaine
public, Cloudflare (tunnel + DNS-01 wildcard).

> 🖼️ _Capture à venir._

Les routes des workspaces/VS Code sont créées **dynamiquement** via l'admin API
de Caddy (jamais par réécriture + reload). Aucun port n'est joignable sans passer
par Caddy + OIDC (fail-closed).

---

## 5. OIDC & rôles

`/admin/oidc` — paramétrage du fournisseur d'identité.

> 🖼️ _Capture à venir._

Points clés :
- Le **claim de rôle** (`OIDC_ROLE_CLAIM`, défaut `realm_access.roles`) et le
  **nom du rôle admin** (`OIDC_ADMIN_ROLE`) doivent correspondre **exactement** à
  ce que Keycloak émet (ex. `yoops-admin`).
- L'identité est ancrée sur le **`sub`** ; l'email sert d'appariement.

> **Symptôme classique** : écran blanc après login = le rôle attendu ne matche pas
> le token → l'utilisateur n'est jamais reconnu admin. Vérifier le mapping Keycloak.

---

## 6. Types d'agents

`/admin/agent-types` — définition des agents provisionnables dans les workspaces
(ex. `claude-code`) : image de base, fichiers poussés, configuration.

> 🖼️ _Capture à venir._

---

## 7. Templates Compose & Jinja

- `/admin/compose` — **templates de services** docker-compose déployables sur les
  hôtes (ex. navigateur headless, collecteur).
- `/admin/jinja-templates` — templates Jinja et leurs sources.

> 🖼️ _Capture à venir._

Les utilisateurs déploient ces services sur leurs VM de test via **Lancer un
service** (voir [Manuel utilisateur §12](manuel-utilisateur.md#12-machines-de-test)).

---

## 8. Kiosque global

`/applications` (gestion admin) — l'admin définit les **tuiles** du kiosque pour
les utilisateurs standard (qui, eux, se contentent de cliquer).

> 🖼️ _Capture à venir._

---

## 9. Observabilité & logs

`/admin/logs` — accès aux logs. La stack **Alloy → Loki → Grafana** collecte les
logs des conteneurs et la **télémétrie front** (Faro). Grafana est exposé
séparément (`:3001` en dev).

> 🖼️ _Capture à venir._

---

## 10. Gouvernance des skills

La **validation des skills** est une prérogative humaine (admin/propriétaire) : la
file **Validations** (onglet Skills) liste les demandes `pending`, permet
d'**examiner le `SKILL.md`** (et son hash serveur) puis de **valider / mettre en
pause / révoquer**. La révocation coupe le routage sur **tous** les placements
(cascade). Voir [Architecture — Skills](architecture.md#skills--grants-placements-gateway).

> 🖼️ _Capture à venir._
