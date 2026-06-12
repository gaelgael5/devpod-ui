# SSH Terminal — Fenêtre flottante sur les hosts SSH

**Date :** 2026-06-12
**Scope :** Admin uniquement — hosts de type `ssh`

## Contexte

La liste des hosts admin expose des nœuds SSH (`type: "ssh"`, `address: "user@ip"`, `key_path: "/data/keys/…"`). Pour diagnostiquer la connexion DevPod sur ces nœuds, l'admin a besoin d'un terminal SSH directement dans l'UI sans sortir du portail.

## Architecture globale

```
Browser (xterm.js)  ──WebSocket──▶  FastAPI WS handler  ──subprocess──▶  SSH daemon
                    ◀──bytes───────                      ◀──stdout/stderr─
```

Le backend FastAPI sert de proxy SSH. La clé privée (`key_path`) ne quitte jamais le serveur.

- Endpoint : `WebSocket /admin/hosts/{name}/ssh`
- Auth : cookie de session Starlette (envoyé automatiquement par le navigateur sur les WS same-origin). Le handler lit `websocket.session.get("user")` — même mécanique que `require_admin` sur les routes HTTP.
- Une seule connexion à la fois : le frontend impose une fenêtre unique
- Fermeture WebSocket → kill subprocess SSH ; fin subprocess → fermeture WebSocket

## Backend

**Nouveau fichier :** `backend/src/portal/routes/ssh_proxy.py`

**Endpoint :**
```python
@router.websocket("/admin/hosts/{name}/ssh")
async def host_ssh_terminal(name: str, websocket: WebSocket)
```

**Flux :**
1. Accepter le WebSocket
2. Lire `websocket.session.get("user")` → vérifier rôle admin → fermer code 4001 si refus
3. Charger `GlobalConfig`, trouver le host → fermer si absent ou si `type != "ssh"`
4. Vérifier `host_cfg.key_path` non-vide + fichier existant + sous `/data` (sécurité path traversal)
5. Lancer subprocess SSH :
   ```
   ssh -i <key_path> -o StrictHostKeyChecking=no -o BatchMode=no <user@host>
   ```
   avec `stdin=PIPE`, `stdout=PIPE`, `stderr=STDOUT`
6. Deux tâches concurrentes :
   - **ws→ssh** : bytes entrants WebSocket → `proc.stdin`
   - **ssh→ws** : `proc.stdout` → bytes sortants WebSocket
7. Annuler les deux tâches + `proc.kill()` à la déconnexion ou fin subprocess

**Enregistrement** dans `app.py` :
```python
from .routes.ssh_proxy import router as ssh_proxy_router
app.include_router(ssh_proxy_router)
```

## Frontend

**Nouvelles dépendances :**
```
xterm  @xterm/addon-fit
```

**Nouveaux fichiers** dans `frontend/src/features/admin/` :

### `SshTerminalWindow.tsx`
- Rendu via `ReactDOM.createPortal(…, document.body)` — hors du DOM de la table
- Props : `host: HostConfig`, `onClose: () => void`
- Drag : `useRef` position + listeners `mousedown/mousemove/mouseup` sur le header
- `useEffect` : `new Terminal({…})` + `FitAddon` + `terminal.open(ref)` + connexion WebSocket
- `ws://…/admin/hosts/{name}/ssh` (cookie de session envoyé automatiquement)
- `terminal.onData(data => ws.send(data))` — frappe → subprocess
- `ws.onmessage(e => terminal.write(e.data))` — output → xterm
- Fermeture : `onClose` ferme WS + detach xterm
- Taille initiale : 600 × 400 px
- Style : header sombre `#2d2d3f` avec adresse SSH + bouton rouge (fermer uniquement)

**Modifications dans `AdminHosts.tsx`** :
- État : `const [sshTarget, setSshTarget] = useState<HostConfig | null>(null)`
- Ligne de table : conditionnel `h.type === 'ssh'` → divider + bouton `SSH`
- JSX bas de page : `{sshTarget && <SshTerminalWindow host={sshTarget} onClose={() => setSshTarget(null)} />}`

## Tests

### Backend — `tests/test_ssh_proxy.py`
- Session absente ou rôle insuffisant → WebSocket fermé code 4001
- Host inconnu → fermeture avec message d'erreur
- Host `docker-tls` → fermeture 422
- `key_path` vide ou fichier absent → fermeture avec message d'erreur
- `key_path` hors `/data` → fermeture 422 (path traversal)
- Proxy nominal : faux subprocess echo, vérifier bytes aller-retour
- Fermeture WebSocket → subprocess tué

### Frontend — `AdminHosts.test.tsx` (extension)
- Bouton SSH absent sur ligne `docker-tls`
- Bouton SSH présent sur ligne `ssh`
- Clic SSH → `SshTerminalWindow` monté

### Frontend — `SshTerminalWindow.test.tsx`
- Mock `xterm` et `WebSocket`
- Rendu initial → header contient l'adresse du host
- Clic bouton rouge → `onClose` appelé + WebSocket fermé

## Hors scope
- Resize de la fenêtre (taille fixe suffisante pour du diagnostic)
- Bouton réduire / minimiser
- Sessions multiples simultanées
- Historique des commandes persisté
