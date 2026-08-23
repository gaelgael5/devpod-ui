/**
 * Collecte des URL dans le flux brut.
 *
 * Le cas qui motive ce module : le 20/08, un clic sur l'URL d'authentification
 * `claude` a ouvert une URL amputée de blocs entiers —
 * `client_id=9d1c250a-e61b-44d9-88ed-...` réduit à `cliened-...`. Le détecteur
 * de xterm relit le buffer *rendu*, où l'URL est repliée ; le flux, lui, la
 * porte d'un seul tenant.
 */
import { describe, expect, it } from 'vitest'
import { createLinkCollector } from './linkCollector'

const ESC = String.fromCharCode(27)
const AUTH_URL =
  'https://claude.ai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e' +
  '&response_type=code&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback' +
  '&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference' +
  '&code_challenge=XeDEpsQ77-4v8pg--FH9-hlW88BI6erYYevVnu1eH4w&code_challenge_method=S256' +
  '&state=puGyxuUpf7QyKJFbvSK3vINUjVrNik60OipNHknuvy0'

describe('createLinkCollector', () => {
  it('répare une URL mutilée par le repli — le cas réel du 20/08', () => {
    const c = createLinkCollector()
    c.push(`Browser didn't open? Use the url below:\n\n${AUTH_URL}\n\nPaste code here: `)

    // Ce que le détecteur de xterm a effectivement remonté au clic.
    const mangled =
      'https://claude.ai/oauth/authorize?code=true&cliened-5944d1962f5e=' +
      '&response_type=code&redirect_uri=https%25m%2Foauth%2Fcode%2Fcallback' +
      '&scope=org%3Acreate_api_keyerence+user%3Asessions%3Aclaude_code'

    expect(c.resolve(mangled)).toBe(AUTH_URL)
  })

  it('laisse passer une URL que le détecteur a vue juste', () => {
    const c = createLinkCollector()
    c.push(`voir ${AUTH_URL} pour continuer`)

    expect(c.resolve(AUTH_URL)).toBe(AUTH_URL)
  })

  it('recolle une URL coupée entre deux trames', () => {
    const c = createLinkCollector()
    const cut = 120
    c.push(`url: ${AUTH_URL.slice(0, cut)}`)
    // Rien ne doit être enregistré tant que la suite n'est pas arrivée : une
    // version tronquée ferait un candidat plausible et gagnerait la résolution.
    expect(c.seen()).toEqual([])

    c.push(`${AUTH_URL.slice(cut)}\n`)
    expect(c.seen()).toEqual([AUTH_URL])
  })

  it('ignore les séquences ANSI qui entourent l’URL', () => {
    const c = createLinkCollector()
    c.push(`${ESC}[1;34m${AUTH_URL}${ESC}[0m\n`)

    expect(c.seen()).toEqual([AUTH_URL])
  })

  it('ne coupe pas l’URL sur un titre de fenêtre OSC', () => {
    const c = createLinkCollector()
    c.push(`${ESC}]0;bash${String.fromCharCode(7)}${AUTH_URL}\n`)

    expect(c.seen()).toEqual([AUTH_URL])
  })

  it('n’avale pas la ponctuation de fin de phrase', () => {
    const c = createLinkCollector()
    c.push('rendez-vous sur https://dev.yoops.org/portal, puis connectez-vous.\n')

    expect(c.seen()).toEqual(['https://dev.yoops.org/portal'])
  })

  it('n’invente rien quand aucune URL connue ne correspond', () => {
    const c = createLinkCollector()
    c.push(`${AUTH_URL}\n`)

    const other = 'https://exemple.test/quelque-chose?a=1'
    expect(c.resolve(other)).toBe(other)
  })

  it('ne confond pas deux URL de même origine mais de chemin différent', () => {
    const c = createLinkCollector()
    c.push('https://claude.ai/oauth/authorize?a=1\nhttps://claude.ai/settings?b=2\n')

    expect(c.resolve('https://claude.ai/settings?zzz')).toBe('https://claude.ai/settings?b=2')
  })

  it('sur deux URL de même chemin, retient la plus récente', () => {
    const c = createLinkCollector()
    c.push('https://claude.ai/oauth/authorize?state=ancien\n')
    c.push('https://claude.ai/oauth/authorize?state=nouveau\n')

    // Un second `claude /login` réaffiche la même route avec un state neuf ;
    // c'est celui affiché en dernier que l'utilisateur a sous les yeux.
    expect(c.resolve('https://claude.ai/oauth/authorize?state=abim')).toBe(
      'https://claude.ai/oauth/authorize?state=nouveau',
    )
  })
})
