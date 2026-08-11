// Éditeur récursif de l'arbre de règle : blocs {filtre ET/OU imbriqué → appels
// nommés → blocs enfants}. Toutes les mutations sont immuables (onChange remonte
// un nouvel arbre) ; le test d'une condition réutilise POST /test-call.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { HeadersEditor, VariablesPalette } from './editor-shared'
import { draftsToRows, METHODS, SELECT_CLS, toDrafts } from './editor-utils'
import {
  isGroup,
  mergeAuthHeaders,
  newBlock,
  newCall,
  newGroup,
  newLeaf,
  type RuleTree,
  type TreeBlock,
  type TreeCall,
  type TreeFilterGroup,
  type TreeFilterLeaf,
  type TreeFilterNode,
  type TreeHeader,
  OPERATORS,
} from './tree'
import { useContract, useContracts, useTestCall, type Operation } from './useAutomations'

// Contexte passé à tous les niveaux : variables copiables et valeurs d'exemple
// des {var} (chaque appel/filtre porte désormais ses propres en-têtes).
export interface EditorCtx {
  variables: string[]
  sampleVars: Record<string, string>
  copied: string | null
  onCopy: (v: string) => void
}

// Éditeur d'en-têtes d'un nœud (HeaderRow[] de l'arbre ↔ drafts UI).
function NodeHeaders({
  headers,
  onChange,
}: {
  headers: TreeHeader[]
  onChange: (h: TreeHeader[]) => void
}) {
  const drafts = toDrafts(headers)
  return (
    <HeadersEditor
      headers={drafts}
      setHeaders={(update) => {
        const next = typeof update === 'function' ? update(drafts) : update
        onChange(draftsToRows(next))
      }}
    />
  )
}

// ─── Sélecteur contrat → opération (préremplit méthode/URL/corps) ──────────────

function OperationPicker({
  contractRef,
  operationId,
  onPick,
}: {
  contractRef: string | null | undefined
  operationId: string | null | undefined
  onPick: (contractRef: string, op: Operation | null, servers: string[]) => void
}) {
  const { t } = useTranslation()
  const contracts = useContracts()
  const detail = useContract(contractRef || null)
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      <select
        className={SELECT_CLS}
        value={contractRef ?? ''}
        onChange={(e) => onPick(e.target.value, null, [])}
        aria-label={t('automations.form.contract')}
      >
        <option value="">{t('automations.tree.noContract')}</option>
        {contracts.data?.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
          </option>
        ))}
      </select>
      <select
        className={SELECT_CLS}
        value={operationId ?? ''}
        onChange={(e) => {
          const op = detail.data?.operations.find((o) => o.operation_id === e.target.value)
          onPick(contractRef ?? '', op ?? null, detail.data?.servers ?? [])
        }}
        disabled={!contractRef}
        aria-label={t('automations.form.operation')}
      >
        <option value="">—</option>
        {detail.data?.operations.map((op) => (
          <option key={op.operation_id} value={op.operation_id}>
            {op.method} {op.path}
          </option>
        ))}
      </select>
    </div>
  )
}

function opUrl(op: Operation, servers: string[]): string {
  const server = servers[0]
  if (!server) return op.url
  const base = server.replace(/\/+$/, '')
  const path = op.path.startsWith('/') ? op.path : `/${op.path}`
  return `${base}${path}`
}

// ─── Condition (feuille de filtre) : appel + évaluation + bouton test ──────────

