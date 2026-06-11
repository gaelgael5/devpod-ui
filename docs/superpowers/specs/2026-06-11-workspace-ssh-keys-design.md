# Design — Clés SSH par workspace

**Date :** 2026-06-11  
**Statut :** Approuvé

## Contexte

L'utilisateur veut pouvoir enregistrer une clé publique SSH sur une plateforme de gestion de code source (GitHub, GitLab, etc.) afin de donner accès à ses dépôts privés depuis un workspace devpod. La clé est générée lors de la création du workspace, affichée à la demande via un bouton sur la carte workspace.

## Périmètre

- Génération d'une paire Ed25519 par workspace, opt-in
- Affichage de la clé publique (bouton sur WorkspaceCard → dialog)
- Pas d'injection de la clé privée dans le container (itération future)

---

## Stockage

**Chemin :**
```
/data/users/{login}/keys/workspaces/{workspace_name}/id_ed25519      (600)
/data/users/{login}/keys/workspaces/{workspace_name}/id_ed25519.pub  (644)
```

Le répertoire parent `keys/workspaces/` existe déjà via `ensure_user_dir()`. Le sous-dossier `{workspace_name}/` est créé lors de la génération.

**Génération :** `cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey` (disponible via authlib — aucune nouvelle dépendance). Écriture atomique (`tempfile` + `os.replace`). Idempotent : si `id_ed25519.pub` existe déjà, retourne son contenu sans régénérer.

---

## Backend

### Nouveau module `portal/ssh_keys.py`

```python
def ensure_workspace_ssh_key(login: str, workspace_name: str) -> str:
    """Génère la paire ed25519 si absente. Retourne la clé publique (str)."""
```

Appelée via `asyncio.to_thread(ensure_workspace_ssh_key, login, name)` dans `DevPodService.up()` quand `generate_ssh_key=True`.

### Modifications `config/models.py`

`WorkspaceSpec` reçoit un nouveau champ :
```python
ssh_key: bool = False
```
Persiste le choix de l'utilisateur ; pilote l'affichage du bouton côté frontend sans requête fichier.

### Modifications `workspace_ops.py`

`UpRequest` reçoit :
```python
generate_ssh_key: bool = False
```

Si `True`, la clé est générée (idempotent) avant le lancement devpod. Le `WorkspaceSpec` persiste `ssh_key=True` via `save_user`.

Nouveau endpoint :
```
GET /workspaces/{name}/ssh-key
→ 200  { "public_key": "ssh-ed25519 AAAA..." }
→ 404  si la clé n'existe pas
```
Lecture seule — aucune génération à ce stade.

### Modifications `devpod/service.py`

`DevPodService.up()` reçoit `generate_ssh_key: bool = False`. Si `True` :
```python
await asyncio.to_thread(ensure_workspace_ssh_key, login, ws_spec.name)
```
Appelé avant `ensure_provider` (la clé doit exister avant tout).

---

## Frontend

### `useWorkspaceSshKey(name: string)`
Hook TanStack Query sur `GET /workspaces/{name}/ssh-key`. Activé uniquement si `enabled` est `true` (passé par le composant parent au moment où la dialog s'ouvre).

### `SshKeyDialog.tsx`
Dialog shadcn/ui :
- Textarea readonly avec la clé publique
- Bouton "Copier" (`navigator.clipboard.writeText`)
- Instruction courte : "Collez cette clé dans GitHub → Settings → Deploy keys (ou GitLab → Dépôt → Paramètres → Clés de déploiement)"

### `WorkspaceCard.tsx`
Si `spec.ssh_key === true`, affiche un bouton icône `<Key />` (lucide-react). Au clic, état local `open = true` → monte `SshKeyDialog` et active le hook.

### `WorkspaceCreate.tsx`
Checkbox ou Switch "Générer une clé SSH pour ce workspace". Valeur passée à `useWorkspaceOps.createWorkspace` → champ `generate_ssh_key`.

### `useWorkspaceOps.ts`
`UpRequest` enrichi avec `generate_ssh_key?: boolean`.

---

## Flux complet

```
[WorkspaceCreate] toggle ssh_key=true
        ↓
POST /workspaces/{name}/up  { generate_ssh_key: true }
        ↓
workspace_ops.py → DevPodService.up(generate_ssh_key=True)
        ↓
asyncio.to_thread(ensure_workspace_ssh_key, login, name)
  → génère id_ed25519 + id_ed25519.pub (si absent)
        ↓
devpod up ...   (la clé est prête mais pas montée dans le container)
        ↓
save_user: WorkspaceSpec.ssh_key = True

[WorkspaceList] WorkspaceCard (spec.ssh_key=true)
        ↓  clic bouton Key
SshKeyDialog ouvre → GET /workspaces/{name}/ssh-key
        ↓
200 { public_key: "ssh-ed25519 ..." }
        ↓
Textarea + bouton Copier
```

---

## Sécurité

- La clé privée n'est jamais exposée via l'API ni loguée
- `safe_user_path` garantit l'isolation entre utilisateurs
- Le `workspace_name` est validé par `_validate_name` (regex stricte) avant tout accès fichier
- Perms 600 sur `id_ed25519`, 644 sur `id_ed25519.pub`

---

## Tests obligatoires

- `ensure_workspace_ssh_key` : génère une paire valide, idempotent au second appel
- `GET /workspaces/{name}/ssh-key` : 200 si clé présente, 404 sinon, 403 si autre utilisateur
- `POST /workspaces/{name}/up` avec `generate_ssh_key=true` : fichier créé sur disque
- Frontend : `SshKeyDialog` affiche la clé et le bouton copier (Vitest + RTL)
