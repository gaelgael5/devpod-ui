# Terminal SSH — géométrie : nudge côté serveur et resize après drain

**Goal:** Supprimer les deux causes racines du décalage de lignes / texte entrelacé dans le
terminal SSH web, mesurées dans les logs de production du 03/09/2026 :

1. le nudge (aller-retour `rows-1` → `rows`) est émis en deux trames WebSocket que le réseau
   regroupe : les deux `TIOCSWINSZ` arrivent à 0–13 ms d'écart, `SIGWINCH` — qui n'est pas mis
   en file — est coalescé, tmux ne voit qu'un changement de taille (ou aucun) et ne repeint pas ;
2. le redimensionnement part sans attendre le vidage de la file de parsing d'xterm : la sonde
   `octets` a mesuré 4580 octets en attente pendant un nudge, octets émis par tmux pour
   l'ancienne géométrie et analysés contre la nouvelle ;
3. **le nudge est déclenché alors que rien n'a bougé** — depuis `6bada4d7` (03/09 09:08), un
   simple `focus` de fenêtre en déclenche un. Sur desktop, un alt-tab suffit.

**C'est une régression, pas un défaut ancien : l'affichage était sain, il a cessé de l'être.**

| Quand | Commit | Effet |
|---|---|---|
| 01/09 22:24 | `159aa506` | `planifierAjustement` passe de `refresh()` local au nudge. Déclencheurs : `window.resize`, `ResizeObserver`, `visualViewport` — sur desktop sans redimensionnement, quasi jamais |
| **03/09 09:08** | **`6bada4d7`** | **`onVisible` (`focus`, `visibilitychange`, `pageshow`) appelle `planifierAjustement` : un nudge par alt-tab** |

Le nudge étant non fiable (cause 1), chaque déclenchement est une chance de laisser tmux calé à
`rows-1` pendant que le PTY et xterm sont à `rows`. Tant qu'il était rare, le défaut restait
invisible ; depuis 09:08 il part à chaque retour dans la fenêtre. Le commit qui voulait faire
repeindre l'écran au retour d'onglet est celui qui a généralisé le symptôme qu'il corrigeait —
les résidus de deux caractères en colonne 0 décrits dans son propre message.

**Preuves (Loki, `compose_service="portal"`, 03/09/2026) :**

```
15:35:35.725 ws_workspace_ssh_resize_applied cols=265 rows=64 haut=1023 vv=1060
15:35:35.725 ws_workspace_ssh_resize_applied cols=265 rows=65 haut=1023 vv=1060   ← 0 ms
15:17:10.789 ws_ssh_resize_applied           cols=54  rows=48 haut=747  vv=796
15:17:10.789 ws_ssh_resize_applied           cols=54  rows=49 haut=747  vv=796    ← 0 ms
15:36:27.890 ws_workspace_ssh_resize_applied cols=265 rows=64 octets=4580
15:36:27.928 ws_workspace_ssh_resize_applied cols=265 rows=65 octets=4580
```

Aucun `pty_set_size_failed` sur 24 h : le pont applique bien tout ce qu'il reçoit. Le défaut est
dans le *quand*, pas dans le *si*.

**Architecture:** l'espacement des deux `TIOCSWINSZ` remonte côté backend, seul endroit où le
temps est maîtrisé — le client ne contrôle pas la livraison de ses trames. Le client cesse
d'émettre deux trames et pose un drapeau `nudge: true` sur la trame `resize` qui existe déjà
(aucune trame de contrôle supplémentaire : la leçon du 03/09, une trame en plus fermait la
session à chaque ouverture du clavier mobile). Côté client, tout recalage attend que la file de
parsing d'xterm soit vide.

**Compatibilité de déploiement (les deux sens) :** un backend antérieur ignore `nudge` et
applique la taille finale — pas de repaint, pas de casse. Un client antérieur envoie ses deux
trames sans `nudge` — comportement actuel. L'ordre de déploiement est donc libre.

**Tech Stack:** Python 3.12 asyncio, structlog, pytest-asyncio ; React 18, xterm 6, Vitest.

---

## Structure des fichiers