function FilterLeafEditor({
  leaf,
  ctx,
  onChange,
  onRemove,
  onWrapInGroup,
}: {
  leaf: TreeFilterLeaf
  ctx: EditorCtx
  onChange: (l: TreeFilterLeaf) => void
  onRemove: () => void
  onWrapInGroup: () => void
}) {
  const { t } = useTranslation()
  const test = useTestCall()

  function runTest() {
    if (!leaf.url.trim()) return
    test.mutate({
      url: leaf.url.trim(),
      http_method: leaf.http_method,
      headers: leaf.headers,
      body: leaf.body?.trim() || null,
      jsonpath: leaf.jsonpath.trim() || null,
      operator: leaf.operator || null,
      expected: leaf.expected?.trim() || null,
      variables: ctx.sampleVars,
    })
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border bg-background p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-muted-foreground">
          {t('automations.tree.condition')}
        </span>
        <div className="flex gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={onWrapInGroup}>
            {t('automations.tree.wrapGroup')}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
            ✕
          </Button>
        </div>
      </div>
      <OperationPicker
        contractRef={leaf.contract_ref}
        operationId={leaf.operation_id}
        onPick={(cRef, op, servers) =>
          onChange(
            op
              ? {
                  ...leaf,
                  contract_ref: cRef,
                  operation_id: op.operation_id,
                  http_method: op.method,
                  url: opUrl(op, servers),
                  headers: mergeAuthHeaders(leaf.headers, op.auth_headers),
                }
              : { ...leaf, contract_ref: cRef || null, operation_id: null },
          )
        }
      />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_7rem]">
        <Input
          placeholder={t('automations.form.url')}
          value={leaf.url}
          onChange={(e) => onChange({ ...leaf, url: e.target.value })}
          className="font-mono text-xs"
        />
        <select
          className={SELECT_CLS}
          value={leaf.http_method}
          onChange={(e) => onChange({ ...leaf, http_method: e.target.value })}
        >
          {METHODS.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
      </div>
      <NodeHeaders headers={leaf.headers} onChange={(h) => onChange({ ...leaf, headers: h })} />
      <Textarea
        placeholder={t('automations.tree.filterBody')}
        value={leaf.body ?? ''}
        onChange={(e) => onChange({ ...leaf, body: e.target.value || null })}
        rows={2}
        className="font-mono text-xs"
      />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_9rem_1fr]">
        <Input
          placeholder={t('automations.form.jsonpath')}
          value={leaf.jsonpath}
          onChange={(e) => onChange({ ...leaf, jsonpath: e.target.value })}
          className="font-mono text-xs"
        />
        <select
          className={SELECT_CLS}
          value={leaf.operator}
          onChange={(e) => onChange({ ...leaf, operator: e.target.value })}
        >
          {OPERATORS.map((o) => (
            <option key={o} value={o}>
              {t(`automations.operators.${o}`)}
            </option>
          ))}
        </select>
        <Input
          placeholder={t('automations.form.expected')}
          value={leaf.expected ?? ''}
          onChange={(e) => onChange({ ...leaf, expected: e.target.value || null })}
          disabled={leaf.operator === 'exists' || leaf.operator === 'not_exists'}
          className="font-mono text-xs"
        />
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={runTest}
          disabled={test.isPending || !leaf.url.trim()}
        >
          {test.isPending ? t('automations.form.filterTesting') : t('automations.form.filterTest')}
        </Button>
        {test.data &&
          (test.data.ok ? (
            <span className="text-xs">
              HTTP {test.data.status_code}
              {test.data.evaluation && (
                <span
                  className={
                    test.data.evaluation.passed ? 'ml-2 text-green-600' : 'ml-2 text-destructive'
                  }
                >
                  {test.data.evaluation.error
                    ? test.data.evaluation.error
                    : test.data.evaluation.passed
                      ? t('automations.tree.passes')
                      : t('automations.tree.blocked')}
                </span>
              )}
            </span>
          ) : (
            <span className="text-xs text-destructive">{test.data.error}</span>
          ))}
      </div>
      {test.data?.ok && test.data.body && (
        <pre className="max-h-40 overflow-auto rounded bg-muted/50 p-2 font-mono text-xs">
          {test.data.body}
        </pre>
      )}
    </div>
  )
}

// ─── Nœud de filtre : feuille ou groupe ET/OU (récursif) ───────────────────────

