# 021 — Mot de passe Proxmox stocké en clair et renvoyé dans les réponses API

- **Sévérité** : mineur (admin-only ; secret passif inutilisé par l'auth SSH)
- **Sous-système** : proxmox / config
- **Fichiers** : `config/models.py:199` (`password: str = ""`), `db/tables.py:108`, `db/global_config.py:187,311`, `routes/proxmox.py:403,447,488`
- **Statut** : ouvert

**Symptôme** : le champ `password` de `Hypervisor` est persisté en clair (colonne `Text`) et **renvoyé**
dans `GET/POST/PUT /hypervisors` via `node.model_dump(mode="json")`. Contredit la règle « aucun secret
en clair ». L'auth SSH réelle est par clé (`BatchMode=yes`), donc ce champ est passif.

**Correction** : typer `SecretStr` + `exclude=True` du dump de sortie, ou le supprimer s'il est inutilisé.
