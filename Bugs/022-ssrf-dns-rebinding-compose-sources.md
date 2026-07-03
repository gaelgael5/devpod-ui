# 022 — SSRF résiduelle : DNS rebinding (TOCTOU) entre le check et le fetch

- **Sévérité** : mineur (admin-only ; nécessite DNS contrôlé par l'attaquant)
- **Sous-système** : compose_sources
- **Fichier** : `routes/compose_sources.py:37-76` (`_check_ssrf` puis `client.get(url)`)
- **Statut** : ouvert

**Symptôme** : `_check_ssrf` résout le hostname et rejette les IP internes, puis `client.get(url)`
**re-résout** le DNS indépendamment. Un attaquant contrôlant le DNS (TTL 0) fait pointer le premier
lookup vers une IP publique et le second vers `169.254.169.254` / `127.0.0.1`. `follow_redirects=False`
ferme la voie des redirections, pas le rebinding.

**Correction** : résoudre une fois, valider l'IP, puis forcer httpx à se connecter **à cette IP validée**
(transport/resolver pinné, ou connexion par IP + header `Host`).
