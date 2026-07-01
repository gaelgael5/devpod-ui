# SPEC — État mécanique des sessions agent (devpod-ui)

> Fonctionnalité : rendre observable, de façon **agent-agnostique** et **sans coopération de
> l'agent**, le seul état d'une session qui soit fiable — un traitement est-il en cours ou non —
> plus le correctif de validation de `session_send`.
> Repo : `gaelgael5/devpod-ui` — branche `dev` — commits conventionnels en français.
>
> Références : `24-mcp-devpod.md` / `25-mcp-devpod-complement.md` (primitives `session_*`),
> `29-backlog-remediation-mcp.md` (backlog MCP).

---

## 1. Contexte & périmètre

Le portail lance des tâches sur des sessions (`session_send`) mais ne peut pas suivre leur état.
Découvert en test réel : (1) un gros prompt en `submit=true` n'est **pas validé** (le
bracketed-paste avale l'`Enter`) ; (2) `session_get` ne renvoie que `alive: true`.

**Périmètre STRICT de cette spec : le socle mécanique**, celui qui ne dépend d'aucun comportement
d'agent. La *sémantique* de l'arrêt (« a fini » / « attend une réponse » / « bloqué ») est
explicitement **hors périmètre** (§5) : elle relève d'une lecture contextuelle et d'un protocole
comportemental, traités séparément et plus tard.

---

## 2. Décisions tranchées (ne pas re-débattre)
1. Le seul état observable et honnête est **traitement en cours / pas de traitement**. On le
   nomme **`processing: bool`**, pas `busy|idle` — `idle` suggérerait à tort une disponibilité.
2. **`processing=false` ne signifie PAS « libre ».** C'est un état volontairement ambigu qui
   recouvre au moins « a fini », « attend une réponse » et « bloqué », indistinguables au niveau
   PTY. La spec **n'essaie pas** de lever cette ambiguïté (§5).
3. Détection **portable** via le PTY, commun à tous les agents (claude / codex / aider / …).
   Aucun parsing de TUI spécifique dans le chemin nominal.
4. Le **comportement** de l'agent (marqueurs de fin de tour, etc.) est écarté ici : une directive
   comportementale s'érode avec la longueur de contexte, elle ne peut donc pas *fonder* la
   détection d'état. Elle sera traitée à part.

---

## 3. Correctif `session_send` — validation après collage

Quand `submit=true`, émettre **deux `send-keys` distincts** avec un court délai, au lieu d'un
seul (l'`Enter` collé dans la même séquence est absorbé par le bracketed-paste) :

```bash
tmux send-keys -t <pane> -l "<texte>"   # 1) texte en littéral (-l)
sleep 0.1                                # 2) laisse le TUI clôturer le bracketed-paste
tmux send-keys -t <pane> Enter           # 3) Enter propre = validation
```

- Le délai (~100 ms) est nécessaire : sans lui, l'`Enter` peut arriver avant la clôture du paste
  et se refaire avaler.
- Cas limites : `text=""` + `submit=true` → étape 3 seule ; `submit=false` → étape 1 seule.

---

## 4. `session_get` — champs mécaniques

`session_get` calcule et renvoie deux champs **sans aucune connaissance de l'agent** :

| Champ        | Méthode (portable)                                                     | Valeurs |
|--------------|------------------------------------------------------------------------|---------|
| `processing` | Hash de `capture-pane` comparé sur un court intervalle (~1 s) : change ⇒ `true`, stable ⇒ `false`. | `bool` |
| `foreground` | `tmux display -p '#{pane_current_command}'`                            | ex. `claude`, `codex`, `bash` |

- `processing=true` ⇔ le pane change (tokens qui streament, sortie d'outil). Robuste : l'agent
  s'anime même pendant un long appel d'outil — pas de faux « figé ».
- `processing=false` ⇔ pane stable. **Rien de plus n'est affirmé** (voir §2 et §5).
- `foreground` retombé sur `bash`/`zsh` (plus l'agent) ⇒ l'agent a rendu la main. Fait
  **factuel** (process en avant-plan), non comportemental.

> Implémentation : deux `capture-pane -p` espacés, comparés par hash. Alternative : hook
> d'activité tmux, mais le double-capture est plus simple et suffisant.

---

## 5. Ce que la spec n'affirme PAS (limite assumée)

- Elle **ne déduit pas « libre »**. `processing=false` n'autorise personne à conclure « disponible
  pour une nouvelle tâche ».
- Elle **ne distingue pas** fini / en attente / bloqué. Cette désambiguïsation exige de **lire le
  dernier message** de la session (interprétation contextuelle) et repose sur un **protocole de
  fin de tour** côté agent — les deux hors périmètre, à traiter dans une spec ultérieure.
- **Corollaire à documenter dans la primitive** : tout consommateur qui voit `processing=false`
  doit lire le contexte récent avant d'agir ; il ne doit jamais traiter cet état comme « libre ».

---

## 6. Contraintes & conventions
- pydantic v2 `extra="forbid"` ; asyncpg direct (pas de SQLAlchemy/Alembic) ; structlog JSON.
- Fichiers ≤ 300 lignes ; additif ; commits conventionnels FR sur `dev`.
- Aucune dépendance à un TUI d'agent spécifique dans le chemin nominal.

## 7. Critères d'acceptation
1. `session_send(text=<gros prompt>, submit=true)` soumet la tâche **en un seul appel** (§3).
2. `session_get` renvoie `processing` (`bool`) et `foreground`, cohérents pour un agent `claude`
   **et** un agent `codex`, qu'ils traitent ou non.
3. Un agent qui rend la main au shell fait passer `foreground` de l'agent à `bash`.
4. `processing=false` n'est **jamais** exposé ni documenté comme « libre » ; la description de
   `session_get` rappelle explicitement la limite du §5.
