# 05 — Clés SSH hosts

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | Paire Ed25519 |
| Chemin | `/data/keys/hosts/{host_name}_ed25519` |
| Fonction | `routes/admin.py :: generate_host_ssh_key()` |
| Format | PEM |
| Écriture | Directe (non atomique, création unique) |

Générée à la création d'un host de type `ssh`. La référence `key_path` est stockée dans le `HostConfig` de la `GlobalConfig`.

---

## Modèle Python (Pydantic v2)

Pas de modèle dédié — la donnée est portée par `HostConfig` (voir `01_global_config`).
Le champ `key_path` du `HostConfig` pointe vers le fichier PEM :

```python
class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    key_path: str = ""       # ← chemin vers /data/keys/hosts/{name}_ed25519
    proxmox_node: str = ""
    vmid: str = ""
```

---

## Tables SQL équivalentes

```sql
-- Intégré dans la table `hosts` (définie dans 01_global_config).
-- Ajout de la colonne public_key pour éviter de relire le fichier à chaque usage :

ALTER TABLE hosts ADD COLUMN public_key TEXT NOT NULL DEFAULT '';

-- La colonne key_path est déjà présente dans hosts.
-- La clé privée reste sur le filesystem ; key_path est l'adresse de référence.
```
