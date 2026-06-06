# Ajout d'un deuxième nœud Docker

Ce guide couvre l'enrôlement d'un nœud supplémentaire dans un portail déjà opérationnel.
La procédure d'installation sur le nœud est identique à celle du premier nœud —
ce document se concentre sur les différences et la gestion multi-nœuds.

---

## Prérequis

- Portail démarré et opérationnel (premier nœud déjà enrôlé et fonctionnel)
- CA initialisée dans `/data/certs/ca/` — **ne pas relancer `install.sh`**
- Accès admin au portail (rôle `admin` dans Keycloak)
- Nom DNS-safe **différent** du premier nœud (regex : `^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$`)
- Les prérequis nœud sont identiques : voir [installation-first-node.md](installation-first-node.md)

---

## Vérifier les nœuds existants

Avant d'enrôler, lister les hosts déjà enregistrés pour éviter les conflits de nom :

```http
GET /admin/hosts
```

Réponse :
```json
[
  {
    "name":        "pve2-docker",
    "type":        "docker-tls",
    "docker_host": "tcp://192.168.1.50:2376",
    "default":     true
  }
]
```

---

## Enrôlement du deuxième nœud

La procédure est **strictement identique** à celle du premier nœud.
Suivre les étapes 1, 2 et 3 de [installation-first-node.md](installation-first-node.md)
en substituant le nom et l'adresse du nouveau nœud.

**Exemple avec un deuxième nœud `pve3-docker` à `192.168.1.51` :**

**Étape 1 — Générer le token (admin) :**
```http
POST /admin/nodes/token
Content-Type: application/json

{
  "node_name": "pve3-docker",
  "address":   "192.168.1.51"
}
```

**Étape 2 — Lancer le script sur le nœud `192.168.1.51` en root :**
```bash
curl -sSL https://dev.yoops.org/install-node.sh | bash -s -- \
  --portal    https://dev.yoops.org \
  --token     <token> \
  --node-name pve3-docker \
  --address   192.168.1.51
```

Après enrôlement, `config.yaml` contient les deux nœuds :
```yaml
hosts:
  - name: pve2-docker
    type: docker-tls
    docker_host: tcp://192.168.1.50:2376
    default: true
  - name: pve3-docker
    type: docker-tls
    docker_host: tcp://192.168.1.51:2376
    default: false          # toujours false à l'enrôlement
```

---

## Gestion du nœud par défaut

Le nœud par défaut (`default: true`) est utilisé lorsqu'un workspace est créé
sans préciser de nœud cible. Un seul nœud peut être défaut à la fois.

### Connaître le nœud par défaut actuel

```http
GET /admin/hosts
```

### Changer le nœud par défaut

`PUT /admin/config` permet de mettre à jour la liste des hosts en une opération atomique.
Passer la liste complète avec les flags `default` ajustés :

```http
PUT /admin/config
Content-Type: application/json

{
  "hosts": [
    {
      "name":        "pve2-docker",
      "type":        "docker-tls",
      "docker_host": "tcp://192.168.1.50:2376",
      "default":     false
    },
    {
      "name":        "pve3-docker",
      "type":        "docker-tls",
      "docker_host": "tcp://192.168.1.51:2376",
      "default":     true
    }
  ]
}
```

> **Attention** : le `PUT /admin/config` remplace la section ciblée en entier.
> Toujours inclure tous les hosts existants dans la liste pour ne pas en supprimer.

---

## Créer un workspace sur un nœud spécifique

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

---

## Vérifier les deux nœuds

### Lister tous les hosts enregistrés

```http
GET /admin/hosts
```

### Tester chaque nœud individuellement

```bash
# Premier nœud
devpod up ghcr.io/microsoft/vscode-dev-containers/base:ubuntu \
  --provider docker-tls --id test-pve2 \
  --option HOST=tcp://192.168.1.50:2376

# Deuxième nœud
devpod up ghcr.io/microsoft/vscode-dev-containers/base:ubuntu \
  --provider docker-tls --id test-pve3 \
  --option HOST=tcp://192.168.1.51:2376
```

---

## Dépannage spécifique multi-nœuds

### `Host 'pve3-docker' already registered`

Un host de ce nom existe déjà dans `config.yaml`.
Vérifier avec `GET /admin/hosts` — si le nœud est orphelin (cert expiré, machine supprimée),
retirer l'entrée via `PUT /admin/config` en omettant ce host de la liste,
puis relancer l'enrôlement.

### `No default host configured`

Aucun host n'a `default: true`. Les workspaces créés sans champ `host` échouent en 404.
Désigner un nœud par défaut via `PUT /admin/config` (voir section ci-dessus).

### Un seul nœud répond, l'autre est muet

Vérifier que le pare-feu du nœud silencieux autorise bien le port 2376
depuis l'IP du portail (voir [dépannage — port 2376 inaccessible](installation-first-node.md#port-2376-inaccessible-depuis-le-portail)).