| Fichier | Action |
|---------|--------|
| `backend/src/portal/sessions/pty_bridge.py` | Modifier — `NUDGE_DELAY_S`, nudge asynchrone annulable |
| `backend/tests/sessions/test_pty_bridge.py` | Modifier — tests de coalescence (vrai PTY, aucun mock) ; le fichier existait déjà avec ce harnais, pas de `test_sigwinch.py` séparé |
| `backend/tests/test_pty_bridge.py` | Modifier — `_FakeWebSocket(garder_ouvert=)` + 5 tests |
| `frontend/src/features/terminal/parseQueue.ts` | Créer — file de parsing xterm, `quandVide` |
| `frontend/src/features/terminal/parseQueue.test.ts` | Créer — tests unitaires purs |
| `frontend/src/features/terminal/FullscreenTerminal.tsx` | Modifier — Task 0 (garde sur le masquage) puis Task 3 (une seule trame, recalage après drain) |
| `frontend/src/features/terminal/FullscreenTerminal.test.tsx` | Modifier — mock `write` avec callback, 4 tests réécrits |
| `LESSONS.md` | Modifier — leçon SIGWINCH coalescé |

**Hors périmètre, à découper à part :** `FullscreenTerminal.tsx` fait 858 lignes contre 300 au
plafond du projet. Ce plan en retire la mécanique de file de parsing ; le découpage complet du
composant est un chantier distinct, à ne pas mélanger à une correction de bug.

---

## Task 0 : Arrêter la régression — ne pas nudger quand rien n'a bougé

**Files:**
- Modify: `frontend/src/features/terminal/FullscreenTerminal.tsx`
- Modify: `frontend/src/features/terminal/FullscreenTerminal.test.tsx`

Petite, déployable seule, et elle restaure l'usage courant sans attendre le reste. Ce n'est pas
un pis-aller : nudger une géométrie qui n'a pas changé est faux en soi — deux `SIGWINCH` pour
rien, dont un peut se perdre.

`focus` sert aujourd'hui à deux choses dans `onVisible` : détecter une socket morte au retour
(à garder — Safari coupe la WebSocket en arrière-plan sans toujours livrer le `close`) et
recaler la géométrie (à conditionner). Un clic qui redonne le focus à une fenêtre jamais masquée
ne justifie aucun recalage.

### Étape 0.1 — Tests rouges

```ts
it('ne recale pas sur un focus sans que la page ait ete masquee', () => {
  // Un alt-tab qui ne masque pas l'onglet : aucune trame ne doit partir.
  // C'est la régression du 03/09 09:08 (6bada4d7).
})

it('recale au retour d\'un onglet REELLEMENT masque', () => {
  // document.hidden = true, visibilitychange, puis retour → le nudge part.
  // Là, tmux a pu peindre pendant que les géométries divergeaient.
})

it('verifie la socket a chaque focus, masquage ou non', () => {
  // La détection de socket morte ne doit PAS être conditionnée au masquage.
})
```

- [x] Écrire les trois tests

### Étape 0.2 — Implémenter

- [x] Poser un drapeau `aEteMasquee` dans le gestionnaire `visibilitychange` quand
      `document.hidden` devient vrai
- [x] Dans `onVisible` : la vérification de socket reste inconditionnelle ; l'appel à
      `planifierAjustement()` est gardé par `aEteMasquee`, qui est ensuite consommé
- [x] Commenter le *pourquoi* : le nudge n'est pas gratuit, chaque déclenchement est une
      occasion de désynchroniser tmux tant que la cause 1 n'est pas corrigée

```bash
cd frontend && npx vitest run src/features/terminal/ && npm run lint && npx tsc --noEmit
```

- [ ] Déployer sur test1 et **confirmer avec l'utilisateur que l'affichage redevient sain**
      avant d'attaquer la suite

---

## Task 1 : Backend — le nudge devient serveur, avec un vrai délai

**Files:**
- Modify: `backend/src/portal/sessions/pty_bridge.py`
- Modify: `backend/tests/test_pty_bridge.py`

### Contrat

Trame reçue : `{"type":"resize","cols":265,"rows":65,"nudge":true,"haut":1023,"vv":1060,"octets":0}`

- `nudge` absent ou faux → comportement actuel : une seule application de taille.
- `nudge: true` et `rows > 1` → application immédiate de `(cols, rows-1)`, puis, après
  `NUDGE_DELAY_S`, application de `(cols, rows)`. Deux `SIGWINCH` séparés par un délai réel :
  tmux traite le premier, redessine, puis traite le second.
