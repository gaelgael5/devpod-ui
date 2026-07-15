# FAQ & dépannage

Cas concrets rencontrés en exploitation et à l'usage.

## Écran blanc après connexion OIDC

**Cause la plus fréquente** : le rôle attendu par le portail ne correspond pas à
ce qu'émet Keycloak. Le portail cherche `OIDC_ADMIN_ROLE` (ex. `yoops-admin`) dans
le claim `OIDC_ROLE_CLAIM` (`realm_access.roles`) — si le mapping Keycloak diffère,
l'utilisateur n'est jamais reconnu et l'app reste vide.

**Correctif** : aligner le **mapping de rôles Keycloak** et la variable
`OIDC_ADMIN_ROLE` (voir [Guide admin §5](guide-administrateur.md#5-oidc--rôles)).

## Le portail renvoie des 502 (Caddy)

Deux situations très différentes :

| | Fenêtre de boot (normal) | Crash-loop (bug) |
|---|---|---|
| `docker compose ps` | `health: starting` → `healthy` | `Restarting` / `unhealthy` |
| `logs portal` | logs `info` normaux | **stacktrace Python répétée** |
| Caddy | 502 pendant ~40-70 s puis OK | 502 **indéfiniment** |

- **Fenêtre de boot** : après un redéploiement, le portail **réconcilie tous les
  workspaces** (upload devcontainer, `devpod up`, rotation de clés, routes Caddy)
  avant d'être prêt. Les 502 cessent seuls. **Rien à faire, on attend.**
- **Crash-loop** : `uvicorn` n'arrive pas à charger l'app (exception à l'import ou
  au lifespan, ou migration en échec). Lire la **stacktrace** dans `logs portal`,
  corriger, redéployer.

> Exemple vécu : un type d'événement (`skill.available`) ajouté sans son
> `dataSchema` → `RuntimeError` **à l'import** → crash-loop. Cf.
> [Guide dev](guide-developpeur.md#tests).

## `dial tcp: lookup <service> no such host` dans Caddy

Le conteneur cible (ex. `portal`, `alloy`) n'est pas (encore) enregistré au DNS
Docker : soit il redémarre (crash-loop), soit il démarre juste (fenêtre de boot).
Vérifier `docker compose ps`. Si un service reste absent, vérifier qu'il est bien
sur le **même réseau** que Caddy et qu'il tourne.

## Ouvrir une 2e session tombe toujours sur la première

**Corrigé.** Symptôme : cliquer `devpod2` ouvrait `devpod1` (tous les onglets
nommés `devpod1`). Cause : la sélection issue de `?session=` était écrasée pendant
le chargement de la liste des sessions. La session effective est désormais
**dérivée** (pas de course) : `?session=` est honoré, et la retombée sur la
première n'a lieu qu'**après** chargement de la liste.

## Une session ne se reconnecte pas

Le **tmux backend survit** à la fermeture de l'onglet et au redéploiement du
portail. Si la WebSocket tombe, un overlay **« Session déconnectée »** propose
**Reconnecter** (rattachement au tmux). Si ça échoue, vérifier que le workspace
est `running` et joignable en SSH.

## Les stacks docker d'une VM de test n'apparaissent pas

La vue live utilise `docker compose ls` / `docker ps` **sur la machine** via SSH.
Si vide : docker/compose absent, hôte injoignable, ou clé SSH portail non posée
(le placement se fait à la création de la VM). C'est **best-effort** — une erreur
n'affiche rien plutôt que de bloquer.

## Captures d'écran automatisées (documentation)

Le chromium de test2 (Browserless `:3000`) capture les pages **publiques** (login)
directement. Pour les pages **protégées**, il faut une **session** : le portail
n'accepte que l'OIDC (`local_auth_enabled: false`), donc une capture sans session
ne montre que l'écran de login. Fournir un **cookie `portal_session`** (ou activer
l'auth locale sur l'environnement de test) permet de capturer les écrans
authentifiés.

## Où sont les données ?

- **PostgreSQL** : grants/placements, délégations, sessions, messages, compose,
  certs nœuds, préférences.
- **`/data`** (fichiers) : config par utilisateur (YAML), CA & certs, secrets
  inline, état local DevPod. **Sauvegardé chiffré** par `backup.sh` (age).