function FilterNodeEditor({
  node,
  ctx,
  onChange,
  onRemove,
}: {
  node: TreeFilterNode
  ctx: EditorCtx
  onChange: (n: TreeFilterNode) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  if (!isGroup(node)) {
    return (
      <FilterLeafEditor
        leaf={node}
        ctx={ctx}
        onChange={onChange}
        onRemove={onRemove}
        onWrapInGroup={() => onChange(newGroup(node))}
      />
    )
  }
  const group: TreeFilterGroup = node
  const setItems = (items: TreeFilterNode[]) => onChange({ ...group, items })
  return (
    <div className="flex flex-col gap-2 rounded-md border border-dashed p-2">
      <div className="flex items-center justify-between gap-2">
        <select
          className={`${SELECT_CLS} w-auto`}
          value={group.op}
          onChange={(e) => onChange({ ...group, op: e.target.value as 'and' | 'or' })}
        >
          <option value="and">{t('automations.tree.and')}</option>
          <option value="or">{t('automations.tree.or')}</option>
        </select>
        <div className="flex gap-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setItems([...group.items, newLeaf()])}
          >
            {t('automations.tree.addCondition')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setItems([...group.items, newGroup(newLeaf())])}
          >
            {t('automations.tree.addGroup')}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
            ✕
          </Button>
        </div>
      </div>
      <div className="flex flex-col gap-2 border-l-2 pl-2">
        {group.items.map((item, i) => (
          <FilterNodeEditor
            key={i}
            node={item}
            ctx={ctx}
            onChange={(n) => setItems(group.items.map((x, j) => (i === j ? n : x)))}
            onRemove={() => setItems(group.items.filter((_, j) => j !== i))}
          />
        ))}
      </div>
    </div>
  )
}

// ─── Appel nommé ───────────────────────────────────────────────────────────────

function CallEditor({
  call,
  ctx,
  onChange,
  onRemove,
}: {
  call: TreeCall
  ctx: EditorCtx
  onChange: (c: TreeCall) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2 rounded-md border bg-background p-2">
      <div className="flex flex-wrap items-center gap-2">
        <Label className="text-xs">{t('automations.tree.callName')}</Label>
        <Input
          className="w-40 font-mono text-xs"
          value={call.name}
          onChange={(e) => onChange({ ...call, name: e.target.value })}
        />
        <span className="text-xs text-muted-foreground">
          {t('automations.tree.callNameHint', { name: call.name || 'nom' })}
        </span>
        <Button type="button" variant="ghost" size="sm" className="ml-auto" onClick={onRemove}>
          ✕
        </Button>
      </div>
      <OperationPicker
        contractRef={call.contract_ref}
        operationId={call.operation_id}
        onPick={(cRef, op, servers) =>
          onChange(
            op
              ? {
                  ...call,
                  contract_ref: cRef,
                  operation_id: op.operation_id,
                  http_method: op.method,
                  url: opUrl(op, servers),
                  headers: mergeAuthHeaders(call.headers, op.auth_headers),
                  body_template:
                    op.body_skeleton != null
                      ? JSON.stringify(op.body_skeleton, null, 2)
                      : call.body_template,
                }
              : { ...call, contract_ref: cRef || null, operation_id: null },
          )
        }
      />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_7rem]">
        <Input
          placeholder={t('automations.form.url')}
          value={call.url}
          onChange={(e) => onChange({ ...call, url: e.target.value })}
          className="font-mono text-xs"
        />
        <select
          className={SELECT_CLS}
          value={call.http_method}
          onChange={(e) => onChange({ ...call, http_method: e.target.value })}
        >
          {METHODS.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
      </div>
      <NodeHeaders headers={call.headers} onChange={(h) => onChange({ ...call, headers: h })} />
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <Label className="text-xs">{t('automations.form.bodyTemplate')}</Label>
          <VariablesPalette variables={ctx.variables} copied={ctx.copied} onCopy={ctx.onCopy} />
        </div>
        <Textarea
          value={call.body_template ?? ''}
          onChange={(e) => onChange({ ...call, body_template: e.target.value || null })}
          rows={4}
          className="font-mono text-xs"
        />
      </div>
    </div>
  )
}

// ─── Bloc récursif ─────────────────────────────────────────────────────────────

function BlockEditor({
  block,
  ctx,
  depth,
  onChange,
  onRemove,
}: {
  block: TreeBlock
  ctx: EditorCtx
  depth: number
  onChange: (b: TreeBlock) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3" data-depth={depth}>
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase text-muted-foreground">
          {t('automations.tree.block')}
        </span>
        <Input
          className="h-8 max-w-64"
          placeholder={t('automations.tree.blockLabel')}
          value={block.label}
          onChange={(e) => onChange({ ...block, label: e.target.value })}
        />
        <Button type="button" variant="ghost" size="sm" className="ml-auto" onClick={onRemove}>
          {t('automations.tree.removeBlock')}
        </Button>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium">{t('automations.tree.filter')}</span>
        {block.filter === null ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {t('automations.tree.noFilter')}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChange({ ...block, filter: newLeaf() })}
            >
              {t('automations.tree.addCondition')}
            </Button>
          </div>
        ) : (
          <FilterNodeEditor
            node={block.filter}
            ctx={ctx}
            onChange={(n) => onChange({ ...block, filter: n })}
            onRemove={() => onChange({ ...block, filter: null })}
          />
        )}
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium">{t('automations.tree.calls')}</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              onChange({ ...block, calls: [...block.calls, newCall(ctx.variables)] })
            }
          >
            {t('automations.tree.addCall')}
          </Button>
        </div>
        {block.calls.map((c, i) => (
          <CallEditor
            key={i}
            call={c}
            ctx={ctx}
            onChange={(nc) =>
              onChange({ ...block, calls: block.calls.map((x, j) => (i === j ? nc : x)) })
            }
            onRemove={() =>
              onChange({ ...block, calls: block.calls.filter((_, j) => j !== i) })
            }
          />
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium">{t('automations.tree.children')}</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange({ ...block, blocks: [...block.blocks, newBlock()] })}
          >
            {t('automations.tree.addChild')}
          </Button>
        </div>
        <div className={block.blocks.length ? 'flex flex-col gap-2 border-l-2 pl-3' : ''}>
          {block.blocks.map((b, i) => (
            <BlockEditor
              key={i}
              block={b}
              ctx={ctx}
              depth={depth + 1}
              onChange={(nb) =>
                onChange({ ...block, blocks: block.blocks.map((x, j) => (i === j ? nb : x)) })
              }
              onRemove={() =>
                onChange({ ...block, blocks: block.blocks.filter((_, j) => j !== i) })
              }
            />
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── Racine ────────────────────────────────────────────────────────────────────

export function TreeEditor({
  tree,
  ctx,
  onChange,
}: {
  tree: RuleTree
  ctx: Omit<EditorCtx, 'copied' | 'onCopy'>
  onChange: (t: RuleTree) => void
}) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState<string | null>(null)

  async function copyVariable(v: string) {
    try {
      await navigator.clipboard?.writeText(`{${v}}`)
      setCopied(v)
      setTimeout(() => setCopied(null), 1200)
    } catch {
      /* presse-papier indisponible */
    }
  }

  const fullCtx: EditorCtx = { ...ctx, copied, onCopy: copyVariable }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">{t('automations.tree.intro')}</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange({ ...tree, blocks: [...tree.blocks, newBlock()] })}
        >
          {t('automations.tree.addBlock')}
        </Button>
      </div>
      {tree.blocks.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('automations.tree.empty')}</p>
      )}
      {tree.blocks.map((b, i) => (
        <BlockEditor
          key={i}
          block={b}
          ctx={fullCtx}
          depth={0}
          onChange={(nb) =>
            onChange({ ...tree, blocks: tree.blocks.map((x, j) => (i === j ? nb : x)) })
          }
          onRemove={() => onChange({ ...tree, blocks: tree.blocks.filter((_, j) => j !== i) })}
        />
      ))}
    </div>
  )
}
