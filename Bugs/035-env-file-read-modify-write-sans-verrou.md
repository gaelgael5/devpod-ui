# 035 — Écriture `.env` en read-modify-write sans verrou

- **Sévérité** : mineur (admin-only, rare ; écriture atomique et perms OK par ailleurs)
- **Sous-système** : config
- **Fichier** : `config/env_file.py:10-45` (appelé par `routes/admin.py:307`)
- **Statut** : ouvert

**Symptôme** : la fonction est correctement atomique (`mkstemp` même dossier + `chmod 600` + `os.replace`)
— aucun défaut de ce côté. Mais elle lit puis réécrit le fichier entier ; deux mises à jour concurrentes
de clés distinctes peuvent se perdre mutuellement (dernier `os.replace` gagne).

**Correction** : sérialiser les mises à jour `.env` (verrou) si plusieurs chemins d'admin peuvent y
écrire.
