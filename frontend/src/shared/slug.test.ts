/**
 * Derivation d'un slug depuis un libelle.
 *
 * Le defaut d'origine, cote types d'hyperviseur : la version maison SUPPRIMAIT
 * les majuscules au lieu de les convertir — « Proxmox4vm » devenait
 * « roxmox4vm », premier caractere mange.
 */
import { describe, expect, it } from 'vitest'
import { slugifier } from './slug'

describe('slugifier', () => {
  it('convertit les majuscules au lieu de les supprimer', () => {
    expect(slugifier('Proxmox4vm')).toBe('proxmox4vm')
    expect(slugifier('PROXMOX')).toBe('proxmox')
  })

  it('retire les accents par decomposition', () => {
    expect(slugifier('Éditeur')).toBe('editeur')
  })

  it('remplace les espaces et la ponctuation par des tirets', () => {
    expect(slugifier("Machine d'Alice (v2)")).toBe('machine-d-alice-v2')
  })

  it('ne laisse pas de tiret aux extremites', () => {
    expect(slugifier('  Test !  ')).toBe('test')
  })

  it('borne la longueur sans finir par un tiret', () => {
    const long = slugifier('a'.repeat(38) + ' ' + 'b'.repeat(10))
    expect(long.length).toBeLessThanOrEqual(40)
    expect(long.endsWith('-')).toBe(false)
  })
})
