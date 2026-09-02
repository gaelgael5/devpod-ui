import {
  createSelectionHintDetector,
  GLISSE_MIN_PX,
  SILENCE_MS,
} from './selectionHint'

/** Horloge manuelle : l'indice est throttlé, on doit pouvoir avancer le temps. */
function horloge(depart = 0) {
  let t = depart
  return { now: () => t, avance: (ms: number) => (t += ms) }
}

const SUIVI = { shift: false, suiviSouris: true }
const SANS_SELECTION = { selectionActive: false }

describe('createSelectionHintDetector', () => {
  it('signale un glissé qui ne sélectionne rien sous suivi souris', () => {
    const d = createSelectionHintDetector(horloge())
    d.start(10, 10, SUIVI)
    expect(d.end(10 + GLISSE_MIN_PX, 10, SANS_SELECTION)).toBe(true)
  })

  it('se tait quand le glissé a bien sélectionné', () => {
    const d = createSelectionHintDetector(horloge())
    d.start(10, 10, SUIVI)
    expect(d.end(200, 10, { selectionActive: true })).toBe(false)
  })

  it('se tait sans suivi souris — la sélection marche déjà', () => {
    const d = createSelectionHintDetector(horloge())
    d.start(10, 10, { shift: false, suiviSouris: false })
    expect(d.end(200, 10, SANS_SELECTION)).toBe(false)
  })

  it('se tait quand Maj est tenue — la sélection est déjà forcée', () => {
    const d = createSelectionHintDetector(horloge())
    d.start(10, 10, { shift: true, suiviSouris: true })
    expect(d.end(200, 10, SANS_SELECTION)).toBe(false)
  })

  it('se tait sur un clic : le déplacement reste sous le seuil', () => {
    const d = createSelectionHintDetector(horloge())
    d.start(10, 10, SUIVI)
    expect(d.end(10 + GLISSE_MIN_PX - 1, 10, SANS_SELECTION)).toBe(false)
  })

  it('se tait sur un mouseup sans mousedown préalable', () => {
    const d = createSelectionHintDetector(horloge())
    expect(d.end(200, 200, SANS_SELECTION)).toBe(false)
  })

  it("ne répète pas l'indice avant la fin du silence", () => {
    const h = horloge()
    const d = createSelectionHintDetector(h)

    d.start(10, 10, SUIVI)
    expect(d.end(200, 10, SANS_SELECTION)).toBe(true)

    h.avance(SILENCE_MS - 1)
    d.start(10, 10, SUIVI)
    expect(d.end(200, 10, SANS_SELECTION)).toBe(false)

    h.avance(1)
    d.start(10, 10, SUIVI)
    expect(d.end(200, 10, SANS_SELECTION)).toBe(true)
  })

  it('oublie le glissé en cours après chaque fin de geste', () => {
    const d = createSelectionHintDetector(horloge())
    d.start(10, 10, SUIVI)
    expect(d.end(200, 10, SANS_SELECTION)).toBe(true)
    // Deuxième `end` sans `start` : plus rien à évaluer, même throttle mis à part.
    expect(d.end(400, 10, SANS_SELECTION)).toBe(false)
  })
})
