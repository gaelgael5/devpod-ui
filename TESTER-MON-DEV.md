# Tester mon développement — Procédure optimisée

## Environnement de test disponible

### Machine test1 (`192.168.10.196`)

> ⚠️ Les VMs de test sont éphémères : l'IP peut changer d'une session à l'autre.
> L'alias SSH `test1` (~/.ssh/config) est la source de vérité — l'utiliser partout.

Alias SSH `test1` (défini dans `~/.ssh/config`). VM dédiée aux tests du portail, accessible en SSH depuis le devpod.

Répertoire du projet : `/opt/workspace-portal-dev` (branche `dev`, clonée manuellement la première fois).

**Stack dev active sur test1 :**

| Service | Accès | Rôle |
|---------|-------|------|
| Portal  | `http://192.168.10.196:8080` | Portail complet (bypass Caddy) |
| Caddy   | `http://192.168.10.196:8090` | Reverse proxy dev |
| PostgreSQL | `192.168.10.196:5432` | Base de données |
| Browserless | `http://192.168.10.196:3000` | Chromium headless — tests UI autonomes |

### Browserless v2 (`ghcr.io/browserless/chromium`)

Chromium headless accessible via API REST — **aucun token requis sur cette instance**.

Permet de tester l'UI de façon autonome sans intervention humaine : naviguer, remplir des formulaires, prendre des captures d'écran, vérifier le rendu.

```bash
# Screenshot d'une page
curl -s -X POST http://192.168.10.196:3000/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.10.196:8080/health"}' \
  -o /tmp/screen.png

# Vérifier que Browserless répond
curl -s http://192.168.10.196:3000/config | head -5
```

L'image Browserless peut aussi exécuter du JavaScript arbitraire via `POST /function` — utile pour simuler des clics, remplir des formulaires, attendre des éléments.

### Docker disponible pour services additionnels

Le `docker-compose.dev.yml` peut accueillir des services supplémentaires si le test l'exige (mock OIDC, mock Harpocrate, serveur de fixtures, etc.). Ajouter le service dans `deploy/docker-compose.dev.yml`, le rattacher au réseau `internal` existant, et `dev-deploy.sh` l'inclura automatiquement au prochain `up`.

---

## Cycle standard : écrire → tester → corriger

### Première installation sur test1 (une seule fois)

```bash
ssh test1
git clone -b dev https://github.com/gaelgael5/devpod-ui.git /opt/workspace-portal-dev
APP_DIR=/opt/workspace-portal-dev bash /opt/workspace-portal-dev/scripts/dev-deploy.sh dev
```

### Cycle normal (toutes les fois suivantes)

```bash
# 1. Écrire le code localement, vérifier lint + mypy
cd backend && uv run ruff check src/ && uv run mypy src/

# 2. Pousser sur dev
git push origin dev

# 3. Déployer sur test1 — le script fait git pull + build + restart + migrations
ssh test1 "APP_DIR=/opt/workspace-portal-dev bash /opt/workspace-portal-dev/scripts/dev-deploy.sh dev"

# 4. Lire les logs du portail
ssh test1 "docker compose -f /opt/workspace-portal-dev/deploy/docker-compose.dev.yml logs portal --tail=100"

# 5. Tester via Browserless ou curl
curl -s http://192.168.10.196:8080/health
```

`dev-deploy.sh` est **idempotent** et **auto-mise à jour** (il se ré-exécute lui-même si le script a changé dans le pull). Ne jamais faire `git pull` manuellement sur test1 — le script le fait.

---

## Règle fondamentale : le workflow EST l'environnement de test

**Ne jamais simuler l'environnement avec `docker run --rm python -c '...'`.**

Ces commandes n'ont pas le même réseau, le même `.env`, le même cycle de vie uvicorn, ni le même contexte lifespan que la vraie stack. Elles produisent des résultats qui ne se reproduisent pas dans le vrai service — c'est précisément ce qu'on cherche à éviter.

Le seul environnement de référence, c'est la stack lancée par `dev-deploy.sh`. Toute hypothèse doit être vérifiée là-dedans, pas dans une commande isolée.

---

## Diagnostic d'un bug en production (ordre des actions)

### 1. Lire les vrais logs en premier

```bash
ssh test1 "docker compose -f /opt/workspace-portal-dev/deploy/docker-compose.dev.yml logs portal --tail=200 2>&1"
```

Si le traceback est présent : le bug est identifié, on passe à la correction.

### 2. Si le crash est silencieux (pas de traceback) : instrumenter le code

Ajouter des `log.info("lifespan_step", step="nom_etape")` dans le code suspect — notamment dans le lifespan de `app.py` où chaque étape doit être tracée :

```python
log.info("lifespan_step", step="warm_global_cache")
await warm_global_cache(conn)
log.info("lifespan_step", step="ensure_system_user")
await ensure_system_user(conn)
```

Puis : **pousser → déployer → relire les logs**. Le dernier log avant le crash indique l'étape fautive.

### 3. Si le process hang (pas de crash, pas de log) : py-spy

```bash
# Récupérer le PID du process Python dans le conteneur
ssh test1 "docker compose -f /opt/workspace-portal-dev/deploy/docker-compose.dev.yml exec portal ps aux | grep python"

# Obtenir le stack trace de tous les threads
ssh test1 "docker compose -f /opt/workspace-portal-dev/deploy/docker-compose.dev.yml exec portal py-spy dump --pid <PID>"
```

`py-spy` donne immédiatement l'appel bloquant, sans modifier le code.

### 4. Pour inspecter l'état de la DB

```bash
ssh test1 "docker compose -f /opt/workspace-portal-dev/deploy/docker-compose.dev.yml exec postgres psql -U \$POSTGRES_USER portal -c 'SELECT * FROM global_config;'"
```

---

## Tests UI autonomes avec Browserless

Browserless permet de tester l'interface sans intervention humaine. Utiliser `POST /function` pour exécuter du JavaScript dans Chromium :

```bash
curl -s -X POST http://192.168.10.196:3000/function \
  -H "Content-Type: application/json" \
  -d '{
    "code": "async ({ page }) => {
      await page.goto(\"http://192.168.10.196:8080\");
      await page.waitForSelector(\"#app\", { timeout: 5000 });
      return { title: await page.title(), url: page.url() };
    }"
  }'
```

Pour un screenshot après interaction :

```bash
curl -s -X POST http://192.168.10.196:3000/screenshot \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://192.168.10.196:8080",
    "options": { "fullPage": true }
  }' -o /tmp/screen.png
```

L'image `/tmp/screen.png` peut ensuite être lue avec le tool `Read` (Claude Code supporte la lecture d'images).

---

## Ajouter un service temporaire à la stack de test

Si un test nécessite un service externe (mock OIDC, mock Harpocrate, etc.) :

1. Ajouter le service dans `deploy/docker-compose.dev.yml` avec `networks: [internal]`
2. Pousser + relancer `dev-deploy.sh` — le service sera démarré avec le reste
3. Le nommer explicitement pour éviter toute confusion avec la stack de prod

Exemple de service mock simple :

```yaml
  mock-oidc:
    image: ghcr.io/navikt/mock-oauth2-server:latest
    networks:
      - internal
    environment:
      SERVER_PORT: "8888"
```

Le portail peut alors l'atteindre via `http://mock-oidc:8888` sur le réseau interne.
