# Enrôlement des nœuds Docker

Ce guide couvre l'ajout de nœuds Docker au portail workspace — premier nœud ou nœuds
supplémentaires. La procédure d'enrôlement est identique quel que soit le rang du nœud.
Le portail joue le rôle de CA : il signe le certificat serveur du daemon,
et seul un client porteur d'un cert signé par cette même CA peut piloter le daemon.

---

## Prérequis

### Côté nœud (VM ou serveur dédié)

- **OS** : Debian/Ubuntu 20.04+ ou RHEL/Rocky 8+ (systemd requis)
- **Accès** : root ou sudo
- **Réseau** : port **2376/tcp** joignable depuis l'IP du portail uniquement
- **Outils** : `curl`, `jq`, `openssl`, `timedatectl`
  ```bash
  apt-get install -y curl jq openssl systemd   # Debian/Ubuntu
  dnf install -y curl jq openssl systemd        # RHEL/Rocky
  ```
- **Nom DNS-safe** : `pve2-docker`, `node-gpu-01`…
  (regex : `^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$`)
- **Adresse** : IP fixe ou hostname résolvable depuis le portail

### Côté portail

- Portail démarré et accessible (`https://dev.yoops.org`)
  → Si ce n'est pas encore fait : [deploiement-portail.md](deploiement-portail.md)
- `install.sh` exécuté (CA initialisée dans `/data/certs/ca/`)
- Compte admin disponible (rôle `admin` dans Keycloak)

---

## Étape 1 — Générer un join token (admin)

Depuis n'importe quel outil HTTP authentifié en admin
(session Keycloak ou outil comme HTTPie/curl avec cookie de session) :

```http
POST /admin/nodes/token
Content-Type: application/json

{
  "node_name": "pve2-docker",
  "address":   "192.168.1.50"
}
```

Réponse :
```json
{
  "token":       "aB3xQ…",
  "expires_in":  "3600s",
  "install_cmd": "curl -sSL https://dev.yoops.org/install-node.sh | bash -s -- --portal https://dev.yoops.org --token aB3xQ… --node-name pve2-docker --address 192.168.1.50"
}
```

**Le champ `install_cmd` contient la commande prête à l'emploi.**
Le token est à **usage unique** et expire dans **1 heure**.
Ne pas le partager ni l'enregistrer — il est équivalent à une autorisation d'enrôlement.

---

## Étape 2 — Exécuter le script sur le nœud

Depuis le nœud **en root** :

```bash
curl -sSL https://dev.yoops.org/install-node.sh | bash -s -- \
  --portal    https://dev.yoops.org \
  --token     <token> \
  --node-name pve2-docker \
  --address   192.168.1.50
```

Le script effectue dans l'ordre :

| #  | Action                          | Détail                                                                                      |
|----|---------------------------------|---------------------------------------------------------------------------------------------|
| 1  | Vérifie les outils requis       | Interrompt si `curl`, `jq`, `openssl` ou `timedatectl` manquent                            |
| 2  | Installe Docker Engine          | Idempotent — ignoré si Docker est déjà présent                                              |
| 3  | Synchronise NTP                 | **Obligatoire avant la génération du cert** — un cert avec horloge décalée est rejeté immédiatement |
| 4  | Génère la clé privée RSA 4096   | Stockée dans `/etc/docker/tls/server-key.pem` (600). La clé ne quitte jamais le nœud.      |
| 5  | Génère une CSR avec SAN         | CN = `node-name`, SAN = IP ou hostname de `address`                                         |
| 6  | Envoie la CSR au portail        | `POST /admin/nodes/enroll` avec Bearer token                                                |
| 7  | Sauvegarde cert + CA            | `/etc/docker/tls/server-cert.pem` et `ca.pem` (600)                                        |
| 8  | Configure `daemon.json`         | mTLS sur `tcp://0.0.0.0:2376` — sauvegarde l'existant si présent                           |
| 9  | Crée un drop-in systemd         | Neutralise le flag `-H fd://` qui entre en conflit avec `daemon.json` — **étape critique**  |
| 10 | Configure le pare-feu           | Port 2376 autorisé depuis l'IP du portail (ufw ou firewalld)                                |
| 11 | Redémarre Docker                | Applique la configuration mTLS                                                              |
| 12 | Vérifie l'écoute                | Contrôle que Docker écoute bien sur `:2376`                                                 |

Durée : 2 à 5 minutes selon la vitesse de téléchargement de Docker.

---

## Étape 3 — Vérifier l'enrôlement

### Sur le nœud

```bash
# Docker daemon mTLS en écoute
ss -tlnp | grep 2376

# Logs en cas d'erreur
journalctl -u docker --no-pager -n 50
```

### Sur le portail

Le nœud apparaît dans `/data/config.yaml` :

```yaml
hosts:
  - name: pve2-docker
    type: docker-tls
    docker_host: tcp://192.168.1.50:2376
    default: false
```

### Test de connexion depuis le portail

