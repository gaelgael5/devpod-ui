// Création et édition d'un type d'hyperviseur en PAGE PLEINE (remplace les deux
// popups). Quatre onglets, parce que quatre natures d'objets cohabitaient dans
// un même flux vertical sans que rien ne les distingue : le type lui-même, les
// actions qui portent sur l'hyperviseur, celles qui portent sur les machines
// qu'il crée, et les variables des nœuds créés.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { slugifier } from '@/shared/slug'
import HypervisorActionsBlock from './HypervisorActionsBlock'
import HypervisorVariablesBlock from './HypervisorVariablesBlock'
import {
  useAdminHypervisorTypes,
  type HypervisorAction,
  type HypervisorTypeConfig,
  type HypervisorVariable,
} from './useAdminHypervisorTypes'

const VIDE: HypervisorTypeConfig = {
  label: '',
  name: '',
  add_script: '',
  destroy_script: '',
  actions: [],
  variables: [],
}

/** `slugManuel` n'existe que le temps de la saisie : le backend le refuserait. */
function sansEtatLocal(actions: HypervisorAction[]): HypervisorAction[] {
  return actions.map(({ label, slug, script, cible }) => ({
    label,
    slug,
    script,
    // Un type enregistré avant l'introduction du champ n'en porte pas : on écrit
    // le défaut explicitement plutôt que de laisser le backend le redeviner.
    cible: cible ?? 'machine',
  }))
}

function variablesPropres(variables: HypervisorVariable[]): HypervisorVariable[] {
  return variables.map(({ label, slug, type }) => ({ label, slug, type }))
}

function TypeForm({ initial }: { initial: HypervisorTypeConfig | null }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { addType, updateType } = useAdminHypervisorTypes()
  const creation = initial === null

  const [form, setForm] = useState<HypervisorTypeConfig>(initial ?? VIDE)

  // Le `name` est une clef technique : dérivé du libellé à la création, figé
  // ensuite — le renommer casserait les slugs d'action déjà qualifiés et les
  // hyperviseurs qui référencent le type.
  function onLabelChange(label: string) {
    setForm((f) => (creation ? { ...f, label, name: slugifier(label) } : { ...f, label }))
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const corps = {
      ...form,
      actions: sansEtatLocal(form.actions ?? []),
      variables: variablesPropres(form.variables ?? []),
    }
    if (creation) {
      addType.mutate(corps, { onSuccess: () => navigate('/admin/hypervisor-types') })
    } else {
      updateType.mutate(
        { name: form.name, body: corps },
        { onSuccess: () => navigate('/admin/hypervisor-types') },
      )
    }
  }

  const pending = addType.isPending || updateType.isPending

  return (
    <form onSubmit={submit} className="mx-auto flex max-w-4xl flex-col gap-6 pb-24">
      <div className="flex items-center justify-between">
        <div>
          <Link
            to="/admin/hypervisor-types"
            className="text-sm text-muted-foreground hover:underline"
          >
            {t('admin.hypervisorTypeEditor.back')}
          </Link>
          <h1 className="text-2xl font-semibold">
            {creation
              ? t('admin.addHypervisorType')
              : `${t('admin.editHypervisorType')} — ${form.label || form.name}`}
          </h1>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate('/admin/hypervisor-types')}
          >
            {t('workspaces.confirm.cancel')}
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? '…' : t('admin.form.save')}
          </Button>
        </div>
      </div>

      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general">{t('admin.hypervisorTypeEditor.tabGeneral')}</TabsTrigger>
          <TabsTrigger value="hyperviseur">
            {t('admin.hypervisorTypeEditor.tabHypervisorActions')}
          </TabsTrigger>
          <TabsTrigger value="machine">
            {t('admin.hypervisorTypeEditor.tabMachineActions')}
          </TabsTrigger>
          <TabsTrigger value="variables">
            {t('admin.hypervisorTypeEditor.tabVariables')}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="general">
          <section className="flex flex-col gap-4 rounded-lg border p-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-label">{t('admin.form.hypervisorLabel')}</Label>
              <Input
                id="ht-label"
                value={form.label}
                onChange={(e) => onLabelChange(e.target.value)}
                placeholder="Proxmox KVM"
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-name">{t('admin.col.name')}</Label>
              <Input
                id="ht-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="proxmox-kvm"
                pattern="^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$"
                required
                disabled={!creation}
                className="font-mono text-xs"
              />
              {!creation && (
                <p className="text-xs text-muted-foreground">
                  {t('admin.hypervisorTypeEditor.nameFrozen')}
                </p>
              )}
            </div>
          </section>
        </TabsContent>

        <TabsContent value="hyperviseur">
          <section className="flex flex-col gap-4 rounded-lg border p-4">
            <HypervisorActionsBlock
              typeName={form.name}
              cible="hyperviseur"
              actions={form.actions ?? []}
              onChange={(actions) => setForm((f) => ({ ...f, actions }))}
            />
          </section>
        </TabsContent>

        <TabsContent value="machine">
          <section className="flex flex-col gap-4 rounded-lg border p-4">
            {/* Créer et détruire sont les deux actions machine de base : elles
                vivent ici, avec les autres, et non dans un onglet « général »
                où plus rien ne dirait sur quoi elles s'appliquent. */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-add">{t('admin.form.addScript')}</Label>
              <Input
                id="ht-add"
                type="url"
                value={form.add_script}
                onChange={(e) => setForm((f) => ({ ...f, add_script: e.target.value }))}
                placeholder="https://exemple.com/scripts/create-vm.json"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-destroy">{t('admin.form.destroyScript')}</Label>
              <Input
                id="ht-destroy"
                type="url"
                value={form.destroy_script}
                onChange={(e) => setForm((f) => ({ ...f, destroy_script: e.target.value }))}
                placeholder="https://exemple.com/scripts/destroy-vm.json"
              />
            </div>
            <HypervisorActionsBlock
              typeName={form.name}
              cible="machine"
              actions={form.actions ?? []}
              onChange={(actions) => setForm((f) => ({ ...f, actions }))}
            />
          </section>
        </TabsContent>

        <TabsContent value="variables">
          <section className="flex flex-col gap-4 rounded-lg border p-4">
            <HypervisorVariablesBlock
              variables={form.variables ?? []}
              onChange={(variables) => setForm((f) => ({ ...f, variables }))}
            />
          </section>
        </TabsContent>
      </Tabs>
    </form>
  )
}

export default function AdminHypervisorTypeEditor() {
  const { t } = useTranslation()
  const { name } = useParams()
  const { typesQuery } = useAdminHypervisorTypes()
  const creation = name === 'new'

  if (creation) return <TypeForm initial={null} />
  if (typesQuery.isLoading) return <p className="text-muted-foreground">…</p>

  const type = typesQuery.data?.find((ht) => ht.name === name)
  if (!type) return <p className="text-sm text-destructive">{t('admin.hypervisorTypeEditor.notFound')}</p>
  // key = name : repart d'un formulaire neuf si on passe d'un type à un autre.
  return <TypeForm key={type.name} initial={type} />
}
