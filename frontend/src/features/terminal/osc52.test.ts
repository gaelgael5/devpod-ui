import { decodeOsc52, OSC52_MAX_OCTETS } from './osc52'

/** Encode en base64 comme le fait une application distante (UTF-8 puis base64). */
function encode(texte: string): string {
  const octets = new TextEncoder().encode(texte)
  return btoa(String.fromCharCode(...octets))
}

describe('decodeOsc52', () => {
  it('décode une sélection avec sa cible', () => {
    const r = decodeOsc52(`c;${encode('ligne copiée')}`)
    expect(r).toEqual({ ok: true, texte: 'ligne copiée' })
  })

  it('décode une charge sans cible (`;base64`)', () => {
    expect(decodeOsc52(`;${encode('abc')}`)).toEqual({ ok: true, texte: 'abc' })
  })

  it('accepte plusieurs cibles à la fois', () => {
    expect(decodeOsc52(`cs;${encode('abc')}`)).toEqual({ ok: true, texte: 'abc' })
  })

  it("restitue l'UTF-8 au lieu des octets bruts", () => {
    // `atob` seul rendrait « Ã©Ã Ã¹ » : le décodage UTF-8 n'est pas optionnel.
    const r = decodeOsc52(`c;${encode('éàù — €')}`)
    expect(r).toEqual({ ok: true, texte: 'éàù — €' })
  })

  it('refuse une demande de LECTURE du presse-papier', () => {
    // Y répondre livrerait le presse-papier de l'utilisateur au processus distant.
    expect(decodeOsc52('c;?')).toEqual({ ok: false, raison: 'lecture' })
  })

  it('refuse une charge vide plutôt que de vider le presse-papier', () => {
    expect(decodeOsc52('c;')).toEqual({ ok: false, raison: 'vide' })
  })

  it('refuse un base64 invalide sans lever', () => {
    expect(decodeOsc52('c;pas du base64 !!')).toEqual({
      ok: false,
      raison: 'base64_invalide',
    })
  })

  it('refuse au-delà de la limite d’octets', () => {
    const trop = decodeOsc52(`c;${encode('x'.repeat(OSC52_MAX_OCTETS + 1))}`)
    expect(trop).toEqual({ ok: false, raison: 'trop_gros' })
    const limite = decodeOsc52(`c;${encode('x'.repeat(OSC52_MAX_OCTETS))}`)
    expect(limite.ok).toBe(true)
  })
})
