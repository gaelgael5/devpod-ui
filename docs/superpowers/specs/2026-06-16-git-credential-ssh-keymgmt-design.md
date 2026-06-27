# Design — Gestion des clés SSH pour credentials git

Date : 2026-06-16

## Contexte

Le formulaire d'ajout de credential git (type SSH) permet actuellement de coller manuellement une clé privée dans un Textarea. Trois lacunes :
1. Pas de bouton pour charger la clé depuis un fichier
2. La clé publique n'est ni stockée ni consultable (impossible de la copier dans GitHub/GitLab après coup)
3. Pas de génération de paire de clés intégrée

## Objectif

Pour les credentials SSH :
- Permettre le **chargement de la clé privée depuis un fichier** (ajout et édition)
- Stocker et exposer la **clé publique** correspondante, consultable à tout moment
- Permettre la **génération d'une paire Ed25519 côté serveur** : crée le credential et affiche la clé publique en une seule action

## Décisions de design

- Génération **côté serveur** uniquement (option A choisie) : la clé privée ne transite pas par le navigateur, cohérent avec le pattern workspace SSH.
- Génération = **création immédiate** du credential (option A) : un seul clic "Générer une clé" soumet le formulaire avec `generate_key: true` et affiche la clé publique dans un dialog.
- La clé publique est stockée dans `id_ed25519.pub` à côté de `id_ed25519` (pattern workspace).
- Pour les credentials existants sans `.pub` : dérivation à la volée depuis la clé privée (via `cryptography`), puis sauvegarde du `.pub` pour les appels suivants.
- Pas de génération dans le formulaire **d'édition** (création d'un nouveau credential si besoin de régénérer).

---

## Backend

### Nouvelles fonctions dans `backend/src/portal/ssh_keys.py`

#### `generate_git_credential_ssh_key(login, cred_name) -> tuple[str, str]`

Génère une paire Ed25519 fraîche pour un credential git.

```
répertoire : safe_user_path(login, "keys", "git", cred_name)
fichiers   : id_ed25519 (0o600) + id_ed25519.pub (0o644)
retourne   : (key_path: str, public_key: str)
```

Commentaire de la clé publique : `devpod-git:{login}/{cred_name}`

#### `derive_git_credential_public_key(key_path: str) -> str`

Charge `id_ed25519` via `Ed25519PrivateKey` (lib `cryptography`), extrait la clé publique OpenSSH, écrit `id_ed25519.pub` à côté (0o644), retourne le texte.

