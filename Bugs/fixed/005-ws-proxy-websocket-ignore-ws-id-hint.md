# 005 — Le proxy WebSocket VS Code ignore le `ws_id_hint` → route vers le mauvais workspace

- **Sévérité** : majeur (dès qu'un utilisateur a ≥ 2 workspaces `running`)
- **Sous-système** : exposure / vscode_proxy
- **Fichiers** : `backend/src/portal/routes/vscode_proxy.py` — handler WS `vscode_ws_proxy` (~200 : `host_port = await _resolve_host_port(login)`), à comparer au handler HTTP (~112-114 qui extrait `ws_id_hint`) ; `_resolve_host_port` (~50-64) ; `_ws_id_hint_from_query` (~76-84)
- **Statut** : corrigé — `vscode_ws_proxy` extrait désormais `ws_id_hint` via `_ws_id_hint_from_query` avant de résoudre `host_port`, comme le proxy HTTP. Tests ajoutés (`tests/routes/test_vscode_proxy.py`).

## Symptôme

Avec deux workspaces `running`, VS Code s'ouvre cassé pour celui qui n'est pas le premier de la
liste DB : les assets HTTP viennent du bon workspace (via `?folder=`), mais le WebSocket (Extension
Host, LSP, terminal) se connecte à l'autre workspace. Symptôme : WS 1006, extension host mort,
terminal introuvable.

## Cause racine

Le proxy HTTP résout correctement le workspace cible en extrayant le hint depuis
`?folder=/workspaces/{ws_id}` et en le passant à `_resolve_host_port(login, ws_id_hint)`. Mais le
handler **WebSocket** appelle `_resolve_host_port(login)` **sans** hint → `_resolve_host_port`
retombe sur `running[0]` (ordre DB arbitraire). Les deux moitiés d'une même session VS Code pointent
donc vers deux workspaces différents.

## Piste de correction

Dans `vscode_ws_proxy`, extraire le `ws_id` depuis `websocket.scope["query_string"]` (réutiliser
`_ws_id_hint_from_query`) et le passer à `_resolve_host_port`, exactement comme le fait le handler
HTTP.

## Vérifié

Confirmé par lecture : le handler HTTP (`vscode_http_proxy`) calcule `ws_id_hint` et le transmet ;
le handler WS appelle `_resolve_host_port(login)` sans argument de hint.
