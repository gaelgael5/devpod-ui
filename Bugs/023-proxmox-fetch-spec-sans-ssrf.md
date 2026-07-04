# 023 — Fetch de spec proxmox sans contrôle SSRF, exécutée ensuite en SSH

- **Sévérité** : mineur (URL admin-fournie ; surface limitée mais RCE possible sur l'hyperviseur)
- **Sous-système** : proxmox
- **Fichier** : `routes/proxmox.py:237-239, 578, 716-720`
- **Statut** : corrigé — les 3 sites (`_run_destroy_script`, `_fetch_spec_for_type`,
  `execute_hypervisor_destroy_script`) appellent désormais `_check_ssrf` (réutilisé depuis
  `recipe_sources`, identique à `compose_sources`) avant tout `httpx.AsyncClient.get`, et
  `follow_redirects` passe de `True` à `False`. Tests ajoutés
  (`tests/routes/test_proxmox_ssrf.py`) : URL vers `169.254.169.254` (cible SSRF metadata cloud
  classique) rejetée (422) sans jamais instancier `httpx.AsyncClient` ni appeler `_ssh_stream` —
  rouge→vert vérifié par `git stash`.

**Symptôme** : `add_script`/`destroy_script` sont des URLs admin fetchées avec `follow_redirects=True`
et **sans** `_check_ssrf` (contrairement à `compose_sources`). Le JSON renvoyé (`commands`) est ensuite
exécuté via `_ssh_stream` sur l'hyperviseur. Un hôte de scripts compromis ⇒ RCE sur l'hyperviseur ;
`follow_redirects=True` permet une redirection vers une cible interne.

**Correction** : appliquer `_check_ssrf` + `follow_redirects=False` sur ces fetchs, ou restreindre à une
allowlist d'hôtes.
