# Tâche d'implémentation — vérifier l'identité on-behalf-of (OBO) côté service MCP

**Destinataires :** équipes/agents **docflow**, **rag**, **workflow**.
**Émetteur :** portail devpod (la passerelle MCP). Côté portail, c'est **fait et déployable** (branche `dev`).
**But :** que les objets créés via les tools MCP (contextes, documents…) soient attribués à **l'utilisateur humain** réel, et non à `mcp-agent` / à l'owner de la clé API partagée.

---

## 1. Contexte (le problème résolu)

Quand un agent appelle un tool MCP à travers la passerelle, celle-ci s'authentifie auprès du
service avec **une clé API** (identité machine). L'identité humaine du pilote est perdue en
chemin → vos créations sont rattachées à `mcp-agent`, invisibles pour l'utilisateur une fois
qu'il se connecte.

La passerelle sait pourtant **qui** est l'humain (son OAuth/login). Elle va désormais le
**propager de façon signée** dans chaque appel sortant, pour les backends marqués « de
confiance ». **À vous de lire et vérifier cette identité, puis de l'estampiller.**

---

## 2. Contrat des en-têtes (normatif)

Sur les appels MCP émis par la passerelle (quand `forward_identity` est activé pour votre
backend), **trois en-têtes HTTP** sont ajoutés, **en plus** de l'authentification habituelle
(`Authorization: Bearer <clé>` ou `X-API-Key: <clé>`) :

| En-tête | Contenu |
|---|---|
| `x-portal-actor` | le principal humain — **le sub OIDC** (`users.sub`, claim `sub` de Keycloak) : ancre d'identité **stable et immuable**, contrairement au login/email qui peuvent changer. Opaque. |
| `x-portal-actor-timestamp` | instant d'émission, **unix secondes** (entier, en clair) |
| `x-portal-actor-signature` | `HMAC-SHA256` **hex** de la charge canonique, avec le secret partagé |

> Le `sub` est l'identifiant **stable** choisi exprès (login et email sont mutables → jamais utilisés comme clé d'identité). Comme workflow/rag/docflow sont derrière le **même Keycloak** que le portail, ce `sub` est une clé d'identité **partagée** entre tous : chaque service mappe `x-portal-actor` sur son utilisateur **par le même sub OIDC**.

**Charge canonique signée (octets exacts) :**

```
<actor> + "\n" + <timestamp>
```

soit, en Python : `f"{actor}\n{timestamp}".encode()`. Aucune autre sérialisation, pas d'espaces.

