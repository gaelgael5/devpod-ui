# 024 — Substitution shell non quotée dans les scripts proxmox/test-vm + re-substitution du token

- **Sévérité** : mineur (pas d'injection exploitable aujourd'hui ; risque latent + exfil token)
- **Sous-système** : proxmox / test_vm
- **Fichier** : `routes/proxmox.py:206-209` (`_substitute`), usages `667, 735`, `test_vm.py:295`
- **Statut** : corrigé — `_substitute` remplace désormais les placeholders `{KEY}` en une seule
  passe via `re.sub` (le texte produit par une substitution n'est jamais réexaminé, contrairement
  à l'enchaînement de `str.replace` précédent) et quote chaque valeur avec `shlex.quote` avant
  injection dans les commandes `bash -s`. Tests ajoutés (`tests/routes/test_proxmox_substitute.py`,
  rouge→vert vérifié par `git stash`) : substitution basique, placeholder inconnu laissé intact,
  valeur avec métacaractères shell quotée, et le cas d'exfiltration (une valeur d'arg contenant
  littéralement `{PORTAL_TOKEN}` ne se fait plus remplacer par le vrai token).

**Symptôme** : `_substitute` fait un `str.replace("{k}", v)` brut des `args` dans des templates de
commandes exécutés par `bash -s`, sans `shlex.quote`. Côté `create_test_vm` (`require_user`),
l'utilisateur ne contrôle que `vmid` (validé `^[0-9]{1,9}$`) → pas d'injection **aujourd'hui**. Risque
latent : toute future valeur semi-fiable dans `args` deviendrait une injection shell.

**Effet de bord vérifiable** : une valeur d'arg contenant littéralement `{PORTAL_TOKEN}` peut se faire
re-substituer par le token réel (l'itération `args.items()` traite `PORTAL_TOKEN` après les args
utilisateur) → exfiltration du `portal_api_key`.

**Correction** : quoter les valeurs à l'injection (ou passer les args comme variables d'environnement du
process ssh) ; **ne jamais re-substituer une valeur déjà substituée** (substitution en une seule passe).
