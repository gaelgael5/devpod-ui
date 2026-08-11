import { describe, expect, it } from 'vitest'
import {
  collectCallNames,
  collectUsedVariables,
  isGroup,
  newCall,
  normalizeTree,
  treeSummary,
  type RuleTree,
} from '../tree'

const TREE: RuleTree = {
  version: 1,
  blocks: [
    {
      label: 'racine',
      filter: {
        op: 'and',
        items: [
          {
            url: 'https://x/{subject.ws_id}',
            http_method: 'GET',
            jsonpath: '$.ok',
            operator: 'exists',
            headers: [],
          },
        ],
      },
      calls: [
        {
          name: 'create',
          url: 'https://x/create',
          http_method: 'POST',
          body_template: '{"login": "{subject.login}"}',
          headers: [],
        },
      ],
      blocks: [
        {
          label: 'enfant',
          filter: null,
          calls: [
            { name: 'share', url: 'https://x/{create.id}/share', http_method: 'POST', headers: [] },
          ],
          blocks: [],
        },
      ],
    },
  ],
}

describe('tree helpers', () => {
  it('collectCallNames traverse récursivement', () => {
    expect(collectCallNames(TREE.blocks)).toEqual(['create', 'share'])
  })

  it('treeSummary compte blocs et appels imbriqués', () => {
    expect(treeSummary(TREE)).toEqual({ blocks: 2, calls: 2 })
    expect(treeSummary(null)).toEqual({ blocks: 0, calls: 0 })
  })

  it('collectUsedVariables balaie filtres et appels', () => {
    const vars = collectUsedVariables(TREE)
    expect(vars).toContain('subject.ws_id')
    expect(vars).toContain('subject.login')
    expect(vars).toContain('create.id')
  })

  it('isGroup distingue groupe et feuille', () => {
    expect(isGroup({ op: 'and', items: [] })).toBe(true)
    expect(
      isGroup({ url: 'https://x', http_method: 'GET', jsonpath: '$', operator: 'exists' }),
    ).toBe(false)
  })

  it('newCall génère un nom unique', () => {
    expect(newCall(['call1', 'call2']).name).toBe('call3')
  })

  it('normalizeTree matérialise les tableaux manquants (arbre d\'une version antérieure)', () => {
    // Nœuds sans headers/calls/blocks/items → normalisés en tableaux vides.
    const raw = {
      version: 1,
      blocks: [
        {
          label: 'x',
          filter: { url: 'https://x', http_method: 'GET', jsonpath: '$.a', operator: 'exists' },
          calls: [{ name: 'c', url: 'https://y', http_method: 'POST' }],
        },
      ],
    } as unknown as RuleTree
    const norm = normalizeTree(raw)
    const block = norm.blocks[0]
    expect(block.blocks).toEqual([])
    expect(block.calls[0].headers).toEqual([])
    expect((block.filter as { headers: unknown[] }).headers).toEqual([])
  })

  it('normalizeTree tolère null/undefined', () => {
    expect(normalizeTree(null)).toEqual({ version: 1, blocks: [] })
    expect(normalizeTree(undefined)).toEqual({ version: 1, blocks: [] })
  })
})