**Secret de signature = la clé API que la passerelle utilise pour s'authentifier chez vous.**
C'est la clé que **vous avez émise** pour ce client et que **seul le portail détient**. Vous la
connaissez donc déjà (c'est celle du header `Authorization`/`X-API-Key` du même appel). Un
client tiers ne la connaît pas → **il ne peut pas forger la signature**. C'est toute la sécurité
du mécanisme.

> Même algorithme HMAC-SHA256 que le relais d'events du portail (header `x-signature`).

### Vecteur de test (interop byte-for-byte)

```
actor     = "gael"
timestamp = 1763000000
secret    = "shared-key-EXAMPLE"

payload signé = b"gael\n1763000000"

x-portal-actor:            gael
x-portal-actor-timestamp:  1763000000
x-portal-actor-signature:  6c1a34eb1b1ca3d9be66ea366460a397e5a684fa647f302368cc7237e8ec93ae
```

Si votre implémentation reproduit cette signature avec ce secret, vous êtes compatible.

---

## 3. Ce que le service DOIT faire

1. **Vérifier avant de faire confiance.** Reconstruire `HMAC-SHA256(f"{actor}\n{ts}", clé_partagée)`
   et comparer en **temps constant** (`hmac.compare_digest`) à `x-portal-actor-signature`.
2. **Anti-rejeu.** Rejeter si `|now − timestamp|` dépasse une fenêtre courte (**recommandé : 300 s**).
3. **Fail-safe, pas fail-open aveugle.** Signature **absente ou invalide** → **ignorer** l'identité
   propagée et retomber sur le comportement actuel (identité = clé). **Ne jamais** renvoyer 401 pour
   ça (l'appel authentifié par la clé reste légitime), et **ne jamais** faire confiance à
   `x-portal-actor` **sans** signature valide.
4. **Estampiller.** Quand la signature est valide, utiliser `actor` comme principal :
   - `require_authenticated` (ou équivalent) expose cet `actor` comme utilisateur courant ;
   - à la création (`context_create`, `def_create`, création de document…), inscrire **`actor`**
     comme membre `owner`, **au lieu de** `mcp-agent`.
5. **Mapper l'identité.** `actor` = le **sub OIDC** (claim `sub` Keycloak). Le rapprocher de votre
   référentiel utilisateur **par le même sub** (vous êtes derrière le même Keycloak). Créer
   l'utilisateur à la volée si absent, ou refuser proprement selon votre politique. **Ne jamais**
   mapper sur le login/email (mutables).

### Invariants de sécurité (non négociables)

- L'identité forwardée n'est acceptée **que** si la signature est valide. Un `x-portal-actor`
  seul (sans signature, ou signature KO) = **anonyme**, jamais l'utilisateur nommé.
- Ne **jamais** accepter un `author`/acteur fourni **en clair dans le corps** d'un tool comme
  source d'identité : ce serait de l'usurpation en une ligne. La seule source = l'en-tête **signé**.
- La fenêtre temporelle protège du rejeu ; imposez `Date` synchronisée (NTP).

---

## 4. Spécifique par service

### workflow (agflow)
- Middleware `McpApiKeyMiddleware` sur `/mcp` : ajouter la vérification des 3 en-têtes juste après
  la validation de la clé (la clé validée EST le secret de signature).
- `context_create` inscrit aujourd'hui `author or "mcp-agent"` → renseigner `author = actor` vérifié.
- **Amorçage** : prévoir une capacité d'**ajout de membre / partage** (ou un accès admin) pour
  rapatrier les contextes déjà créés sous `mcp-agent` — sinon l'utilisateur ne peut pas s'ajouter à
  un contexte qu'il ne voit pas.

### docflow
- Point d'auth du mount MCP (`/api/mcp/sse`) : même vérification.
- Création de documents/blocs : membre/propriétaire = `actor` vérifié au lieu de l'identité de la clé.

### rag
- Le MCP est monté sous `/mcp/` (endpoints SSE `/mcp/sse` + `/mcp/messages`), auth `Authorization: Bearer`.
- Ajouter la vérification des en-têtes au même endroit ; rattacher les objets indexés/wokspaces créés
  à `actor`.

---

## 5. Activation & séquencement

- Côté **portail** : un interrupteur **« Propager mon identité (on-behalf-of) »** par backend
  (Sécurité → MCP → éditer le backend). Tant qu'il est **off**, rien ne change pour vous.
- Séquence conseillée : (1) vous implémentez la **vérification tolérante** (signature absente =
  comportement actuel) et déployez ; (2) on **active** le flag côté portail ; (3) vous basculez
  l'estampillage sur `actor`. Aucune fenêtre de casse si l'étape 1 est bien fail-safe.

---

## 6. Definition of Done (par service)

- [ ] Vérification HMAC + fenêtre anti-rejeu, en temps constant.
- [ ] Signature absente/invalide → identité ignorée, appel toujours servi (pas de 401).
- [ ] Corps de tool jamais utilisé comme source d'identité.
- [ ] Création → membre `owner` = `actor` vérifié.
- [ ] Mapping `actor` → utilisateur du référentiel.
- [ ] (workflow) capacité de partage/rapatriement des objets `mcp-agent` existants.
- [ ] Test d'interop passé contre le vecteur du §2.
