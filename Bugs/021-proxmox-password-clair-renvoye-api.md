# 021 — Mot de passe Proxmox stocké en clair et renvoyé dans les réponses API

- **Sévérité** : mineur (admin-only ; secret passif inutilisé par l'auth SSH)
- **Sous-système** : proxmox / config
- **Fichiers** : `config/models.py:199` (`password: str = ""`), `db/tables.py:108`, `db/global_config.py:187,311`, `routes/proxmox.py:403,447,488`
- **Statut** : corrigé — champ supprimé entièrement (confirmé inutilisé : aucun consommateur en
  dehors du stockage/echo, l'auth SSH réelle passe par clé `BatchMode=yes`). Retiré de
  `Hypervisor` (config/models.py), de la table `hypervisors` (migration alembic `046`), de
  `_hyp_row_to_dict`/`_hyp_to_row` (db/global_config.py), des paramètres `Form` et de la
  construction `Hypervisor(...)` dans `add_hypervisor`/`update_hypervisor` (routes/proxmox.py).
  Frontend : champ retiré du formulaire d'ajout/édition (`AdminProxmox.tsx`,
  `useAdminProxmox.ts`), clé i18n `admin.form.proxmoxPassword` orpheline supprimée (en/fr).
  Vérifié : suite backend complète (873 passés / 171 échecs pré-existants, identique avant/après
  via `git stash` — aucune régression), suite frontend complète verte.

**Symptôme** : le champ `password` de `Hypervisor` est persisté en clair (colonne `Text`) et **renvoyé**
dans `GET/POST/PUT /hypervisors` via `node.model_dump(mode="json")`. Contredit la règle « aucun secret
en clair ». L'auth SSH réelle est par clé (`BatchMode=yes`), donc ce champ est passif.

**Correction** : typer `SecretStr` + `exclude=True` du dump de sortie, ou le supprimer s'il est inutilisé.
