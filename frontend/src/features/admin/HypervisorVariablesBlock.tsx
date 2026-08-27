import { useTranslation } from 'react-i18next'
import { Trash2, Plus, Gauge } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { slugifier } from '@/shared/slug'
import { CAPACITY_VARIABLE, type HypervisorVariable } from './useAdminHypervisorTypes'

interface Props {
  variables: HypervisorVariable[]
  onChange: (variables: HypervisorVariable[]) => void
}

/**
 * Variables declarees par un type d'hyperviseur.
 *
 * Le type dit CE QUI EXISTE, le profil de host dira COMBIEN. La declaration vit
 * ici parce qu'elle depend de l'hyperviseur et de ce que l'exploitant sait de
 * ses machines : personne d'autre que lui ne peut dire combien de workspaces
 * tient un gabarit donne.
 *
 * `capacity_workspaces` s'ajoute d'un clic plutot qu'a la main : c'est le seul
 * slug que le portail LIT, une faute de frappe le rendrait invisible sans rien
 * signaler.
 */
export default function HypervisorVariablesBlock({ variables, onChange }: Props) {
  const { t } = useTranslation()
  const aLaCapacite = variables.some((v) => v.slug === CAPACITY_VARIABLE)

  function set(i: number, champ: keyof HypervisorVariable, valeur: string) {
    onChange(variables.map((v, j) => (j === i ? { ...v, [champ]: valeur } : v)))
  }

  // Le slug suit le libelle tant qu'il n'a pas ete saisi a la main.
  function setLabel(i: number, label: string) {
    onChange(variables.map((v, j) => (
      j === i ? { ...v, label, slug: v.slugManuel ? v.slug : slugifier(label) } : v
    )))
  }

  return (
    <div className="flex flex-col gap-2">
      <Label>{t('admin.hypervisorVariables.title')}</Label>
      <p className="text-xs text-muted-foreground">{t('admin.hypervisorVariables.hint')}</p>

      {variables.length === 0 && (
        <p className="rounded-md border border-dashed bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {t('admin.hypervisorVariables.empty')}
        </p>
      )}

      {variables.map((variable, i) => (
        <div key={i} className="flex items-start gap-2 rounded-md border p-2">
          <div className="flex flex-1 flex-col gap-1.5">
            <Input
              value={variable.label}
              onChange={(e) => setLabel(i, e.target.value)}
              placeholder={t('admin.hypervisorVariables.labelPlaceholder')}
              aria-label={t('admin.hypervisorVariables.labelPlaceholder')}
            />
            <div className="flex gap-1.5">
              <Input
                className="flex-1 font-mono"
                value={variable.slug}
                onChange={(e) => {
                  onChange(variables.map((v, j) => (
                    j === i ? { ...v, slug: e.target.value, slugManuel: true } : v
                  )))
                }}
                placeholder="capacity_workspaces"
                aria-label={t('admin.hypervisorVariables.slugLabel')}
                pattern="^[a-z0-9]([a-z0-9_-]{0,38}[a-z0-9])?$"
                required
              />
              {/* Deux types seulement : ce qui se compte, et ce qui se lit. */}
              <select
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                value={variable.type}
                aria-label={t('admin.hypervisorVariables.typeLabel')}
                onChange={(e) => set(i, 'type', e.target.value)}
              >
                <option value="string">{t('admin.hypervisorVariables.typeString')}</option>
                <option value="int">{t('admin.hypervisorVariables.typeInt')}</option>
              </select>
            </div>
            {variable.slug === CAPACITY_VARIABLE && (
              <Badge variant="secondary" className="self-start gap-1">
                <Gauge className="h-3 w-3" />
                {t('admin.hypervisorVariables.capacityBadge')}
              </Badge>
            )}
          </div>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            aria-label={t('admin.hypervisorVariables.remove')}
            onClick={() => onChange(variables.filter((_, j) => j !== i))}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onChange([...variables, { label: '', slug: '', type: 'string' }])}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          {t('admin.hypervisorVariables.add')}
        </Button>
        {!aLaCapacite && (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => onChange([...variables, {
              label: t('admin.hypervisorVariables.capacityLabel'),
              slug: CAPACITY_VARIABLE,
              type: 'int',
              slugManuel: true,
            }])}
          >
            <Gauge className="mr-1 h-3.5 w-3.5" />
            {t('admin.hypervisorVariables.addCapacity')}
          </Button>
        )}
      </div>
    </div>
  )
}
