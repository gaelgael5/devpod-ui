# M6 — Exposition des workspaces (Caddy + cloudflare-manager)

**Objectif :** rendre chaque workspace accessible en HTTPS authentifié à
`ws-<login>-<name>.dev.yoops.org`, en récupérant le port openvscode de façon fiable et en gérant les
routes dynamiquement sans casser les sessions existantes.

## Stratégie de port (décidée pour éviter le parsing fragile)
Plutôt que parser une sortie DevPod instable (§B-12), **le portail choisit le port hôte** et le fait
publier par le conteneur du workspace :
- Allouer un port libre côté nœud (registre dans `routes/`), p.ex. plage 40000–49999.
- Le passer au workspace via le devcontainer (`appPort` / publication de port) ou via une option
  DevPod de forward. Vérifier le mécanisme exact avec `devpod up --help` (§B-7) et le tester.
- Enregistrer `{ws_id, login, node, host_port, hostname, status}` dans `routes/<ws_id>.json`
  (écriture atomique). C'est la source de vérité du routage, pas une DB.

> Si la version de DevPod ne permet pas de fixer le port proprement, repli : `docker inspect` du
> conteneur du workspace sur le nœud (via le client Docker mTLS) pour lire le port publié. Documenter
> le choix retenu.

## Étapes

### M6.1 — Client Caddy admin (`exposure/caddy.py`)
- Ajout/suppression de route via l'**API admin** (`POST/DELETE` sur `/config/...`), pas par réécriture
  du Caddyfile + reload. Piège §F-31.
- Route type : `ws-<login>-<name>.dev.yoops.org` → vérification OIDC → reverse_proxy vers
  `<node_ip>:<host_port>`. La couche auth est **devant** le proxy ; fail closed. Piège §F-33, §B-11.
- Idempotent (remplacer une route existante du même id).

### M6.2 — Client cloudflare-manager (`exposure/cloudflare.py`)
- Deux modèles possibles ; choisir le plus simple :
  - **Wildcard unique** : une seule règle `*.dev.yoops.org` → Caddy (posée une fois en M5). Alors M6
    n'appelle PAS cloudflare-manager par workspace — tout est routé par Caddy. **Préféré.**
  - Hostname par workspace via cloudflare-manager : plus granulaire mais plus d'appels et de
    nettoyage. À n'utiliser que si le wildcard ne convient pas. Piège §F-32.
- Documenter le modèle retenu dans `01_ARCHITECTURE.md`.

### M6.3 — Intégration au lifecycle (rebrancher M3)
- `up` : après `running`, allouer le port, écrire la route, pousser la route Caddy → exposer l'URL.
- `stop`/`delete` : retirer la route Caddy, libérer le port, mettre à jour `routes/`.
- `status` renvoie l'URL prête quand `running`.

### M6.4 — Sécurité de l'exposition
- Re-vérifier : aucun port openvscode n'est joignable sans passer par Caddy+OIDC. Tester en
  contactant directement `<node_ip>:<host_port>` depuis l'extérieur → doit être bloqué (firewall
  nœud, §A-5) ; seul le portail/Caddy y accède sur le réseau interne. Piège §B-11.

## Tests
- Allocation de port : pas de collision (deux workspaces simultanés → ports distincts), libération au delete.
- Caddy : ajout puis suppression de route via API admin sans toucher aux autres routes (§F-31).
- Route inclut bien la validation OIDC (un appel non authentifié → 401/redirection login).
- `routes/<ws_id>.json` cohérent avec l'état réel après up/stop/delete.

## Definition of Done
- DoD commune + un workspace réel atteignable à son URL, authentifié, et inaccessible en direct.

## Pièges spécifiques M6
- §B-11 (openvscode sans auth → toujours derrière Caddy), §B-12 (port fiable, pas de parsing fragile),
  §F-31 (API admin vs reload), §F-32 (modèle wildcard vs per-host), §F-33 (fail closed), §A-5 (le port
  workspace ne doit pas être joignable directement).
