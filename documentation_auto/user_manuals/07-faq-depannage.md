# 7. FAQ & dépannage

## Connexion et coffre

**Je n'arrive pas à me connecter (compte local).**
Vérifiez identifiant et mot de passe ; le message « identifiants invalides » couvre les
deux cas. Si votre instance utilise le SSO, passez par le bouton de connexion OIDC. En
dernier recours, l'administrateur peut vérifier la configuration d'authentification
(page **Configuration OIDC**, compte local *break-glass*).

**J'ai oublié mon PIN.**
Sur l'écran « Déverrouiller le coffre », utilisez **Code de secours oublié ?** avec le
code de secours remis à la création du PIN. Sans ce code, utilisez **Coffre
inaccessible ?** — mais les secrets chiffrés avec l'ancien PIN ne sont pas récupérables :
vous devrez re-saisir vos tokens et régénérer vos clés.

**Le portail me redemande mon PIN.**
Normal : le coffre se verrouille à chaque nouvelle session. Le PIN déverrouille les
secrets pour la session en cours uniquement.

## Workspaces

**Mon workspace reste longtemps en création.**
La première création télécharge l'image de base et exécute les recettes : plusieurs
minutes selon l'image et le réseau du nœud. Consultez **⋮ → Logs** (source `setup`)
pour suivre la progression ; si une recette échoue, l'erreur y apparaît.

**VS Code ne s'ouvre pas (erreur ou page blanche).**
Vérifiez d'abord que le badge de la carte est bien **`en cours`** — un workspace arrêté
n'a pas de VS Code joignable. Redémarrez-le au besoin (bouton flèche, ou
**⋮** → redémarrer). Si le problème persiste, regardez **⋮ → Logs**.

**Le clone de mon dépôt privé échoue.**
Trois vérifications : le **secret** (PAT) existe dans Services & Sécurité → Secrets, le
**credential Git** pointe vers ce secret et la bonne forge, et le PAT n'est pas expiré
côté forge (scopes requis : lecture/écriture du dépôt). L'erreur exacte est dans les
logs `setup` du workspace.

**Ma session terminal a disparu ?**
Les sessions sont persistantes côté serveur, mais un **redémarrage** du workspace les
ferme (les actions « destructives sessions » sont signalées dans l'UI). Rouvrez une
session depuis la page Terminal.

**Je ne peux pas pousser mes commits (permission denied).**
Si le workspace a une **clé SSH dédiée** (case cochée à la création), sa clé publique
doit être déclarée sur la forge (deploy key ou clé du compte). Sinon, vérifiez le
credential Git comme ci-dessus.

## Secrets et sécurité

**Où sont stockées mes clés ?**
En base, chiffrées : les colonnes sensibles sont chiffrées au repos et les clés privées
le sont avec votre PIN vault. Rien n'apparaît en clair dans les sauvegardes ni les
exports (voir bandeau de l'onglet Vault).

**Puis-je partager un secret avec un collègue ?**
Non — les secrets sont personnels (namespace par utilisateur). Chacun enregistre les
siens.

## MCP et automatisation

**Mon client MCP (Claude Desktop, script) reçoit 401.**
La clé `mcpk_…` est peut-être révoquée ou mal collée. Ré-émettez une apikey dans
**Services & Sécurité → MCP → Clés API client** et reprenez le bloc de configuration
affiché sur cette page (URL `…/mcp` + header `Authorization: Bearer`).

**Ma règle ne se déclenche pas.**
Testez-la avec **Jouer** (onglet Règles) en fournissant un workspace de test : vous
verrez si la condition est vraie et si l'action s'exécute. Vérifiez aussi que
l'événement déclencheur est le bon — le **journal des événements** (onglet Événements)
liste ce qui a été réellement émis. Rappel : le journal est purgé après 24 h.

**`{workspace}` est vide quand je teste ma règle.**
Le dialogue **Jouer** demande un « workspace de test » précisément pour alimenter cette
variable : renseignez-le. En production, la variable est remplie par l'événement.

## Divers

**Comment changer la langue ou le thème ?**
Menu utilisateur (initiales en bas du rail) → **Langue : FR/EN** et **Thème :
clair/sombre**.

**Le lien Logs (icône activité) n'apparaît pas.**
Les logs centralisés ne sont pas activés sur votre instance — c'est un réglage
administrateur (voir [chapitre 6, § Logs centralisés](06-administration.md#68-logs-centralisés)).

---

Retour au [sommaire](README.md)
