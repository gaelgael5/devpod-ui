// Arbre de règle d'un automate — miroir TS du schéma backend automations/tree.py.
// Blocs récursifs : filtre (arbre ET/OU imbriqué) → appels nommés → blocs enfants.

export interface TreeHeader {
  name: string
  value?: string | null
  secret_ref?: string | null
  value_prefix?: string
  required?: boolean
  enabled?: boolean
}

export interface TreeCall {
  name: string
  url: string
  http_method: string
  body_template?: string | null
  headers: TreeHeader[]
  contract_ref?: string | null
  operation_id?: string | null
}

export interface TreeFilterLeaf {
  url: string
  http_method: string
  body?: string | null
  jsonpath: string
  operator: string
  expected?: string | null
  headers: TreeHeader[]
  contract_ref?: string | null
  operation_id?: string | null
}

export interface TreeFilterGroup {
  op: 'and' | 'or'
  items: TreeFilterNode[]
}

export type TreeFilterNode = TreeFilterGroup | TreeFilterLeaf

export interface TreeBlock {
  label: string
  filter: TreeFilterNode | null
  calls: TreeCall[]
  blocks: TreeBlock[]
}

export interface RuleTree {
  version: 1
  blocks: TreeBlock[]
}

export const OPERATORS = ['exists', 'not_exists', 'equals', 'not_equals'] as const

export function isGroup(node: TreeFilterNode): node is TreeFilterGroup {
  return (node as TreeFilterGroup).op !== undefined
}

export function emptyTree(): RuleTree {
  return { version: 1, blocks: [] }
}

export function newBlock(): TreeBlock {
  return { label: '', filter: null, calls: [], blocks: [] }
}

export function newCall(existingNames: string[]): TreeCall {
  let i = existingNames.length + 1
  let name = `call${i}`
  while (existingNames.includes(name)) name = `call${++i}`
  return { name, url: '', http_method: 'POST', body_template: null, headers: [] }
}

export function newLeaf(): TreeFilterLeaf {
  return {
    url: '',
    http_method: 'GET',
    jsonpath: '',
    operator: 'exists',
    expected: null,
    headers: [],
  }
}

/** Fusionne les en-têtes d'auth d'une opération dans une liste (sans doublon de nom). */
export function mergeAuthHeaders(
  existing: TreeHeader[],
  auth: { header: string; value_prefix: string }[] | undefined,
): TreeHeader[] {
  if (!auth?.length) return existing
  const names = new Set(existing.map((h) => h.name.toLowerCase()))
  const add = auth
    .filter((a) => !names.has(a.header.toLowerCase()))
    .map<TreeHeader>((a) => ({
      name: a.header,
      value: null,
      secret_ref: null,
      value_prefix: a.value_prefix,
      required: true,
      enabled: true,
    }))
  return add.length ? [...existing, ...add] : existing
}

export function newGroup(first: TreeFilterNode): TreeFilterGroup {
  return { op: 'and', items: [first] }
}

/** Tous les noms d'appels de l'arbre (parcours en profondeur). */
export function collectCallNames(blocks: TreeBlock[]): string[] {
  const out: string[] = []
  for (const b of blocks) {
    for (const c of b.calls) out.push(c.name)
    out.push(...collectCallNames(b.blocks))
  }
  return out
}

/** Compteurs pour la ligne de liste ({{blocks}} bloc(s), {{calls}} appel(s)). */
export function treeSummary(tree: RuleTree | null | undefined): { blocks: number; calls: number } {
  function walk(blocks: TreeBlock[]): { blocks: number; calls: number } {
    let nb = 0
    let nc = 0
    for (const b of blocks) {
      nb += 1
      nc += b.calls.length
      const sub = walk(b.blocks)
      nb += sub.blocks
      nc += sub.calls
    }
    return { blocks: nb, calls: nc }
  }
  return walk(tree?.blocks ?? [])
}

/** Variables {var} référencées dans l'arbre (pour les valeurs d'exemple des tests). */
export function collectUsedVariables(tree: RuleTree): string[] {
  const found = new Set<string>()
  const scan = (s: string | null | undefined) => {
    // Même charset que le moteur de template backend (_VAR_RE) : évite de
    // capturer des accolades de JSON comme des variables.
    for (const m of (s ?? '').matchAll(/\{([a-zA-Z0-9_.]+)\}/g)) found.add(m[1])
  }
  function walkFilter(node: TreeFilterNode | null) {
    if (!node) return
    if (isGroup(node)) {
      node.items.forEach(walkFilter)
      return
    }
    scan(node.url)
    scan(node.body)
    scan(node.jsonpath)
    scan(node.expected)
  }
  function walkBlocks(blocks: TreeBlock[]) {
    for (const b of blocks) {
      walkFilter(b.filter)
      for (const c of b.calls) {
        scan(c.url)
        scan(c.body_template)
      }
      walkBlocks(b.blocks)
    }
  }
  walkBlocks(tree.blocks)
  return [...found]
}
