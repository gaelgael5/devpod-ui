# Recette `copilot-cli` — prête à appliquer sur `ag-flow/ressources`

Agent IA de terminal **GitHub Copilot CLI** (`@github/copilot`), pendant de
`claude-code`, à ajouter au catalogue de recettes servi à la création de
workspace. Contenu **validé contre le modèle `RecipeMeta`** du portail devpod.

## Faits vérifiés (doc GitHub officielle + npm, 2026-08-06)

- Package : `@github/copilot` · install `npm install -g @github/copilot` · commande `copilot`.
- **Node.js 22+ requis** (garde explicite dans `install.sh`).
- Auth **device-flow** au runtime (`copilot` → `/login`) avec la licence Copilot du
  dev, ou env `COPILOT_GITHUB_TOKEN`/`GH_TOKEN`. **Aucun secret côté recette.**
- État/auth dans **`~/.copilot`** (override `COPILOT_HOME`) → monté en `memory_volume`.

## Application (repo externe, étape humaine — pas de push autonome)

```bash
git clone git@github.com:ag-flow/ressources.git && cd ressources
mkdir -p recipes/copilot-cli
cp /chemin/devpod-ui/docs/pending-recipes/copilot-cli/{devcontainer-feature.json,install.sh,recipe.meta.yaml} recipes/copilot-cli/
chmod +x recipes/copilot-cli/install.sh
echo "copilot-cli/" >> recipes/toc.txt          # ajouter l'entrée au catalogue
git add recipes/copilot-cli recipes/toc.txt
git commit -m "feat(recipes): GitHub Copilot CLI (agent terminal, licence Copilot)"
git push origin main
```

Côté devpod ensuite : `POST /admin/recipes/sync`, puis la recette **« GitHub
Copilot CLI » apparaît dans le sélecteur d'agents à la création de workspace**.

## Validation runtime attendue

- La recette apparaît au catalogue et est cochable à la création.
- Dans un workspace qui l'active : `copilot` disponible en terminal, `/login`
  device-flow fonctionnel, auth **persistée après recréation** (si memory-volume activé).
- Aucun secret dans l'image, les layers ni les logs.
