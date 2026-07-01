# SPEC — Primitive MCP `logs_query` (devpod-ui)

> Fonctionnalité : exposer aux agents une primitive MCP **read-only** pour interroger les logs
> centralisés de toute la stack (tous les hosts + workspaces), en une requête, avec retour d'un
> lien Grafana pré-filtré. C'est le §6 de `30-logs-parametrage.md`, développé en spec dédiée.
> Repo : `gaelgael5/devpod-ui` — branche `dev` — commits conventionnels en français.
>
> Références : `30-logs-parametrage.md` (section `logs:`, labels du collecteur),
> `27-convention-descripteurs-mcp.md` (convention de descripteurs), `24-mcp-devpod.md` /
> `25-mcp-devpod-complement.md` (surface MCP du portail).

---

## 1. Contexte & objectif

La stack de logs (spec 30) agrège dans Loki les logs de tous les hosts. Deux surfaces la
consomment, sur **une seule source** (l'API Loki) : Grafana pour l'humain, cette primitive pour
l'agent. Un agent doit pouvoir filtrer les logs par host / rôle / projet / service / niveau sur
une fenêtre temporelle, **sans** se connecter host par host, et recevoir en retour les lignes
**plus** un lien Grafana vers la même requête (bascule agent → humain en un clic).

La primitive ne dédouble pas les outils existants `workspace_logs` / `compose_service_logs`
(point-in-time, une cible précise) : elle apporte la vue **transverse et historique** sur toute
la flotte.

---

## 2. Descripteur MCP

```
name: logs_query
impact: read-only — aucune mutation, simple lecture de l'agrégateur Loki.
description: >
  Interroge les logs centralisés de la stack (tous les hosts + workspaces + système).
  Filtres structurés par host/role/project/service/unit/level, ou expression LogQL brute
  pour les cas avancés. Retourne les lignes correspondantes et un lien Grafana pré-filtré.
  Préférer cet outil à workspace_logs/compose_service_logs pour une vue transverse ou
  historique ; les outils par-conteneur restent utiles pour du point-in-time sur une cible.
```

Exposée uniquement si `logs.enabled = true` (spec 30 §2). Si désactivée, la primitive n'est pas
enregistrée dans la surface MCP.

---

## 3. Paramètres

| Champ       | Type                       | Défaut     | Rôle |
|-------------|----------------------------|------------|------|
| `query`     | `str \| None`              | `None`     | Expression LogQL brute (échappatoire puissance). Si fournie, prime sur les filtres. |
| `host`      | `str \| None`              | `None`     | Filtre label `host` (ex. `host-test-105-2`). |
| `role`      | `str \| None`              | `None`     | Filtre label `role` (`portail`/`workspace`/`test`). |
| `project`   | `str \| None`              | `None`     | Filtre label `compose_project` (workspace / déploiement compose). |
| `service`   | `str \| None`              | `None`     | Filtre label `compose_service`. |
| `unit`      | `str \| None`              | `None`     | Filtre label `unit` (logs journald : `docker.service`, `sshd`…). |
| `level`     | `str \| None`              | `None`     | Filtre niveau structlog via `| json | level="..."`. |
| `since`     | `str`                      | `"1h"`     | Fenêtre relative (`15m`, `6h`, `2d`). Ignoré si `start`/`end`. |
| `start`     | `str \| None` (rfc3339)    | `None`     | Borne absolue optionnelle. |
| `end`       | `str \| None` (rfc3339)    | `None`     | Borne absolue optionnelle. |
| `limit`     | `int` (1..5000)            | `200`      | Nombre max de lignes. |
| `direction` | `forward` \| `backward`    | `backward` | Ordre (backward = plus récent d'abord). |

**Règle** : si `query` est absent, **au moins un** filtre de *label de stream*
(`host`/`role`/`project`/`service`/`unit`) est requis — Loki refuse un sélecteur vide. `level`
seul ne suffit pas (c'est un filtre de pipeline, pas un sélecteur de flux). Erreur de validation
explicite sinon, avant tout appel réseau.

---

## 4. Construction LogQL (mapping paramètre → label réel)

Les filtres mappent vers les **labels réels émis par le collecteur** (spec 30 §3.1) :

| Paramètre | Label Loki        |
|-----------|-------------------|
| `host`    | `host`            |
| `role`    | `role`            |
| `project` | `compose_project` |
| `service` | `compose_service` |
| `unit`    | `unit`            |

- `query` fourni → utilisé tel quel.
- sinon : `{ <selectors joints par ,> }` puis, si `level`, `| json | level="<level>"`.
  - ex. `host=host-dev-01`, `project=rag`, `level=error`
    → `{host="host-dev-01",compose_project="rag"} | json | level="error"`

> Note de cohérence : le §6 de la spec 30 évoquait des filtres « node/workspace/service » ;
> cette spec les précise en `host`/`project`/`service` pour coller aux labels réellement émis
> (§3.1 de la 30). `role` reste identique. C'est la source de vérité pour les noms de filtres.

---

## 5. Retour

```json
{
  "query": "{compose_project=\"rag\"} | json | level=\"error\"",
  "range": { "start": null, "end": null, "since": "1h" },
  "count": 12,
  "truncated": false,
  "lines": [
    { "ts": "2026-07-01T09:31:02.114Z",
      "labels": { "host": "host-test-105-2", "role": "test",
                  "compose_project": "rag", "compose_service": "chromium" },
      "line": "{...structlog json...}" }
  ],
  "grafana_url": "https://<grafana>/explore?...=<LogQL + range encodés>"
}
```

- `truncated=true` si `count == limit` (l'agent sait qu'il faut affiner/paginer).
- `grafana_url` : deep-link Explore pré-rempli, construit depuis `logs.grafana_url`. Le format
  d'URL exact (`panes`/`left`) dépend de la version de Grafana — à caler ; **fallback** = lien
  nu vers `/explore` avec la datasource Loki sélectionnée.

---

## 6. Comportement d'échec (explicite, jamais silencieux)
- Loki injoignable → erreur `logs_backend_unreachable` avec l'URL tentée.
- LogQL invalide → remonter le message d'erreur de Loki tel quel (débogable).
- Sélecteur vide (ni `query` ni label de stream) → erreur de validation avant appel réseau.
- Zéro résultat → succès avec `count: 0`, `lines: []` (ce n'est pas une erreur).

---

## 7. Configuration consommée (spec 30 §2)
- `logs.loki_query_url` → base des appels `/loki/api/v1/query_range` (URL interne du portail).
- `logs.grafana_url` → base du deep-link `grafana_url` retourné.
- `logs.push_token` → si présent, porté en `Authorization` (Loki protégé).
- `logs.enabled` → conditionne l'enregistrement de la primitive.

---

## 8. Squelette d'implémentation (à câbler dans l'enregistrement d'outils MCP du portail)
```python
# portal/mcp/tools/logs_query.py  (< 300 lignes, httpx async, pydantic v2)
from typing import Literal
import httpx
import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger()

_LABEL = {  # paramètre -> label Loki réel (spec 30 §3.1)
    "host": "host", "role": "role", "project": "compose_project",
    "service": "compose_service", "unit": "unit",
}

class LogsQueryParams(BaseModel):
    model_config = {"extra": "forbid"}
    query: str | None = None
    host: str | None = None
    role: str | None = None
    project: str | None = None
    service: str | None = None
    unit: str | None = None
    level: str | None = None
    since: str = "1h"
    start: str | None = None
    end: str | None = None
    limit: int = Field(200, ge=1, le=5000)
    direction: Literal["forward", "backward"] = "backward"

def build_logql(p: LogsQueryParams) -> str:
    if p.query:
        return p.query
    sel = [f'{lbl}="{getattr(p, key)}"'
           for key, lbl in _LABEL.items() if getattr(p, key)]
    if not sel:
        raise ValueError("logs_query: fournir une query LogQL ou au moins un filtre de label "
                         "(host/role/project/service/unit)")
    expr = "{" + ",".join(sel) + "}"
    if p.level:
        expr += f' | json | level="{p.level}"'
    return expr

async def logs_query(p: LogsQueryParams, *, cfg) -> dict:  # cfg = LogsConfig (spec 30)
    logql = build_logql(p)
    params = {"query": logql, "limit": p.limit, "direction": p.direction}
    if p.start and p.end:
        params["start"], params["end"] = p.start, p.end
    else:
        params["since"] = p.since
    headers = {"Authorization": f"Bearer {cfg.push_token}"} if cfg.push_token else {}
    url = f"{cfg.loki_query_url}/loki/api/v1/query_range"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, params=params, headers=headers)
            r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("logs_backend_unreachable", url=url, error=str(e))
        raise RuntimeError(f"logs_backend_unreachable: {url} ({e})") from e
    lines = _flatten_streams(r.json())[: p.limit]   # -> [{ts, labels, line}]
    return {
        "query": logql,
        "range": {"start": p.start, "end": p.end, "since": None if p.start else p.since},
        "count": len(lines),
        "truncated": len(lines) == p.limit,
        "lines": lines,
        "grafana_url": _grafana_explore_url(cfg.grafana_url, logql, p),
    }
# _flatten_streams / _grafana_explore_url : helpers dédiés, testés isolément.
```

---

## 9. Contraintes & conventions
- pydantic v2 `extra="forbid"` ; httpx async ; structlog JSON ; fichier ≤ 300 lignes.
- Read-only : aucune écriture, aucun asyncpg (la primitive n'a pas de base).
- Conforme à `27-convention-descripteurs-mcp.md` (descripteur clair, identités = labels réels,
  échec explicite).
- Additif à la surface MCP ; commits conventionnels en français, sur `dev`.

## 10. Critères d'acceptation
1. `logs_query(project="rag", level="error")` retourne les lignes d'erreur du workspace `rag`,
   toutes machines confondues, + un `grafana_url` ouvrant la même requête.
2. `logs_query(role="test")` retourne les logs de tous les serveurs de test.
3. `logs_query(host="host-dev-01", unit="docker.service")` retourne les logs journald du daemon
   Docker du host portail (valide la collecte système de la spec 30).
4. Appel sans `query` ni label de stream → erreur de validation, sans appel réseau.
5. Loki injoignable → `logs_backend_unreachable` avec l'URL.
6. `logs.enabled=false` → la primitive n'est pas exposée.