```bash
# Depuis le conteneur portail ou le serveur qui héberge devpod
devpod provider use docker-tls \
  --option HOST=tcp://192.168.1.50:2376 \
  --option CACERT=/data/certs/ca/ca.pem \
  --option CERT=/data/certs/portal/client-cert.pem \
  --option KEY=/data/certs/portal/client-key.pem

devpod up ghcr.io/microsoft/vscode-dev-containers/base:ubuntu \
  --provider docker-tls --id test-connection
```

---

## Rotation et renouvellement

| Élément            | Durée              | Action à l'expiration                                                                    |
|--------------------|--------------------|------------------------------------------------------------------------------------------|
| Join token         | 1 heure            | Regénérer via `POST /admin/nodes/token`                                                  |
| Cert serveur nœud  | **5 ans** (1825 j) | Ré-enrôler le nœud (supprimer l'host de `config.yaml` puis relancer le script)          |
| CA portail         | Selon `install.sh` | Ne jamais régénérer la CA — renouveler les certs feuilles à la place                    |

---

## Dépannage

### Docker n'écoute pas sur le port 2376

```bash
journalctl -u docker --no-pager -n 50
```

Si le journal affiche `unable to configure the Docker daemon ... conflicting options`,
c'est que le flag `-H fd://` du service systemd entre en conflit avec `daemon.json`.

```bash
# Vérifier le drop-in
cat /etc/systemd/system/docker.service.d/override.conf
# Doit contenir exactement :
# [Service]
# ExecStart=
# ExecStart=/usr/bin/dockerd

# Corriger si nécessaire
systemctl daemon-reload && systemctl restart docker
```

### 401 Token already used ou Token expired

Le token est à usage unique et expire en 1 heure.
Regénérer un nouveau token depuis l'admin et relancer le script.

### CSR CN must be 'pve2-docker'

Le `--node-name` passé au script ne correspond pas à celui déclaré lors de la création du token.
Les deux doivent être identiques.

### Port 2376 inaccessible depuis le portail

Si `ufw` et `firewalld` sont tous les deux absents, le script affiche un avertissement et
laisse la configuration manuelle à l'opérateur :

```bash
# iptables (exemple — adapter selon la politique existante)
iptables -A INPUT -s <IP_PORTAIL> -p tcp --dport 2376 -j ACCEPT
iptables -A INPUT -p tcp --dport 2376 -j DROP

# Persister selon la distrib
apt-get install -y iptables-persistent && netfilter-persistent save  # Debian/Ubuntu
```

### Nœud déjà enrôlé (`Host 'pve2-docker' already registered`)

Supprimer l'entrée correspondante dans `/data/config.yaml` sur le portail
(édition atomique ou via un endpoint d'administration si disponible),
puis regénérer un token et relancer l'enrôlement.

### `No default host configured`

Aucun host n'a `default: true`. Les workspaces créés sans champ `host` échouent en 404.
Désigner un nœud par défaut via `PUT /admin/config` (voir section ci-dessus).

### Un nœud répond, un autre est muet

Vérifier que le pare-feu du nœud silencieux autorise bien le port 2376
depuis l'IP du portail (voir [Port 2376 inaccessible depuis le portail](#port-2376-inaccessible-depuis-le-portail)).

---

## Gestion des nœuds

### Enrôler un nœud supplémentaire

Répéter les étapes 1, 2 et 3 en substituant le nom et l'adresse du nouveau nœud.
Vérifier d'abord qu'aucun host du même nom n'existe déjà :

```http
GET /admin/hosts
```

Réponse exemple avec deux nœuds enrôlés :
```json
[
  { "name": "pve2-docker", "type": "docker-tls", "docker_host": "tcp://192.168.1.50:2376", "default": true  },
  { "name": "pve3-docker", "type": "docker-tls", "docker_host": "tcp://192.168.1.51:2376", "default": false }
]
```

### Nœud par défaut

Le nœud par défaut (`default: true`) est utilisé lorsqu'un workspace est créé sans préciser
de nœud cible. Un seul nœud peut être défaut à la fois.

Pour changer le nœud par défaut, passer la liste complète avec les flags ajustés —
`PUT /admin/config` remplace la section en entier, toujours inclure tous les hosts existants :

```http
PUT /admin/config
Content-Type: application/json

{
  "hosts": [
    { "name": "pve2-docker", "type": "docker-tls", "docker_host": "tcp://192.168.1.50:2376", "default": false },
    { "name": "pve3-docker", "type": "docker-tls", "docker_host": "tcp://192.168.1.51:2376", "default": true  }
  ]
}
```

### Cibler un nœud spécifique à la création

Le champ `host` de `UpRequest` permet de cibler un nœud précis.
Sans ce champ (ou `host: ""`), le nœud par défaut est utilisé.

```http
POST /workspaces/mon-projet/up
Content-Type: application/json

{
  "source": "github.com/org/repo",
  "host":   "pve3-docker"
}
```

Si le nœud demandé n'existe pas dans `config.yaml`, la réponse est `404 Host not found`.
Si aucun nœud par défaut n'est configuré et que `host` est vide, la réponse est également `404`.
