# SPEC — État & orchestration des sessions agent (devpod-ui)

> Fonctionnalité : rendre observable l'état d'une session agent (occupé / au repos / terminé /
> bloqué) et permettre au portail de détecter qu'un agent s'est arrêté sans finir sa tâche —
> **de façon agent-agnostique** (claude, codex, aider, gemini-cli, opencode, goose…).
> Repo : `gaelgael5/devpod-ui` — branche `dev` — commits conventionnels en français.
>
> Références : `24-mcp-devpod.md` / `25-mcp-devpod-complement.md` (primitives `session_*`),
> `29-backlog-remediation-mcp.md` (backlog MCP), recettes agent (`recipes/`).

---

## 1. Contexte & problème

Le portail sait **lancer** une tâche sur une session (`session_send`) mais pas **suivre** son
exécution. Découvert en test réel en dispatchant une tâche à un agent :

1. **Validation du `send`** : un gros prompt envoyé via `session_send(submit=true)` arrive en
   *bracketed-paste* et n'est **pas soumis** — l'`Enter` est avalé par le collage. Il a fallu
   un second appel pour valider.
2. **Aucun état d'agent** : `session_get` ne renvoie que `alive: true`. Impossible de savoir si
   l'agent travaille, a fini, ou s'est arrêté au milieu — sans parser l'écran.

**Contrainte structurante** : `session_open` est agent-agnostique. Toute détection basée sur le
rendu d'un TUI précis (ex. `esc to interrupt` de Claude Code) se couple à cet agent et casse sur
Codex/Aider. La solution doit s'appuyer sur ce qui est **commun à tous** : le PTY et git.

---

## 2. Décisions tranchées (ne pas re-débattre)
1. **Ne pas dériver l'état du rendu de l'agent.** Pas de parsing de TUI comme source de vérité
   (couplage par agent). Le rendu spécifique n'est toléré qu'en **optimisation opportuniste** (§7).
2. **L'activité se lit sur le PTY**, dénominateur commun : un agent qui travaille écrit sur son
   pane, un agent au repos n'écrit plus (§4).
3. **La complétion est une convention imposée par le portail, pas un signal offert par l'agent.**
   On l'obtient via un marqueur vérifiable en git (`Task-Done`), indépendant du TUI (§5).
4. **Découpage des responsabilités** : la session dit « ça bouge ou pas » ; le portail dit « la
   tâche est finie ou pas ». `session_get` ne connaît pas les tâches (§6).

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

## 4. Enrichissement `session_get` — activité portable

`session_get` calcule et renvoie deux champs **sans aucune connaissance de l'agent** :

| Champ        | Méthode (portable) | Valeurs |
|--------------|--------------------|---------|
| `activity`   | Hash de `capture-pane` comparé sur un court intervalle (~1 s) : identique ⇒ stable, différent ⇒ écrit. | `busy` \| `idle` |
| `foreground` | `tmux display -p '#{pane_current_command}'` | ex. `claude`, `codex`, `bash` |