Utilisée pour :
- Les credentials SSH uploadés (à la création ou à l'édition)
- Les anciens credentials sans `.pub` (migration à la demande)

### Changements dans `backend/src/portal/routes/me.py`

#### Modèle `_GitCredentialCreate`

Ajouter :
```python
generate_key: bool = False
```

#### `POST /me/git-credentials` — `add_git_credential`

| Cas | Comportement |
|-----|-------------|
| `generate_key=True`, `kind="ssh"` | Appelle `generate_git_credential_ssh_key` ; ignore `private_key` ; retourne `{name, host, kind, public_key}` |
| `generate_key=False`, `kind="ssh"`, `private_key` fourni | Comportement existant + appelle `derive_git_credential_public_key` pour écrire `.pub` |
| `kind="token"` | Inchangé |

Validation : `generate_key=True` avec `kind="token"` → 422.

#### `PATCH /me/git-credentials/{name}` — `patch_git_credential`

Quand une nouvelle `private_key` est fournie (non-sentinel), appeler `derive_git_credential_public_key` pour réécrire `.pub`.

#### `GET /me/git-credentials/{name}/public-key` — nouveau endpoint

```
200 : {"public_key": "ssh-ed25519 AAAA... devpod-git:login/name"}
404 : credential introuvable, ou kind != "ssh", ou aucun fichier clé
```

Logique :
1. Charger le credential ; 404 si absent ou `kind != "ssh"`
2. Lire `{key_path_dir}/id_ed25519.pub` si présent → retourner
3. Sinon appeler `derive_git_credential_public_key(cred.key_path)` → retourner
4. Si `key_path` vide → 404

### Réponse enrichie pour la génération

`add_git_credential` avec `generate_key=True` retourne `{name, host, kind, public_key: "ssh-ed25519 …"}`.
Les autres cas retournent `{name, host, kind}` (inchangé).

---

## Frontend

### `frontend/src/features/git-credentials/useGitCredentials.ts`

**`GitCredentialSummary`** : ajouter `public_key?: string` (présent uniquement dans la réponse de génération).

**`AddCredentialPayload`** : ajouter `generate_key?: boolean`.

**Nouveau hook `useGitCredentialPublicKey`** :

```ts
function useGitCredentialPublicKey(name: string, enabled: boolean) {
  return useQuery<{ public_key: string }>({
    queryKey: ['git-credential-public-key', name],
    queryFn: () => apiFetchJson(`/me/git-credentials/${encodeURIComponent(name)}/public-key`),
    enabled,
    retry: false,
  })
}
```

### Nouveau composant `GitCredentialPublicKeyDialog.tsx`

Props : `open: boolean`, `publicKey: string`, `onClose: () => void`

Contenu :
- Titre : `gitCredentials.publicKeyDialogTitle`
- Hint : `gitCredentials.publicKeyHint` ("Copiez cette clé dans GitHub → Settings → SSH keys ou GitLab → Dépôt → Clés de déploiement.")
- Textarea read-only avec la clé
- Bouton **Copier** + feedback **Copié !** (2 s)

Utilisé dans deux contextes :
1. Après génération (public_key dans la réponse du POST)
2. Au clic sur le bouton clé publique de la liste

### `GitCredentialManager.tsx` — changements

#### État ajouté

```ts
const [publicKeyDialog, setPublicKeyDialog] = useState<{ name: string; key: string } | null>(null)
const [publicKeyFetchName, setPublicKeyFetchName] = useState<string | null>(null)
```

#### Formulaire d'ajout — mode SSH

**Bouton "Charger depuis un fichier"** sous le Textarea :

```tsx
<input
  type="file"
  accept=".pem,.key,.pub"
  id="cred-key-file"
  className="hidden"
  onChange={e => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => setForm(f => ({ ...f, privateKey: (ev.target?.result as string) ?? '' }))
    reader.readAsText(file)
    e.target.value = ''
  }}
/>
<Button type="button" variant="outline" size="sm" asChild>
  <label htmlFor="cred-key-file" className="cursor-pointer">
    {t('gitCredentials.loadKeyFile')}
  </label>
</Button>
```

**Bouton "Générer une clé"** à côté du bouton "Enregistrer" :

- Visible uniquement quand `form.kind === 'ssh'`
- Disabled si `form.name.trim()` ou `effectiveHost` est vide
- Au clic : valide name + host, soumet avec `{..., generate_key: true, private_key: ''}`
- `onSuccess` : si `data.public_key` présent → `setPublicKeyDialog({ name: data.name, key: data.public_key })` + `resetForm()`

```tsx
<Button
  type="button"
  variant="secondary"
  size="sm"
  disabled={!form.name.trim() || !effectiveHost || addMutation.isPending}
  onClick={handleGenerate}
>
  {addMutation.isPending ? '…' : t('gitCredentials.generateKey')}
</Button>
```

#### Liste des credentials — bouton clé publique

Sur chaque ligne `kind === 'ssh'` : icône `KeyRound` avant le `Pencil` :

```tsx
{c.kind === 'ssh' && (
  <Button
    size="icon"
    variant="ghost"
    className="h-8 w-8"
    onClick={() => setPublicKeyFetchName(c.name)}
    aria-label={t('gitCredentials.viewPublicKey')}
  >
    <KeyRound className="h-4 w-4" />
  </Button>
)}
```

Le hook `useGitCredentialPublicKey(publicKeyFetchName ?? '', !!publicKeyFetchName)` est interrogé dès que `publicKeyFetchName` est défini. Sur `isSuccess` → `setPublicKeyDialog(...)` + `setPublicKeyFetchName(null)`.

#### Formulaire d'édition — mode SSH

Ajouter uniquement le **bouton "Charger depuis un fichier"** sous le Textarea d'édition (même logique que l'ajout, injecte dans `editForm.privateKey` + `keyTouched=true`).

#### Dialog clé publique

```tsx
<GitCredentialPublicKeyDialog
  open={!!publicKeyDialog}
  publicKey={publicKeyDialog?.key ?? ''}
  onClose={() => setPublicKeyDialog(null)}
/>
```

### i18n — nouvelles clés

| Clé | FR | EN |
|-----|----|----|
| `gitCredentials.loadKeyFile` | "Charger depuis un fichier" | "Load from file" |
| `gitCredentials.generateKey` | "Générer une clé" | "Generate key" |
| `gitCredentials.viewPublicKey` | "Voir la clé publique" | "View public key" |
| `gitCredentials.publicKeyDialogTitle` | "Clé publique SSH" | "SSH Public Key" |
| `gitCredentials.publicKeyHint` | "Copiez cette clé dans GitHub → Settings → SSH keys ou GitLab → Dépôt → Paramètres → Clés de déploiement." | "Paste this key into GitHub → Settings → SSH keys or GitLab → Repository → Settings → Deploy Keys." |
| `gitCredentials.publicKeyCopy` | "Copier" | "Copy" |
| `gitCredentials.publicKeyCopied` | "Copié !" | "Copied!" |
| `gitCredentials.errors.publicKey` | "Impossible de récupérer la clé publique." | "Could not retrieve public key." |

---

## Tests backend (obligatoires)

- `POST /me/git-credentials` avec `generate_key=True` → credential créé, fichier `id_ed25519` + `id_ed25519.pub` présents, réponse contient `public_key`
- `POST /me/git-credentials` avec clé privée uploadée → `id_ed25519.pub` dérivé et présent
- `GET /me/git-credentials/{name}/public-key` sur credential généré → retourne la clé publique
- `GET /me/git-credentials/{name}/public-key` sur credential uploadé (sans `.pub`) → dérive à la volée, retourne la clé publique
- `GET /me/git-credentials/{name}/public-key` sur credential token → 404
- `PATCH /me/git-credentials/{name}` avec nouvelle `private_key` → `.pub` mis à jour
- `POST` avec `generate_key=True` et `kind="token"` → 422
