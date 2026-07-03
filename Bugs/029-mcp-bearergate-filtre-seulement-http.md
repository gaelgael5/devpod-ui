# 029 — MCP : `BearerGate` ne filtre que les scopes `http`

- **Sévérité** : mineur (non exploitable en l'état : sous-app HTTP uniquement) — durcissement
- **Sous-système** : mcp / asgi_auth
- **Fichier** : `mcp/asgi_auth.py:22-24`
- **Statut** : ouvert

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
