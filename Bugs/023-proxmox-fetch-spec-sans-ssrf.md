# 023 — Fetch de spec proxmox sans contrôle SSRF, exécutée ensuite en SSH

- **Sévérité** : mineur (URL admin-fournie ; surface limitée mais RCE possible sur l'hyperviseur)
- **Sous-système** : proxmox
- **Fichier** : `routes/proxmox.py:237-239, 578, 716-720`
- **Statut** : ouvert

**Symptôme** : `add_script`/`destroy_script` sont des URLs admin fetchées avec `follow_redirects=True`
et **sans** `_check_ssrf` (contrairement à `compose_sources`). Le JSON renvoyé (`commands`) est ensuite
exécuté via `_ssh_stream` sur l'hyperviseur. Un hôte de scripts compromis ⇒ RCE sur l'hyperviseur ;
`follow_redirects=True` permet une redirection vers une cible interne.

**Correction** : appliquer `_check_ssrf` + `follow_redirects=False` sur ces fetchs, ou restreindre à une
allowlist d'hôtes.
