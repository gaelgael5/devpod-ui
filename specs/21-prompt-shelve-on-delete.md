# Chantier — Shelve du travail en cours à la suppression d'un workspace

> Dépôt **devpod-ui**. Sécurise le seul moment où du travail peut être perdu : la **suppression**.
> À la suppression d'un workspace dont le dépôt a du travail en attente, on pousse ce travail sur une
> branche `recovery-JJ-MM-AA-HH-MM` du remote **avant** de supprimer. Récupération : la branche est
> sur le remote, l'utilisateur la reprend et la **nettoie lui-même**.
> Hors périmètre : bind-mount / persistance disque, réintégration automatique, UI de récupération.

## 0. Préalables

1. Lis `CLAUDE.md`, `LESSONS.md`. **Mime les patterns existants** :
   - `devpod/service.py` : `up` / `stop` / `delete` (on se greffe sur `delete`) ;
   - `devpod/git.py` : exécution git + protection SSRF + injection de credential ;
   - `routes/workspace_ops.py` : endpoint de suppression (valeur de retour à enrichir) ;
   - frontend `@/features/workspaces` : dialogue de confirmation, toasts, mutations React Query.
2. Branche `dev`. Commits conventionnels **FR**. Aucun fichier > 300 lignes. **Pas de DB.**

## 1. Comportement attendu

DevPod conserve déjà le workspace entre `stop` et `up` : le travail n'est en danger qu'au `delete`.
Ce chantier ne couvre que ce moment.

À la suppression :
1. Détecter si le dépôt a du travail **en attente** = working tree sale **ou** fichiers non suivis
   non ignorés **ou** commits non poussés.
2. Si **rien** en attente → suppression directe (comportement actuel).
3. Si **en attente** → créer la branche `recovery-JJ-MM-AA-HH-MM`, y committer le travail, la
   **pousser sur le remote** (push obligatoire), **puis seulement** supprimer le workspace.
4. Si le **push échoue** (credential en lecture seule, réseau, protection de branche) → **on ne
   supprime pas**. On remonte une erreur claire ; l'utilisateur résout et relance. Jamais de perte.

La récupération ne demande aucune action du portail : la branche vit sur le remote, présente au
prochain clone. **L'utilisateur la récupère et la supprime quand il a fini** (le portail n'y touche
jamais).

## 2. Backend

Le travail tourne **dans le conteneur du workspace** (c'est là qu'est l'arbre de travail), via
`devpod ssh <ws_id> --command "<script>"`. Le credential git est déjà configuré dans le conteneur
par le clone initial, donc le `push` réutilise ce credential — rien à réinjecter depuis le portail.

> À vérifier sur la version installée (`devpod ssh --help`) : `devpod ssh` ouvre bien dans le dossier
> projet. Sinon, préfixer le script d'un `cd` explicite.

### `devpod/shelve.py` — script exécuté dans le conteneur

```bash
set -eu
# 1 = sale, 0 = propre ; on shelve si sale OU commits non poussés
dirty=0
[ -n "$(git status --porcelain)" ] && dirty=1
upstream="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
ahead=0
[ -n "$upstream" ] && ahead="$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)"
if [ "$dirty" -eq 0 ] && [ "$ahead" -eq 0 ]; then
  echo "NOTHING_TO_SHELVE"; exit 0
fi

br="recovery-$(date +%d-%m-%y-%H-%M)"
# collision (même minute) : suffixe -2, -3, …
i=1; base="$br"
while git ls-remote --exit-code --heads origin "$br" >/dev/null 2>&1; do
  i=$((i+1)); br="$base-$i"
done

git checkout -b "$br"
git add -A                      # respecte .gitignore — JAMAIS -f (pas de secret ignoré poussé)
git commit -m "WIP shelve $br" || true   # peut être vide si seulement des commits non poussés
git push -u origin "$br"
echo "SHELVED:$br"
```

### Greffe sur `DevPodService.delete`

```python
async def delete(self, login: str, ws_id: str) -> dict[str, Any]:
    branch = await self._shelve_if_pending(login, ws_id)  # None | str
    cmd = [*self._devpod_bin, "delete", ws_id, "--force"]
    rc, _ = await self._run(cmd, env=self._minimal_env(login),
                            log_path=self._log_path(login, f"{ws_id}-delete"))
    if rc != 0:
        _log.warning("workspace_delete_failed", ws_id=ws_id, returncode=rc)
    _log.info("workspace_deleted", ws_id=ws_id, login=login, recovery_branch=branch)
    return {"deleted": True, "recovery_branch": branch}
```

`_shelve_if_pending` lance `devpod ssh <ws_id> --command <script>` :
- sortie `NOTHING_TO_SHELVE` → retourne `None` ;
- sortie `SHELVED:<br>` → retourne `<br>` ;
- **échec du push** (rc ≠ 0) → `HTTPException(409, "Shelve impossible (push échoué), suppression
  annulée : <stderr>")` **sans** appeler `devpod delete`.

Ne jamais logguer le contenu des fichiers ni le credential.

## 3. Frontend (`@/features/workspaces`)

- Dialogue de confirmation de suppression : si le workspace est `running`, prévenir qu'un éventuel
  travail en cours sera poussé sur une branche `recovery-…` avant suppression.
- Après succès, toast avec le nom de branche renvoyé (`recovery_branch`) s'il est non nul :
  « Travail sauvegardé sur `origin/<branch>` ». i18n `fr.json` / `en.json`, jamais de string brute.
- Sur `409` (push échoué) : toast d'erreur reprenant le détail, le workspace n'est pas supprimé.

## 4. Tests

- **shelve** sur dépôt fixture (working tree sale + fichier non suivi + commit non poussé) : la
  branche poussée contient tout ; les fichiers ignorés (`node_modules`, `.env`) sont **absents**.
- dépôt **propre** → `NOTHING_TO_SHELVE`, suppression directe, `recovery_branch == None`.
- **push KO** simulé (credential read-only) → `409`, le workspace **n'est pas** supprimé.
- nom de branche au format `JJ-MM-AA-HH-MM` ; collision même minute → suffixe `-2`.
```
```
