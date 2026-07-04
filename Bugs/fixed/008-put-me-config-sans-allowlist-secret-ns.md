# 008 — `PUT /me/config` sans allowlist : `secret_ns` et `version` réécrivables par l'utilisateur

- **Sévérité** : majeur (isolation `secret_ns` / cohérence de version)
- **Sous-système** : config / routes
- **Fichier** : `backend/src/portal/routes/me.py:93-106` (`put_config`)
- **Statut** : corrigé — `_ALLOWED_CONFIG_UPDATE_FIELDS = {"defaults", "culture"}`, rejet 422 explicite avant tout accès à `load_user`/DB. Test de régression réel (sans DB requise, la validation précède `load_user`) : `test_put_me_config_rejects_secret_ns_rewrite`.

**Note** : les tests `test_get_me_config_returns_user_config` / `test_put_me_config_updates_defaults` / `test_put_me_config_rejects_unknown_field` déjà présents échouent dans ce devpod faute de `DATABASE_URL` (dette pré-existante, sans rapport avec ce bug — confirmé par git stash sur le fichier avant correction, même échec).

## Symptôme

Un utilisateur peut réécrire son propre `secret_ns` (GUID d'isolation des secrets) via l'endpoint de
mise à jour de config, rendant ses secrets stockés orphelins ou ciblant potentiellement un autre
namespace — et peut modifier `version`.

## Cause racine

```python
cfg = await load_user(user.login)
merged = cfg.model_dump(mode="json")
merged.update(updates)                    # updates = dict[str, object] brut du client
new_cfg = UserConfig.model_validate(merged)
await save_user(user.login, new_cfg)
```

`updates` est fusionné sans liste blanche. Grâce à `extra="forbid"`, un champ *inconnu* serait
rejeté — mais `secret_ns`, `version`, `workspaces`, `git_credentials` sont des champs **valides** de
`UserConfig`, donc ils passent. Envoyer `{"secret_ns": "<uuid valide>"}` réécrit le namespace ; en
cas de collision avec le `secret_ns` unique d'un autre user, l'`IntegrityError` remonte en 500 non
géré.

## Piste de correction

N'accepter qu'un sous-ensemble explicite de clés modifiables par l'utilisateur (`defaults`,
`culture`, …). Rejeter ou ignorer `secret_ns`, `version`, `workspaces`, `git_credentials` sur cette
route (elles ont leurs propres endpoints dédiés).

## Vérifié

Confirmé par lecture : `merged.update(updates)` sur un `dict[str, object]` non filtré, puis
`model_validate`. `secret_ns` et `version` sont bien des champs de `UserConfig`.
