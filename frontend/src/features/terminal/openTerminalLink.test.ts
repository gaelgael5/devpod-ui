/**
 * Ouverture des liens détectés dans un terminal.
 *
 * Le contenu d'un terminal est la sortie brute d'un processus distant : il n'est
 * pas de confiance. Ces tests verrouillent la liste blanche de schémas et le
 * `noopener` (sans lui, la page ouverte peut rediriger le portail — tabnabbing).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isOpenableLink, openTerminalLink } from './openTerminalLink'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('isOpenableLink', () => {
  it('accepte http et https', () => {
    expect(isOpenableLink('https://claude.ai/oauth/authorize?code=abc')).toBe(true)
    expect(isOpenableLink('http://localhost:3000/callback')).toBe(true)
  })

  it('refuse les schémas dangereux ou non pertinents', () => {
    // Une commande distante peut afficher n'importe quoi.
    expect(isOpenableLink('javascript:alert(1)')).toBe(false)
    expect(isOpenableLink('file:///etc/passwd')).toBe(false)
    expect(isOpenableLink('data:text/html,<script>alert(1)</script>')).toBe(false)
  })

  it('refuse ce qui n’est pas une URL', () => {
    expect(isOpenableLink('pas une url')).toBe(false)
    expect(isOpenableLink('')).toBe(false)
  })
})

describe('openTerminalLink', () => {
  it('ouvre un onglet avec noopener et noreferrer', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    const url = 'https://claude.ai/oauth/authorize?code=abc'

    expect(openTerminalLink(url)).toBe(true)
    expect(open).toHaveBeenCalledWith(url, '_blank', 'noopener,noreferrer')
  })

  it('n’ouvre rien sur un schéma refusé', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    vi.spyOn(console, 'warn').mockImplementation(() => {})

    expect(openTerminalLink('javascript:alert(1)')).toBe(false)
    expect(open).not.toHaveBeenCalled()
  })
})