- `activity=busy` ⇔ le pane change (tokens qui streament, sortie d'outil). Robuste : l'agent
  s'anime même pendant un long appel d'outil, pas de faux « figé ».
- `activity=idle` ⇔ pane stable → l'agent n'écrit plus (fini **ou** en attente).
- `foreground` retombé sur `bash`/`zsh` (plus l'agent) ⇒ l'agent a rendu la main / a crashé.

Ces deux signaux sont valables pour **n'importe quel** agent lancé en tmux.

> Implémentation : deux `capture-pane -p` espacés, comparés par hash. Alternative : hook
> d'activité tmux (`pane-`), mais le double-capture est plus simple et suffisant.

---

## 5. Convention de complétion & registre de tâches (portail)

`activity=idle` **ne suffit pas** : un agent au repos peut avoir légitimement fini. Distinguer
« fini » de « arrêté au milieu » exige un signal de complétion — imposé par le portail, donc
agent-agnostique :

- **Marqueur `Task-Done`** : chaque tâche dispatchée reçoit la consigne de **terminer par un
  trailer de commit** `Task-Done: <task_id>`. Vérifiable via `git log` — totalement indépendant
  du TUI, et les agents committent déjà.
- **Registre de tâches** (table PostgreSQL, asyncpg) : le portail enregistre à chaque dispatch
  `{ task_id, workspace, session, dispatched_at, status }` et considère la tâche `en_cours`
  jusqu'à détection du marqueur.

```sql
CREATE TABLE agent_task (
  task_id       text PRIMARY KEY,
  workspace     text NOT NULL,
  session       text NOT NULL,
  dispatched_at timestamptz NOT NULL DEFAULT now(),
  status        text NOT NULL DEFAULT 'en_cours',   -- en_cours|done|stalled|exited
  updated_at    timestamptz NOT NULL DEFAULT now()
);
```

---

## 6. Dérivation de l'état de tâche (croisement session × registre)

Le portail croise l'activité de session (§4) avec le registre (§5) :

| `activity` | `Task-Done` présent | `foreground` | → état de tâche |
|------------|---------------------|--------------|-----------------|
| `busy`     | —                   | agent        | **en_cours**    |
| `idle`     | oui                 | agent        | **done**        |
| `idle`     | non                 | agent        | **stalled**     |
| —          | non                 | shell        | **exited**      |

- **`stalled`** = l'agent ne travaille plus mais la tâche n'est pas bouclée. Recouvre **à la fois**
  la procrastination et l'attente d'input : indiscernables par la seule activité du pane, et de
  toute façon **même action humaine** — « l'agent s'est arrêté sans finir, va voir ». On ne
  cherche pas à les séparer côté observation (les séparer imposerait de lire le TUI).
- **`exited`** = le process agent a rendu la main au shell (crash / fin anormale).
- Raffinement optionnel : un **seuil** (`idle` depuis > N min avec tâche `en_cours`) avant de
  classer `stalled`, pour éviter d'alerter sur un idle transitoire.

Un état `stalled`/`exited` sur une tâche `en_cours` est **remonté à l'humain** (notification).

---

## 7. Optimisation opportuniste (jamais une dépendance)

Si le portail **reconnaît** le marqueur d'activité d'un agent connu (ex. `esc to interrupt` de
Claude Code), il peut s'en servir pour un `busy` plus immédiat. Mais c'est un **raccourci** : en
son absence (Codex, Aider, agent inconnu), on retombe **toujours** sur le hash de pane (§4). La
correction de l'état ne dépend jamais de la reconnaissance d'un TUI.

---

## 8. Contraintes & conventions
- pydantic v2 `extra="forbid"` ; asyncpg direct (pas de SQLAlchemy/Alembic) ; structlog JSON.
- Fichiers ≤ 300 lignes ; migrations additives ; commits conventionnels FR sur `dev`.
- Aucune dépendance à un TUI d'agent spécifique dans le chemin nominal.

## 9. Critères d'acceptation
1. `session_send(text=<gros prompt>, submit=true)` soumet la tâche **en un seul appel** (le
   correctif §3 valide après le collage).
2. `session_get` renvoie `activity` (`busy`/`idle`) et `foreground`, identiques pour un agent
   `claude` **et** un agent `codex` en train de travailler / au repos.
3. Un agent qui rend la main au shell fait passer `foreground` de l'agent à `bash`.
4. Une tâche dont le commit final porte `Task-Done: <id>` passe `done` ; sans marqueur et pane
   stable, elle passe `stalled` et déclenche une remontée à l'humain.
5. Le chemin nominal de détection ne lit aucun élément de rendu spécifique à un agent.

## 10. Points à confirmer à l'implémentation
- Intervalle et méthode exacts du hash de pane (double `capture-pane` vs hook tmux).
- Emplacement de la consigne `Task-Done` : injectée par le portail au dispatch, ou portée par
  les recettes agent (`recipes/`).
- Seuil temporel de bascule `idle`→`stalled` (valeur par défaut).
- Canal de notification « tâche stalled/exited » vers l'humain (réutiliser le mécanisme existant
  du portail).
