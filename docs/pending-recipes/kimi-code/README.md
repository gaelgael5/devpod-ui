# Recette `kimi-code` — prête à appliquer sur `ag-flow/ressources`

Agent IA de terminal **Kimi Code CLI** (`@moonshot-ai/kimi-code`, commande `kimi`),
pendant de `claude-code` / `copilot-cli`, à ajouter au catalogue de recettes servi
à la création de workspace. Contenu **validé contre le modèle `RecipeMeta`**.

## Faits vérifiés (doc Moonshot + npm, 2026-08-07)

- Package `@moonshot-ai/kimi-code` · install `npm install -g @moonshot-ai/kimi-code` · commande `kimi`.
- **Node.js 22.19+ requis** (garde explicite dans `install.sh`).
- Auth **`/login`** au runtime (OAuth Kimi Code ou clé API Moonshot). **Aucun secret côté recette.**
- État/auth dans **`~/.kimi-code`** → monté en `memory_volume`.
- Câblage MCP séparé : agent_type `kimi` (migration `085`) écrit `~/.kimi-code/mcp.json`.

## Application (repo externe, étape humaine — pas de push autonome)

```bash
git clone git@github.com:ag-flow/ressources.git && cd ressources
mkdir -p recipes/kimi-code
cp /chemin/devpod-ui/docs/pending-recipes/kimi-code/{devcontainer-feature.json,install.sh,recipe.meta.yaml} recipes/kimi-code/
chmod +x recipes/kimi-code/install.sh
echo "kimi-code/" >> recipes/toc.txt
git add recipes/kimi-code recipes/toc.txt
git commit -m "feat(recipes): Kimi Code CLI (agent terminal Moonshot)"
git push origin main
```

Côté devpod ensuite : `POST /admin/recipes/sync`, migration `085`, puis « Kimi Code
CLI » apparaît dans le sélecteur d'agents à la création de workspace.

## Validation runtime attendue

- La recette apparaît au catalogue et est cochable à la création.
- Dans un workspace qui l'active : `kimi` disponible en terminal, `/login` OK, auth
  **persistée après recréation** (si memory-volume activé), et les outils MCP de la
  gateway visibles (via `~/.kimi-code/mcp.json` écrit par l'agent_type `kimi`).
- Aucun secret dans l'image, les layers ni les logs.
