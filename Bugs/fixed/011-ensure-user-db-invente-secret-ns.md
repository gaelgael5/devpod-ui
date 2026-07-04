# 011 — `ensure_user_db` fabrique un `secret_ns` aléatoire en secours → secrets orphelins

- **Sévérité** : majeur
- **Sous-système** : db / secrets
- **Fichier** : `backend/src/portal/db/user_config.py:44-54`
- **Statut** : ✅ corrigé

## Symptôme

Si le `config.yaml` d'un utilisateur est absent ou illisible au moment où `ensure_user_db` s'exécute
(garde-FK après un restart/wipe DB alors que la session survit), la fonction insère une ligne `users`
avec un `secret_ns` **inventé** (`uuid.uuid4()`), différent du namespace réel de l'utilisateur. Tous
les secrets rangés sous l'ancien `secret_ns` deviennent inaccessibles, et un futur `save_user`
réécrit ce GUID erroné.

## Cause racine

```python
except OSError:
    secret_ns_str = str(uuid.uuid4())     # namespace inventé
```

Provisioning « best effort » qui préfère générer un GUID plutôt que d'échouer quand le `secret_ns`
d'origine est introuvable. Incohérence de source de vérité en prime : ici la source est le YAML,
alors que le reste du sous-système est passé sur la DB.

## Piste de correction

Si le `secret_ns` d'origine est introuvable, **échouer explicitement** (forcer un re-login /
re-provisioning complet) plutôt que d'inventer un namespace. Ou dériver `secret_ns` d'une source
unique et fiable (la DB, pas le YAML).

## Correction (e928c02)

UserNotProvisionedError levée si config.yaml absent/illisible/sans secret_ns — plus jamais de GUID inventé. /vault/pin/setup traduit en 401 → re-login → re-provisioning propre par provision_user (seul chemin légitime de création du namespace).