- `rows == 1` → pas de `rows-1` (taille nulle interdite) : application directe.
- **Annulation** : une trame de contrôle qui demande une taille *différente* de la taille finale
  du nudge en vol l'annule. Une trame qui demande la *même* taille finale ne l'annule pas — le
  `onResize` d'xterm émet sa propre trame juste avant le nudge, et l'ordre d'arrivée ne doit pas
  pouvoir tuer le repaint.
- **Teardown** : la tâche du nudge est annulée à la fermeture du pont, sinon elle écrit sur un
  descripteur fermé (`EBADF` journalisé pour rien).

`NUDGE_DELAY_S = 0.08` — valeur de départ, à confirmer sur test1 en Task 4.

### Étape 1.0 — Test système : établir la coalescence, sans aucun mock

Les tests des étapes suivantes remplacent `set_pty_size` par un espion : ils vérifient que le
pont fait ce qu'on a décidé, jamais que le noyau se comporte comme on le croit. Ce test-ci ne
mocke rien — vrai PTY, vrai processus, vrais signaux — et c'est le seul qui établisse la cause
racine.

Mesure faite le 03/09/2026 sur la machine de dev, avant écriture du plan :

```
delai=  0.0s -> COUNT=1      ← deux TIOCSWINSZ, UN seul SIGWINCH délivré
delai=0.005s -> COUNT=2
delai= 0.08s -> COUNT=2
```

Les tests vont dans `backend/tests/sessions/test_pty_bridge.py`, qui porte déjà ce harnais
(vrai PTY, vrai enfant, vrais signaux) et ses helpers `_read_line` / `_set_size` :

```python
"""SIGWINCH est-il vraiment coalescé ? Test système, sans mock.

Tout le reste de la correction repose sur cette propriété du noyau : SIGWINCH
n'est pas un signal temps réel, il n'est donc pas mis en file. Deux changements
de taille appliqués avant que le processus n'ait traité le premier ne lui font
voir qu'un seul signal — et tmux, ne voyant qu'un changement (vers la taille
FINALE, celle qu'il a déjà), ne redessine rien.

Mesuré en production le 03/09/2026 : les deux trames du nudge arrivaient à 0 ms
d'écart. Ce test échoue si le noyau change de comportement, ou si quelqu'un
raccourcit `NUDGE_DELAY_S` en croyant que l'espacement est décoratif.
"""

ENFANT = """
import signal, sys, time
n = 0
signal.signal(signal.SIGWINCH, lambda *_: globals().__setitem__('n', n + 1))
sys.stderr.write('READY\n'); sys.stderr.flush()
time.sleep({duree})
sys.stderr.write(f'COUNT={{n}}\n'); sys.stderr.flush()
"""


def _signaux_recus(delai: float) -> int:
    """Compte les SIGWINCH vus par un enfant pour deux changements de taille."""
    # openpty + setsid + TIOCSCTTY : sans terminal de contrôle, le signal
    # n'est adressé à aucun groupe de processus (cf. _attach_controlling_tty).
    ...


def test_deux_redimensionnements_colles_ne_font_qu_un_signal():
    """La cause racine, reproduite : c'est pour ça que tmux ne repeignait pas."""
    assert _signaux_recus(0.0) == 1


def test_le_delai_du_pont_fait_bien_delivrer_deux_signaux():
    """Et la correction, vérifiée sur la valeur réellement utilisée."""
    from portal.sessions.pty_bridge import NUDGE_DELAY_S

    assert _signaux_recus(NUDGE_DELAY_S) == 2
```

**Ce que ce test ne prouve pas :** qu'une valeur donnée de `NUDGE_DELAY_S` suffit *pour tmux*.
L'enfant ci-dessus est oisif et traite son signal aussitôt ; tmux, occupé à dessiner, a une
fenêtre de coalescence bien plus large — 5 ms d'écart produisaient déjà le symptôme en
production alors que ce test passe à 5 ms. Le dimensionnement du délai reste donc la Task 4,
sur logs réels. Ce test établit le mécanisme, pas la marge.

