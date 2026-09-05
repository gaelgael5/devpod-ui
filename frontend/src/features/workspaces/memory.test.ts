import { describe, it, expect } from 'vitest'
import { memoireEnOctets, memoireDepassePlafond } from './memory'

describe('memoireEnOctets', () => {
  it('convertit les unités Docker', () => {
    expect(memoireEnOctets('512m')).toBe(512 * 1024 ** 2)
    expect(memoireEnOctets('4g')).toBe(4 * 1024 ** 3)
    expect(memoireEnOctets('1024k')).toBe(1024 * 1024)
    expect(memoireEnOctets('2048b')).toBe(2048)
  })

  it('traite un entier nu comme des octets et tolère casse/espaces', () => {
    expect(memoireEnOctets('4096')).toBe(4096)
    expect(memoireEnOctets('  2G ')).toBe(2 * 1024 ** 3)
  })

  it('rend null sur vide ou syntaxe non conforme', () => {
    expect(memoireEnOctets('')).toBeNull()
    expect(memoireEnOctets('4go')).toBeNull()
    expect(memoireEnOctets('abc')).toBeNull()
  })
})

describe('memoireDepassePlafond', () => {
  it('signale un dépassement strict', () => {
    expect(memoireDepassePlafond('8g', '4g')).toBe(true)
    expect(memoireDepassePlafond('4097', '4096')).toBe(true)
  })

  it('ne signale rien à égalité ou en dessous', () => {
    expect(memoireDepassePlafond('4g', '4g')).toBe(false)
    expect(memoireDepassePlafond('2g', '4g')).toBe(false)
  })

  it('ne borne pas quand le plafond est vide, ni quand la demande est vide', () => {
    expect(memoireDepassePlafond('8g', '')).toBe(false)
    expect(memoireDepassePlafond('', '4g')).toBe(false)
  })
})
