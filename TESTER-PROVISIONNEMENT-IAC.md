# Tester l'épic provisionnement IaC (tickets 1 → 11)

Plan de la passe de test finale — tout ce que la session autonome du 05/09/2026
n'a pas pu jouer faute d'accès Proxmox/Azure/tailnet. Chaque section est
indépendante ; remonter les écarts au fil de l'eau, la session corrigera.

Ce qui est **déjà vérifié automatiquement** (ne pas re-tester) : schémas et
drivers (75+ tests unitaires), taxonomie des échecs contre la vraie base,
cycle OpenTofu complet contre le backend pg réel avec **state chiffré vérifié
en base** (marqueur en clair absent, mauvaise passphrase refusée),
`tofu validate` des deux modules avec les providers réels.

## 1. Découpe du script (tickets 1–2) — sur pve

```bash
# Clone complet : JSON final identique à l'ancien script (comparer à un run connu)
bash scripts/proxmox-clone-vm-node.sh <VMID> test-iac-01

# Rejouabilité : double passage de configure-node.sh sur la machine créée
bash scripts/configure-node.sh --address <ip> --user debian \
  --key ~/.ssh/id_ed25519 --node-name test-iac-01
# 2e passage : rien ne se duplique (swapfile, fstab, buildx, groupes)

# Échec injecté : couper le réseau de la VM pendant A.10 →
# dernière ligne stdout = {"status":"error","stage":"...","provider_ref":{...}}
# et la VM reste listée avec sa commande de nettoyage sur stderr.
# Variante : --cleanup-on-error → la VM est détruite, pas de provider_ref.

# Secrets : pendant un run avec PORTAL_TOKEN en env, `ps auxww | grep token` → rien
# DHCP sans net-tools : apt-get remove net-tools sur pve, le repli ip neigh détecte l'IP
```

## 2. Spike Azure (ticket 3) — souscription requise

```bash
az login
bash scripts/spike-azure.sh          # ~10 min, tout est détruit à la fin
```
Vérifier : `configure-node.sh` non modifié passe sur l'image Debian stock
(verdict affiché), noter les durées chronométrées dans le doc de cadrage
« Spike Azure » (bloc cadrages docflow).

## 3. Tailnet (ticket 7) — clé d'API Tailscale requise

Console Tailscale : créer un client OAuth scope `auth_keys` porteur de
`tag:workspace-node` (+ ACL tagOwners). Puis :

```bash
TAILNET_AUTHKEY=<clé générée> bash scripts/configure-node.sh \
  --address <ip> --user debian --key <clé> --node-name test-iac-01
# → ligne TAILNET_IP=100.x.y.z ; ssh debian@100.x.y.z depuis le portail passe
# sans règle de firewall. Vérifier le flag réel : tailscale up --help
# Destruction → le nœud disparaît de la liste des devices.
```

## 4. Chemin driver Proxmox (tickets 8–9) — bascule opt-in

Dans `.env` du portail (test1 ou stack dédiée) :

```
TOFU_STATE_PASSPHRASE=<16+ caractères>
PROXMOX_VE_ENDPOINT=https://<pve>:8006
PROXMOX_VE_API_TOKEN=<user>@<realm>!<tokenid>=<uuid>   # jeton API PVE à créer
TOFU_PROVIDER_MIRROR=/data/tofu/mirror
```

```bash
bash scripts/tofu-mirror.sh --mirror /data/tofu/mirror   # une fois
```

Puis IHM : Type d'hyperviseur → poser `provisioning_driver=proxmox` (champ API
`PUT /admin/hypervisor-types/...`) ; le profil machine du chemin driver parle
le vocabulaire spec : `CPU`, `MEMORY_MB`, **`DISK_GB` absolu**, `TEMPLATE_VMID`,
`CI_USER` (un profil avec `DISK_EXTRA` est refusé avec message).

- Souscription d'essai (ou déclenchement manuel) → machine `ded-<vmid>` montée,
  indiscernable d'une machine du script (docker, swap, hostname, enrôlée) ;
- `GET /admin/provisioning/runs` : la tentative est `fait`, `provider_ref`
  porte `{stack, vmid, node, variables}` ;
- VMID déjà pris sur un AUTRE nœud du cluster → échec AVANT création ;
- destruction (`POST /admin/provisioning/runs/{id}/detruire` après un échec
  provoqué, ou `driver.destroy`) → VMID et disque réellement libérés ;
- **rollback** : vider `provisioning_driver` → le chemin script refonctionne ;
- au boot du portail, les hosts existants ont reçu `provider`/`provider_ref`
  (backfill) — vérifier via la config, `vmid`/`proxmox_node` inchangés.

## 5. Taxonomie des échecs (ticket 6)

- Échec provoqué pendant la configuration (couper la VM après création) →
  run `echec_apres_creation` **avec provider_ref**, l'API propose
  `rejouer` (409, refusé) et `detruire` (accepté → redevient rejouable) ;
- `kill -9` du portail pendant un provisionnement → au reboot, le run passe
  `indetermine` ; `POST .../rejouer` → 409 avec le motif ;
- échec avant création (profil cassé) → `echec_avant_creation`, rejeu OK.

## 6. Azure derrière le contrat (tickets 10–11) — ARM + tailnet requis

`.env` : `ARM_CLIENT_ID/ARM_CLIENT_SECRET/ARM_TENANT_ID/ARM_SUBSCRIPTION_ID`
+ `TAILNET_API_KEY` (+ éventuellement `PROVISIONING_COST_CAP_EUR_MONTH=200`).

- provision d'une spec azure (region francecentral) → VM sans IP publique,
  jointe par son IP 100.64/10, SKU résolu affiché dans `resolved` ;
- toutes les ressources du RG portent `managed-by=devflow` + `machine=<nom>`
  (lister par tag et comparer au contenu du RG) ;
- `GET /admin/provisioning/reconciliation` : créer une ressource taguée à la
  main → elle apparaît en `orphelines` et RIEN n'est supprimé ;
- plafond : poser un cap sous le coût demandé → refus avant toute création
  (aucun RG, aucune clé tailnet) ;
- destruction → RG supprimé (cascade) ET nœud retiré du tailnet.

## Écarts déjà connus / arbitrages en attente

- `proxmox-clone-vm-node.sh` restant : 489 lignes hors commentaires (>300
  exigées par le ticket 1) — assumé pour ne pas amputer de comportement ;
- le `bash -c` distant composé par le portail (chemin script legacy) porte
  encore `PORTAL_TOKEN` dans l'argv du wrapper — transport à revoir avec
  l'exécuteur (consigné au journal du ticket 2) ;
- IHM : écran des runs (« reprendre / détruire »), affichage de l'estimation
  de coût avant confirmation, champ `provisioning_driver` dans la page Types
  d'hyperviseurs — l'API est prête, les écrans restent à câbler ;
- suite backend : 157 échecs préexistants (ticket « Remettre la suite au
  vert ») — zéro régression prouvée par diff de baseline.
