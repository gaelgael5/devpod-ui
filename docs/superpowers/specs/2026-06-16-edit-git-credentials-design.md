# Design — Édition de credentials git

Date : 2026-06-16

## Contexte

La page `GitCredentialManager` permet actuellement de créer et supprimer des credentials git (PAT ou SSH). Il n'est pas possible de modifier un credential existant. L'utilisateur doit supprimer puis recréer, ce qui casse les références dans les workspaces existants.

## Objectif

Permettre l'édition complète d'un credential : nom, host, type (token ↔ SSH), username, secret.

## Décisions de design

- **Tous les champs sont éditables**, y compris le nom (qui est l'identifiant — un rename déclenche une cascade sur les workspaces).
- **UI** : bouton crayon sur chaque ligne → dialog d'édition (cohérent avec la confirmation de suppression existante).
- **Secrets** : affichés masqués (`"••••••••"`) à l'ouverture ; si l'utilisateur ne touche pas le champ, l'ancien secret est conservé via le sentinel `"__UNCHANGED__"`.
- **API** : PATCH partiel (seuls les champs modifiés transitent).

---

## Backend

### Endpoint

```
PATCH /me/git-credentials/{name}
```

### Corps — modèle `_GitCredentialUpdate` (tous optionnels)

| Champ        | Type                    | Notes |
|--------------|-------------------------|-------|
| `new_name`   | `str \| None`           | validé regex + unicité |
| `host`       | `str \| None`           | normalisé (lowercase, strip scheme) |
| `kind`       | `"token" \| "ssh" \| None` | changement de type possible |
| `username`   | `str \| None`           | |
| `token`      | `str \| None`           | `"__UNCHANGED__"` = conserver |
| `private_key`| `str \| None`           | `"__UNCHANGED__"` = conserver |

### Logique (séquentielle)

1. Trouver le credential par `name` → 404 si absent
2. Si `new_name` fourni : valider regex `_CRED_NAME_RE` + vérifier unicité → 409 si doublon
3. Résoudre le `kind` effectif (nouveau ou ancien)
4. Transition `token → ssh` : `private_key` requis et non-sentinel ; créer fichier clé 0o600 ; `key_path` mis à jour ; `token` effacé
5. Transition `ssh → token` : `token` requis et non-sentinel ; supprimer ancien fichier clé ; `key_path` vidé
6. Même `kind`, secret non-sentinel : mettre à jour fichier clé ou token en place
7. Appliquer `host`, `username`
8. Si `new_name` : cascade — parcourir `cfg.workspaces`, remplacer `ws.git_credential` et chaque `source.git_credential` dans `ws.extra_sources`
9. `save_user()` atomique
10. Retourner `{"name": effective_name, "host": effective_host, "kind": effective_kind}`

### Réponse

- `200` : `{name, host, kind}` (même shape que POST)
- `404` : credential introuvable
- `409` : `new_name` déjà utilisé
- `422` : validation échouée (nom invalide, secret manquant lors d'un changement de kind)

---

## Frontend

### Hook `useUpdateGitCredential` (`useGitCredentials.ts`)

```ts
mutationFn: ({ name, payload }) =>
  apiFetchJson<GitCredentialSummary>(
    `/me/git-credentials/${encodeURIComponent(name)}`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
onSuccess: () => qc.invalidateQueries({ queryKey: QK })
```

Payload type `UpdateCredentialPayload` : mêmes champs que `_GitCredentialUpdate`.

### `GitCredentialManager.tsx` — état ajouté

```ts
const [toEdit, setToEdit] = useState<GitCredentialSummary | null>(null)
```

### Liste — bouton crayon

Icône `Pencil` ajoutée avant `Trash2` sur chaque ligne. Click → `setToEdit(c)`.

### Dialog d'édition

Ouverture : `open={!!toEdit}`

Formulaire pré-rempli depuis `toEdit` :

| Champ | Valeur initiale | Comportement |
|-------|----------------|--------------|
| Nom | `toEdit.name` | texte libre |
| Host | valeur connue ou `__other__` | Select existant |
| Kind | `toEdit.kind` | Select ; changement → reset secret + `secretTouched=true` |
| Token / Clé SSH | `"••••••••"` (valeur affichée) | focus → vide + `secretTouched=true` ; blur sans saisie → `"••••••••"` revient |

À la soumission : si `secretTouched === false` → champ secret = `"__UNCHANGED__"` dans le payload.

Boutons : **Annuler** / **Enregistrer** (disabled pendant mutation, affiche `…`). Erreur API affichée en rouge sous le formulaire.

---

## Tests backend (obligatoires)

- PATCH nom seul → cascade workspaces mise à jour
- PATCH secret token → ancien token remplacé
- PATCH kind token→ssh avec clé valide → fichier clé créé, token effacé
- PATCH kind ssh→token avec token valide → fichier clé supprimé
- PATCH secret `"__UNCHANGED__"` → secret inchangé en base
- PATCH `new_name` déjà pris → 409
- PATCH credential inexistant → 404
