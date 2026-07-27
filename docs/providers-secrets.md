# Convention des secrets providers LLM & gateway (enabler d92893b1)

Chemins de secrets **par utilisateur** (résolus par le SecretResolver depuis le
namespace Harpocrate de l'utilisateur, fallback inline), consommés par les
recettes via `requires_secrets` → injectés en `remoteEnv` du devcontainer.
Alignés sur le style existant (`llm/anthropic_key` → `ANTHROPIC_API_KEY`).

| Chemin vault           | Variable d'env         | Consommateur                    | Nature |
|------------------------|------------------------|---------------------------------|--------|
| `llm/anthropic_key`    | `ANTHROPIC_API_KEY`    | claude-code (existant)          | Clé API Anthropic |
| `llm/deepseek_api_key` | `DEEPSEEK_API_KEY`     | aider (défaut), opencode        | Clé API DeepSeek |
| `llm/zai_api_key`      | `ZAI_API_KEY`          | opencode (provider GLM)         | Token Z.ai **au compteur** (API paas) |
| `llm/zai_coding_token` | `ANTHROPIC_AUTH_TOKEN` | claude-code-glm                 | Token Z.ai **Coding Plan** (endpoint anthropic) |
| `mcp/gateway_token`    | `MCP_GATEWAY_TOKEN`    | opencode (MCP remote)           | Clé client de la gateway MCP `dev.yoops.org/mcp/` |

Points d'attention :

- **Deux tokens Z.ai distincts** : le Coding Plan (forfait, endpoint
  `api.z.ai/api/anthropic`, réservé aux outils type claude-code) et le token API
  au compteur (`api.z.ai/api/paas/v4`, openai-compatible). Ne pas les confondre.
- **Aucune valeur en clair** nulle part : les recettes ne portent que les
  références ; l'utilisateur pose ses valeurs dans ses secrets portail
  (Harpocrate ou inline) sous les chemins ci-dessus.
- `mcp/gateway_token` : à terme, l'accès MCP des agents « spec 35 »
  (agent_types) est provisionné automatiquement par le portail ; ce chemin sert
  au cas opencode configuré par recette. Si opencode devient un agent_type
  géré, ce secret devient inutile pour lui.

## Recettes consommatrices (repo `ag-flow/ressources`)

- `recipes/aider` v1.1.0 — DeepSeek par défaut (`AIDER_MODEL=deepseek/deepseek-chat`
  via `/etc/profile.d/aider-defaults.sh`). GLM différé (routé via claude-code).
- `recipes/opencode` v1.1.0 — `/etc/opencode/opencode.json` (écrit par
  `install.sh`, tranché vs template jinja : config statique, secrets en
  `{env:…}`) : providers DeepSeek (défaut) + GLM, MCP remote vers la gateway.
- `recipes/claude-code-glm` v1.0.0 — **opt-in** : profil GLM de claude-code
  (`ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic`, `ANTHROPIC_MODEL=glm-5.2`)
  via `/etc/profile.d/` ; sans cette recette, claude-code reste sur Anthropic
  natif. `installs_after: claude-code`.

## Ce qui reste à la main de l'admin

1. Poser les valeurs dans Harpocrate (ou secrets inline du portail) sous les
   chemins du tableau : `DEEPSEEK_API_KEY`, `ZAI_API_KEY` (si GLM au compteur),
   `ZAI` Coding Plan, et une clé client MCP gateway.
2. `POST /admin/recipes/sync` (la synchro des recettes n'est jamais automatique).
3. Validation runtime dans un vrai workspace (`aider --model`, `opencode` liste
   les outils MCP, `claude` répond via GLM) — non jouable sans les valeurs.
