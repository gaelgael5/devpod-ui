# 017 — MCP : les exceptions non-`DevpodToolError` échappent au dispatch → trou d'audit

- **Sévérité** : majeur
- **Sous-système** : mcp
- **Fichiers** : `backend/src/portal/mcp/devpod_tools/__init__.py:1113-1117` (dispatch `execute_internal_tool`), `mcp/handlers.py:130-158` ; sources d'exceptions non gardées : `message_tools.py:18-21` (`ValueError` explicite) et les `int(args.get(...))` non validés : `__init__.py:144` (`lines`), `413` (`depth`), `462` (`timeout_s`), `607` (`lines`), `compose_tools.py:275` (`tail`)
- **Statut** : ouvert

## Symptôme

Un client MCP qui envoie un argument mal typé (`{"workspace":"x","lines":"abc"}`) provoque une erreur
interne opaque **et aucune ligne d'audit n'est écrite** pour l'appel — angle mort d'observabilité sur
des entrées pourtant contrôlées par le client.

## Cause racine

Le gateway ne valide pas les arguments contre l'`inputSchema` avant dispatch (le `Server`
bas-niveau MCP ne valide pas par défaut). `execute_internal_tool` ne rattrape que `DevpodToolError` :
```python
try:
    payload = await impl(conn, arguments, owner_login)
except DevpodToolError as exc:
    return _err(exc.message)
```
Toute autre exception (`ValueError` de `int("abc")`, `_workspace_messages` qui lève `ValueError`)
remonte à `execute_tool_call` qui ne rattrape que `BackendUnavailable` → elle **contourne**
`audit_record` (handlers.py:151) et remonte brute au serveur MCP.

## Piste de correction

Valider les arguments contre l'`inputSchema` en amont du dispatch ; **ou** envelopper le corps de
`execute_internal_tool` dans un `except Exception` qui journalise + audite `status="error"` + renvoie
`_err`. Faire lever `DevpodToolError` (pas `ValueError`) par `_workspace_messages` et les conversions
`int()`.
