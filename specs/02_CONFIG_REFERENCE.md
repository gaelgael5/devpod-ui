# 02 — Référence de configuration

Deux fichiers, deux portées. **Tout ce qui suit doit être validé par des modèles pydantic v2.**
Toute valeur de type secret accepte un littéral OU une référence `${vault://path}` / `${env://VAR}`.

## `config.yaml` global (admin)

```yaml
version: "1"

server:
  listen: "0.0.0.0:8080"
  base_domain: "dev.yoops.org"        # ws-<login>-<name>.dev.yoops.org
  external_url: "https://dev.yoops.org"
  dev_mode: false                      # true => reload + logs debug ; JAMAIS true en prod
  log:
    level: "info"                      # debug|info|warn|error
    format: "text"                     # text|json
    output: ""                         # "" => stdout ; sinon chemin sous /data/logs

auth:
  oidc:
    issuer: "https://security.yoops.org/realms/yoops"
    client_id: "workspace-portal"
    client_secret: "${env://OIDC_CLIENT_SECRET}"
    scopes: ["openid", "profile", "email", "roles"]
    role_claim: "realm_access.roles"   # chemin du claim contenant les rôles
    admin_role: "admin"
    user_role: "dev"
    username_claim: "preferred_username"

secrets:
  backend: "harpocrate"                # harpocrate|inline
  harpocrate:
    url: "https://harpocrate.yoops.org"
    api_key: "${env://HARPOCRATE_API_KEY}"   # vide => bascule auto en inline
    base_path: "devpod"                # racine des namespaces : devpod/<secret_ns>/...

devpod:
  binary: "/usr/local/bin/devpod"
  defaults:
    ide: "openvscode"
    idle_timeout: "2h"
    dotfiles: ""
  client_cert_path: "/data/certs/portal"   # contient ca.pem, cert.pem, key.pem (DOCKER_CERT_PATH)

hosts:                                  # ADMIN ONLY
  - name: "local"
    default: true
    type: "docker-tls"                  # docker-tls|ssh
    docker_host: "tcp://192.168.1.50:2376"
    # certs lus depuis devpod.client_cert_path (cert CLIENT partagé du portail)
  - name: "pve1"
    type: "ssh"
    address: "devops@192.168.1.40"
    key_path: "/data/keys/hosts/pve1_ed25519"

caddy:
  admin_api: "http://caddy:2019"        # API admin pour pousser les routes

cloudflare_manager:
  url: "http://cloudflare-manager:8000"
  api_key: "${env://CFM_API_KEY}"
```

## `users/<login>/config.yaml`

```yaml
version: "1"
secret_ns: "a3f8c1d2-..."              # GUID immuable, généré au 1er login. NE JAMAIS dériver du login.

defaults:
  ide: "openvscode"                     # override des defaults globaux
  idle_timeout: "4h"

harpocrate:
  api_key: ""                           # optionnel : coffre perso ; vide => clé globale

git_credentials:
  - name: "github-perso"
    host: "github.com"
    kind: "ssh"                         # ssh|token
    key_path: "keys/git/github_ed25519" # RELATIF au répertoire user
  - name: "gitlab-pickup"
    host: "gitlab.example"
    kind: "token"
    username: "gael"
    token: "${vault://git/gitlab_token}"   # relatif => devpod/<secret_ns>/git/gitlab_token

workspaces:
  - name: "agflow"                      # <name> seul ; le portail préfixe en <login>-<name>
    source: "git@github.com:gaelgael5/ag.flow.git"
    branch: "main"
    git_credential: "github-perso"
    host: "local"                       # doit exister dans hosts global ET être autorisé
    template: "python-uv"               # OU devcontainer_path
    devcontainer_path: ""
    recipes: ["claude-code", "aider"]   # noms de Features (registre portail)
    ide: "openvscode"
    idle_timeout: "4h"
    env:
      ANTHROPIC_API_KEY: "${vault://llm/anthropic_key}"
    expose:
      hostname: ""                      # "" => auto: ws-<login>-<name>.<base_domain>
```

## Contrat du résolveur de secrets

Signature : `resolve(value: str, scope: Scope) -> str` où `scope` porte `secret_ns` et le backend.

Règles **strictes** (testables) :
1. Si `value` ne matche pas `^\$\{(vault|env)://(.+)\}$` → renvoyer `value` tel quel (littéral / fallback inline).
2. `${env://VAR}` → `os.environ["VAR"]`, erreur explicite si absent.
3. `${vault://PATH}` en **scope user** → préfixe imposé : `base_path/secret_ns/PATH`.
   - `PATH` ne doit JAMAIS commencer par `/`, contenir `..`, ni `secret_ns` d'autrui → rejet (voir pièges).
4. `${vault://PATH}` en **scope global/admin** → `PATH` absolu sous `base_path`, pas de préfixe user.
5. Backend `inline` : lit `users/<login>/secrets.yaml` (scope user) ou `config global` ; même grammaire de path.
6. **Le résultat résolu ne doit jamais être loggé.** Le résolveur renvoie un type `Secret` (wrapper
   avec `__repr__`/`__str__` masqués) que seul le point d'injection déballe.

## Modèles pydantic — exigences
- `extra="forbid"` partout (détecte les fautes de frappe dans le YAML, fréquentes côté user).
- Validation custom : `workspace.name` ∈ `^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$` (DNS-safe).
- `host` référencé par un workspace doit exister dans `hosts` global → validation au chargement
  combiné (pas isolément, car les deux fichiers sont séparés).
- Écriture de config = **write atomique** (`tempfile` + `os.replace`) — voir `03_PITFALLS.md` §État.
