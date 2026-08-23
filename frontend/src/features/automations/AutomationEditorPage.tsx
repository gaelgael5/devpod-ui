// Édition d'une règle d'automate en PAGE PLEINE (remplace l'ancienne popup) :
// général (libellé, slug, events, priorité, débounce, flags) → arbre de la règle
// (éditeur récursif, en-têtes par appel/filtre) → valeurs d'exemple pour les tests.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { EventsTree, VariablesPalette } from './editor-shared'
import { slugify } from './editor-utils'
import { collectCallNames, collectUsedVariables, normalizeTree, type RuleTree } from './tree'
import { TreeEditor } from './TreeEditor'
import {
  useAutomation,
  useCreateAutomation,
  useEventTypes,
  useEventVariables,
  useUpdateAutomation,
  type Automation,
  type AutomationInput,
} from './useAutomations'

function EditorForm({ automation }: { automation: Automation | null }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isEdit = automation !== null
  const eventTypes = useEventTypes()
  const eventVariables = useEventVariables()
  const create = useCreateAutomation()
  const update = useUpdateAutomation()

  const [label, setLabel] = useState(automation?.label ?? '')
  const [slug, setSlug] = useState(automation?.slug ?? '')
  const [slugTouched, setSlugTouched] = useState(isEdit)
  const [events, setEvents] = useState<string[]>(automation?.event_types ?? [])
  const [priority, setPriority] = useState(String(automation?.position ?? 0))
  const [delay, setDelay] = useState(String(automation?.delay_minutes ?? 0))
  const [stopChain, setStopChain] = useState(automation?.stop_chain ?? false)
  const [active, setActive] = useState(automation?.active ?? false)
  const [tree, setTree] = useState<RuleTree>(() => normalizeTree(automation?.tree))
  const [sampleVars, setSampleVars] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState<string | null>(null)

  function onLabelChange(v: string) {
    setLabel(v)
    if (!slugTouched) setSlug(slugify(v))
  }

  function toggleEvent(code: string) {
    setEvents((c) => (c.includes(code) ? c.filter((x) => x !== code) : [...c, code]))
  }

  async function copyVariable(v: string) {
    try {
      await navigator.clipboard?.writeText(`{${v}}`)
      setCopied(v)
      setTimeout(() => setCopied(null), 1200)
    } catch {
      /* presse-papier indisponible */
    }
  }

  // Variables exposées par les events sélectionnés (référence sous la sélection).
  const eventVars = useMemo(() => {
    const map = eventVariables.data ?? {}
    const set = new Set<string>()
    for (const ev of events) for (const v of map[ev] ?? []) set.add(v)
    return [...set]
  }, [eventVariables.data, events])

  // Variables copiables dans les appels : events + réponses nommées des appels.
  const variables = useMemo(() => {
    const set = new Set<string>(eventVars)
    for (const name of collectCallNames(tree.blocks)) set.add(`${name}.…`)
    return [...set]
  }, [eventVars, tree])

  // {var} utilisées dans l'arbre → champs de valeurs d'exemple pour les tests.
  const usedVars = useMemo(() => collectUsedVariables(tree), [tree])

  function submit() {
    if (!label.trim() || events.length === 0) {
      toast.error(t('automations.editor.missing'))
      return
    }
    const body: AutomationInput = {
      label: label.trim(),
      slug: slug.trim() || undefined,
      event_types: events,
      tree,
      delay_minutes: Number(delay) || 0,
      position: Number(priority) || 0,
      stop_chain: stopChain,
      active,
    }
    // Sauver ne ferme plus l'éditeur : on reste sur la page. À la création, on
    // bascule vers l'URL de la règle créée (mode édition) pour que les sauvegardes
    // suivantes mettent à jour au lieu de recréer.
    if (isEdit) {
      update.mutate(
        { id: automation.id, body },
        { onSuccess: () => toast.success(t('automations.form.updated')) },
      )
    } else {
      create.mutate(body, {
        onSuccess: (created) => {
          toast.success(t('automations.form.created'))
          navigate(`/admin/automations/${created.id}`, { replace: true })
        },
      })
    }
  }

  const pending = create.isPending || update.isPending

  // Ctrl/Cmd+S = sauver (sans déclencher le « enregistrer la page » du navigateur).
  // Ref sur le submit courant : l'écouteur est posé une fois, lit toujours l'état frais.
  const submitRef = useRef(submit)
  useEffect(() => {
    submitRef.current = submit
  })
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        submitRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 pb-24">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/admin/automations" className="text-sm text-muted-foreground hover:underline">
            {t('automations.editor.back')}
          </Link>
          <h1 className="text-2xl font-semibold">
            {isEdit ? t('automations.form.editTitle') : t('automations.form.newTitle')}
          </h1>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate('/admin/automations')}>
            {t('common.close')}
          </Button>
          <Button onClick={submit} disabled={pending}>
            {pending ? '…' : t('common.save')}
          </Button>
        </div>
      </div>

      {/* ── Général ── */}
      <section className="flex flex-col gap-4 rounded-lg border p-4">
        <h2 className="text-sm font-semibold">{t('automations.form.tabGeneral')}</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="au-label">{t('automations.form.label')}</Label>
            <Input id="au-label" value={label} onChange={(e) => onLabelChange(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="au-slug">{t('automations.form.slug')}</Label>
            <Input
              id="au-slug"
              value={slug}
              onChange={(e) => {
                setSlugTouched(true)
                setSlug(e.target.value)
              }}
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">{t('automations.form.slugHint')}</p>
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>{t('automations.form.events')}</Label>
          <EventsTree codes={eventTypes.data ?? []} selected={events} onToggle={toggleEvent} />
          {eventVars.length > 0 && (
            <div className="mt-1 flex flex-col gap-1 rounded-md border bg-muted/30 p-2">
              <span className="text-xs text-muted-foreground">
                {t('automations.editor.eventVars')}
              </span>
              <VariablesPalette variables={eventVars} copied={copied} onCopy={copyVariable} />
            </div>
          )}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="au-priority">{t('automations.form.priority')}</Label>
            <Input
              id="au-priority"
              type="number"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t('automations.form.priorityHint')}</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="au-delay">{t('automations.form.delay')}</Label>
            <Input
              id="au-delay"
              type="number"
              min={0}
              value={delay}
              onChange={(e) => setDelay(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t('automations.form.delayHint')}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={stopChain} onCheckedChange={setStopChain} />
            {t('automations.form.stopChain')}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={active} onCheckedChange={setActive} />
            {t('automations.form.active')}
          </label>
        </div>
      </section>

      {/* ── Arbre de la règle (chaque appel/filtre porte ses propres en-têtes,
             pré-remplis par l'opération du contrat choisie) ── */}
      <section className="flex flex-col gap-3 rounded-lg border p-4">
        <h2 className="text-sm font-semibold">{t('automations.tree.title')}</h2>
        <TreeEditor tree={tree} onChange={setTree} ctx={{ variables, sampleVars }} />
      </section>

      {/* ── Valeurs d'exemple pour les boutons Tester ── */}
      {usedVars.length > 0 && (
        <section className="flex flex-col gap-2 rounded-lg border p-4">
          <h2 className="text-sm font-semibold">{t('automations.editor.sampleVars')}</h2>
          <p className="text-xs text-muted-foreground">
            {t('automations.editor.sampleVarsHint')}
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {usedVars.map((v) => (
              <label key={v} className="flex items-center gap-2 text-xs">
                <code className="w-48 shrink-0 truncate">{`{${v}}`}</code>
                <Input
                  className="h-8"
                  value={sampleVars[v] ?? ''}
                  onChange={(e) => setSampleVars((sv) => ({ ...sv, [v]: e.target.value }))}
                />
              </label>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

export default function AutomationEditorPage() {
  const { t } = useTranslation()
  const { automationId } = useParams()
  const isNew = automationId === 'new'
  const { data, isLoading, isError } = useAutomation(isNew ? null : (automationId ?? null))

  if (isNew) return <EditorForm automation={null} />
  if (isLoading) return <p className="text-muted-foreground">…</p>
  if (isError || !data)
    return <p className="text-sm text-destructive">{t('automations.editor.notFound')}</p>
  // key = id : réinitialise le formulaire si on navigue d'une règle à une autre.
  return <EditorForm key={data.id} automation={data} />
}
