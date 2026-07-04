# 029 — MCP : `BearerGate` ne filtre que les scopes `http`

- **Sévérité** : mineur (non exploitable en l'état : sous-app HTTP uniquement) — durcissement
- **Sous-système** : mcp / asgi_auth
- **Fichier** : `mcp/asgi_auth.py:22-24`
- **Statut** : corrigé — `BearerGate` distingue désormais explicitement 3 cas : `lifespan` passe
  sans auth (nécessaire au démarrage de l'app), `http` suit le chemin existant (vérification
  Bearer), et tout le reste (websocket compris) est fail-closed via `_reject_non_http` (ferme la
  websocket avec le code `4401` après avoir consommé `websocket.connect`, plutôt que de laisser
  passer). Tests ajoutés : scope websocket rejeté sans jamais atteindre l'app protégée (même avec
  un tenant valide), scope lifespan toujours laissé passer — rouge→vert vérifié par `git stash`.

**Symptôme** :
```python
if scope.get("type") != "http":
    await self._app(scope, receive, send)   # laisse passer sans vérifier le Bearer
    return
```
Tout scope non-`http` (websocket) traverse la garde sans vérification. Non exploitable aujourd'hui car
le sous-app monté est `StreamableHTTPASGIApp` (transport HTTP uniquement). À corriger comme
fail-closed explicite.

**Correction** : rejeter explicitement (ou exiger le Bearer sur) tout scope non-`http`, au lieu de le
laisser passer.