- [x] Ajouter `_CHILD_OCCUPE` (bloque SIGWINCH le temps d'une « frame ») et sa fixture
- [x] `test_deux_redimensionnements_colles_ne_font_voir_aucun_changement` — vert AVANT correction
- [x] `test_espaces_du_delai_du_pont_les_deux_signaux_sont_delivres`

Le masque de signal rend le test déterministe : sans lui, la coalescence dépend de
l'ordonnanceur et le test serait instable. Un processus qui n'a pas encore traité son signal
est exactement la situation de tmux en train de dessiner.

```bash
cd backend && uv run pytest tests/sessions/test_pty_bridge.py -v
# Le PREMIER test passe AVANT toute correction : il décrit le monde tel qu'il est. Constaté.
```

### Étape 1.1 — Test rouge : le nudge applique la taille réduite puis la vraie

Ajouter dans `backend/tests/test_pty_bridge.py` un fake qui garde le pont vivant (les tests
actuels débitent leurs trames puis se déconnectent, ce qui annulerait le nudge avant son terme) :

```python
class _FakeWebSocket:
    """Websocket minimal : débite les trames fournies puis se déconnecte.

    `garder_ouvert` retient la déconnexion : le nudge est asynchrone, un pont qui
    se démonte aussitôt les trames lues l'annulerait avant qu'il ne s'applique.
    """

    def __init__(self, frames: list[dict], *, garder_ouvert: bool = False) -> None:
        self._frames = [*frames] if garder_ouvert else [*frames, {"type": "websocket.disconnect"}]
        self.sent: list[bytes] = []
```

(le `receive` existant dort déjà 3600 s quand la file est vide — c'est ce qu'on veut ici).

Puis le test :

```python
@pytest.mark.asyncio
async def test_le_nudge_applique_la_taille_reduite_puis_la_vraie(monkeypatch):
    """Deux SIGWINCH, pas un seul : c'est ce qui fait repeindre tmux."""
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.01)
    vues: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda _fd, cols, rows: vues.append((cols, rows)),
    )

    ws = _FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "resize", "cols": 265, "rows": 65, "nudge": True}),
            }
        ],
        garder_ouvert=True,
    )
    pont = asyncio.create_task(
        run_pty_bridge(
            ws,  # type: ignore[arg-type]
            ["sleep", "5"],
            {"TERM": "xterm", "PATH": "/usr/bin:/bin"},
            _FakeTerminal(),  # type: ignore[arg-type]
            log_label="test",
            initial_size=(80, 24),
        )
    )
    await asyncio.sleep(0.05)
    pont.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pont

    assert vues == [(265, 64), (265, 65)]
```

- [x] Ajouter `import contextlib` en tête du fichier de test
- [x] Ajouter le paramètre `garder_ouvert` à `_FakeWebSocket`
- [x] Écrire le test ci-dessus

```bash
cd backend && uv run pytest tests/test_pty_bridge.py -k nudge -v   # ROUGE
```

### Étape 1.2 — Test rouge : les deux tailles sont réellement espacées

C'est le test qui verrouille la cause racine — sans lui, une implémentation qui poserait les
deux tailles à la suite passerait 1.1.

```python
@pytest.mark.asyncio
async def test_le_nudge_espace_reellement_les_deux_tailles(monkeypatch):
    """0 ms d'écart mesuré en production : SIGWINCH coalescé, tmux ne repeint pas.

    Le délai ne peut pas être garanti côté navigateur — deux trames WebSocket
    espacées d'une frame sont livrées dans le même segment TCP. Il est donc tenu
    ici, où l'horloge est celle du processus qui pose l'ioctl.
    """
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.05)
    instants: list[float] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda *_a: instants.append(asyncio.get_event_loop().time()),
    )
    # … même montage qu'en 1.1, avec await asyncio.sleep(0.2)

    assert len(instants) == 2
    assert instants[1] - instants[0] >= 0.04
```

- [x] Écrire le test

### Étape 1.3 — Tests rouges : annulation, taille identique, `rows == 1`, teardown

```python
async def test_un_resize_vers_une_autre_taille_annule_le_nudge(monkeypatch):
    """Trames `nudge 65` puis `resize 40` : le PTY finit à 40, jamais à 65."""

async def test_un_resize_vers_la_meme_taille_laisse_le_nudge_finir(monkeypatch):
    """`onResize` d'xterm émet sa trame juste avant le nudge : l'ordre d'arrivée
    des deux ne doit pas pouvoir tuer le repaint."""

async def test_le_nudge_ne_descend_pas_a_zero_ligne(monkeypatch):
    """rows=1 → une seule application, jamais (cols, 0)."""

async def test_le_nudge_est_annule_a_la_fermeture_du_pont(monkeypatch):
    """Sinon il écrit sur un descripteur fermé et journalise un EBADF pour rien."""
```

- [x] Écrire les quatre tests

```bash
cd backend && uv run pytest tests/test_pty_bridge.py -v   # 5 ROUGES, les 4 anciens VERTS
```

### Étape 1.4 — Implémenter

Dans `pty_bridge.py`, au niveau module :

```python
# Espacement des deux TIOCSWINSZ d'un nudge. SIGWINCH n'est pas mis en file :
# deux changements de taille rapprochés sont coalescés et tmux n'en voit qu'un —
# mesuré à 0 ms d'écart en production le 03/09/2026, repaint jamais déclenché.
# Le délai est tenu ici parce que le navigateur ne peut pas le garantir : ses
# deux trames partent à une frame d'écart et arrivent dans le même segment TCP.
NUDGE_DELAY_S = 0.08
```

Dans `run_pty_bridge`, avant `_handle_control` :

```python
nudge: asyncio.Task[None] | None = None
nudge_cible: tuple[int, int] | None = None

def _annuler_nudge() -> None:
    nonlocal nudge, nudge_cible
    if nudge is not None and not nudge.done():
        nudge.cancel()
    nudge, nudge_cible = None, None

async def _nudge_puis_vraie_taille(cols: int, rows: int, sonde: dict[str, int]) -> None:
    await asyncio.sleep(NUDGE_DELAY_S)
    set_pty_size(master_fd, cols, rows)
    _log.info(f"{log_label}_resize_applied", cols=cols, rows=rows, nudge=True, **sonde)
```

Dans `_handle_control`, en remplacement de l'appel direct à `_pty_resize` :

```python
        # Une trame qui vise la MÊME taille finale ne casse pas le nudge en vol
        # (cf. onResize d'xterm, qui émet la sienne juste avant).
        if nudge_cible is not None and (cols, rows) != nudge_cible:
            _annuler_nudge()
        elif nudge_cible is not None:
            return
        if msg.get("nudge") is True and rows > 1:
            set_pty_size(master_fd, cols, rows - 1)
            nudge_cible = (cols, rows)
            nudge = asyncio.create_task(_nudge_puis_vraie_taille(cols, rows, sonde))
        else:
            _pty_resize(cols, rows)
            journaliser(...)
```

Le calcul de `sonde` remonte donc avant ce bloc (il alimente les deux chemins), et le compteur
`controls` reste borné à 20.

Dans le `finally` de `run_pty_bridge`, avant `os.close(master_fd)` : `_annuler_nudge()`.

- [x] Ajouter `NUDGE_DELAY_S` et son commentaire
- [x] Ajouter la tâche annulable et la règle d'annulation
- [x] Annuler le nudge au teardown
- [x] Remonter le calcul de `sonde` avant le branchement

```bash
cd backend && uv run pytest tests/test_pty_bridge.py tests/sessions -v   # TOUT VERT
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

---

## Task 2 : Frontend — `parseQueue.ts`, module pur et testable

**Files:**
- Create: `frontend/src/features/terminal/parseQueue.ts`
- Create: `frontend/src/features/terminal/parseQueue.test.ts`

`terminal.write(data, cb)` est asynchrone : xterm met en file et analyse plus tard. Le composant
compte déjà les octets en vol (`octetsEnAttente`) pour la sonde, mais personne ne les attend.
Ce module porte l'attente, isolément de React et d'xterm.

### API

```ts
export interface ParseQueue {
  /** Octets reçus de la WebSocket, remis à xterm. */
  arrive(n: number): void
  /** Octets analysés par xterm (rappel de `write`). */
  analyse(n: number): void
  /** Octets encore en file — c'est la sonde `octets`. */
  enAttente(): number
  /**
   * Exécute `action` dès que la file est vide, immédiatement si elle l'est déjà.
   * Une action en attente est REMPLACÉE par la suivante : c'est un recalage, pas
   * une file de travaux, et deux recalages coup sur coup, c'est la rafale de
   * SIGWINCH qu'on cherche à éviter.
   */
  quandVide(action: () => void): void
  /** Démontage : oublie l'action en attente et son minuteur. */
  dispose(): void
}

export const ATTENTE_MAX_MS = 250

export function createParseQueue(attenteMaxMs?: number): ParseQueue
```

`ATTENTE_MAX_MS` est un plafond, pas un délai : une session qui écrit en continu (`top`,
un build) ne doit pas empêcher le recalage indéfiniment. Passé ce délai, l'action part même
avec des octets en file — l'état d'aujourd'hui, donc jamais pire.

### Étape 2.1 — Tests rouges

```ts
describe('parseQueue', () => {
  it('exécute immédiatement quand la file est vide', ...)
  it('attend le vidage complet avant d\'exécuter', ...)          // arrive(100), quandVide, analyse(40) → rien ; analyse(60) → exécuté
  it('ne garde que la dernière action en attente', ...)
  it('n\'exécute qu\'une fois quand la file se vide', ...)
  it('exécute au bout du plafond si le flux ne se tarit pas', ...) // vi.useFakeTimers
  it('ne compte pas les octets en dessous de zéro', ...)          // analyse() sans arrive() → enAttente() === 0
  it('n\'exécute plus rien après dispose', ...)
})
```

- [x] Créer `parseQueue.test.ts` (neuf tests)

```bash
cd frontend && npx vitest run src/features/terminal/parseQueue.test.ts   # ROUGE
```

### Étape 2.2 — Implémenter

- [x] Créer `parseQueue.ts`

```bash
cd frontend && npx vitest run src/features/terminal/parseQueue.test.ts   # VERT
```

---

## Task 3 : Frontend — une seule trame, recalage après drain

**Files:**
- Modify: `frontend/src/features/terminal/FullscreenTerminal.tsx`
- Modify: `frontend/src/features/terminal/FullscreenTerminal.test.tsx`

### Étape 3.1 — Rendre le mock capable de reproduire le bug

`MockTerminal.write = vi.fn()` n'appelle jamais son rappel : avec ce mock, la file ne se vide
jamais et aucun test ne peut distinguer les deux comportements.

```ts
  /** Rappels de `write` non encore honorés : le test décide QUAND xterm a analysé. */
  ecritures: Array<() => void> = []
  write = vi.fn((_data: unknown, cb?: () => void) => {
    if (cb) this.ecritures.push(cb)
  })
  /** Vide la file de parsing, comme xterm le fait à son rythme. */
  draine() {
    const cbs = this.ecritures
    this.ecritures = []
    cbs.forEach((cb) => cb())
  }
```

- [x] Modifier `MockTerminal.write` et ajouter `draine()`
- [x] Vérifier que les tests existants qui comptent les `write` passent toujours

### Étape 3.2 — Tests rouges

Réécrire dans `describe('FullscreenTerminal — rafraichir l'affichage')` :

```ts
it('envoie UNE trame de nudge, pas deux tailles a la merci du reseau', () => {
  // Deux trames espacées d'une frame arrivent dans le même segment TCP :
  // SIGWINCH coalescé, tmux ne repeint pas (0 ms mesurés le 03/09).
  // Attendu : une seule trame, {type:'resize', cols, rows, nudge:true}.
})

it('ne redimensionne pas tant qu\'xterm n\'a pas analyse le flux', () => {
  // arrive 4580 octets non analysés → aucune trame ; après draine() → la trame part.
  // C'est le cas mesuré à 15:36:27 : tmux avait écrit pour l'ancienne géométrie.
})

it('recale malgre un flux continu, au bout du plafond', () => {
  // vi.useFakeTimers, jamais de draine() → la trame part après ATTENTE_MAX_MS.
})

it('embarque la sonde sur la trame de taille, sans trame supplementaire', () => {
  // conservé — octets doit valoir 0 sur le chemin nominal, désormais.
})
```

Tests existants à adapter (le comportement change, pas l'intention) :

| Test | Ligne | Devient |
|------|-------|---------|
| `envoie une taille differente puis la vraie` | 1237 | remplacé par « envoie UNE trame de nudge » |
| `envoie la taille COURANTE, pas celle capturee avant la frame` | 1253 | sans objet (plus de rAF) → « la trame porte la taille relue au moment de l'envoi » |
| `fait REPEINDRE tmux, au lieu de redessiner la trame locale` | 548 | attend `nudge:true` sur la trame |
| `fait REPEINDRE tmux au retour, pas seulement le tampon local` | 925 | idem |

- [x] Écrire les nouveaux tests (quatre : le cas « taille COURANTE » est conservé, adapté au drain)
- [x] Adapter les tests du tableau

```bash
cd frontend && npx vitest run src/features/terminal/FullscreenTerminal.test.tsx   # ROUGES ciblés
```

### Étape 3.3 — Implémenter

Dans `FullscreenTerminal.tsx` :

- [x] Remplacer `octetsEnAttente` par `const file = createParseQueue()` ; `safeFit` lit
      `file.enAttente()` pour la sonde
- [x] `ws.onmessage` : `file.arrive(data.length)` puis `terminal.write(data, () => file.analyse(data.length))`
- [x] `sendResize(cols, rows, nudge = false)` : ajoute `...(nudge ? { nudge: true } : {})`
- [x] `refreshRef.current` : plus de `requestAnimationFrame`, plus de double envoi —
      `file.quandVide(() => { safeFit(); sendResize(terminal.cols, terminal.rows, true); terminal.refresh(0, terminal.rows - 1) })`
- [x] Réécrire le commentaire de `refreshRef`
- [x] `dispose()` de la file dans le `return` du `useEffect`

```bash
cd frontend && npx vitest run src/features/terminal/   # TOUT VERT
cd frontend && npm run lint && npx tsc --noEmit
```

---

## Task 4 : Vérifier sur test1, et calibrer le délai

Lire [`TESTER-MON-DEV.md`](../../../TESTER-MON-DEV.md) avant toute manipulation. Les tests unitaires
ne prouvent rien sur le comportement de tmux — seuls les logs réels le font.

- [x] `git push` sur `dev`, puis `dev-deploy.sh` sur test1
- [ ] Ouvrir une session, lancer un TUI (`htop`, `claude`), redimensionner la fenêtre, basculer
      d'onglet, revenir
- [ ] Relire les logs :

```
mcp logs_query: {compose_service="portal"} |~ "resize_applied"
```

**Critères de recette :**
- toute paire `nudge=debut` / `nudge=fin` est espacée d'au moins 40 ms (0 ms avant correction —
  les deux moitiés sont journalisées précisément pour rendre cet écart mesurable) ;
- `octets=0` sur le chemin nominal — une valeur non nulle ne doit plus subsister qu'au plafond ;
- aucun nudge au chargement initial d'une session ni sur un simple focus — seuls un vrai
  masquage, un redimensionnement ou le bouton Rafraîchir en déclenchent ;
- aucun `pty_set_size_failed`.

- [ ] Si tmux ne repeint toujours pas à 80 ms, remonter `NUDGE_DELAY_S` par paliers (120, 160)
      et **noter la valeur retenue et sa mesure** dans le commentaire — pas de constante posée
      au jugé
- [ ] Vérifier au passage le cas mobile (clavier ouvert/fermé : alternance `rows=28 ↔ 49`)

---

## Task 5 : Consigner

- [ ] `LESSONS.md` : `- [terminal] SIGWINCH n'est pas mis en file : deux TIOCSWINSZ rapprochés
      sont coalescés et tmux ne repeint pas. Un aller-retour de taille doit être espacé côté
      serveur — deux trames WebSocket à une frame d'écart arrivent dans le même segment TCP.`
- [ ] Article dans Docflow (workspace `devpod`, bloc `Documentation`) : la géométrie d'un
      terminal web (PTY, SIGWINCH, file de parsing xterm) — ce qui alimente le RAG
- [ ] Backlog : passer la tâche liée en `en review`
- [x] Commit français conventionnel, un par task :
      `fix(terminal): le nudge etait coalesce par le noyau, tmux ne repeignait pas`
      `fix(terminal): plus de redimensionnement tant qu'xterm n'a pas analyse le flux`

---

## Definition of Done

- [ ] `cd backend && uv run pytest -v` vert
- [ ] `cd backend && uv run ruff check src/ tests/ && uv run mypy src/` vert
- [ ] `cd frontend && npx vitest run && npm run lint && npx tsc --noEmit` vert
- [ ] Task 0 déployée et affichage sain confirmé par l'utilisateur
- [x] Coalescence établie sans mock dans `tests/sessions/test_pty_bridge.py`
- [ ] Critères de recette de la Task 4 constatés **dans les logs de test1**, pas déduits
- [ ] Aucun secret dans le diff
