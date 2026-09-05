import { useTranslation } from 'react-i18next'
import { Trash2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { slugifier, qualifierSlugAction } from '@/shared/slug'
import type { CibleAction, HypervisorAction } from './useAdminHypervisorTypes'

interface Props {
  /** Nom du type — sert à montrer le slug qualifié réellement enregistré. */
  typeName: string
  /**
   * Cible éditée dans ce bloc. Le bloc ne voit QUE les actions de cette cible,
   * mais reçoit et rend la liste complète : les slugs doivent rester uniques
   * sur les deux familles, c'est par le slug que l'exécution retrouve l'action.
   */
  cible: CibleAction
  actions: HypervisorAction[]
  onChange: (actions: HypervisorAction[]) => void
}

/** Défaut du backend : une action sans cible explicite vise une machine. */
function cibleDe(action: HypervisorAction): CibleAction {
  return action.cible ?? 'machine'
}

/**
 * Actions supplémentaires d'un type d'hyperviseur.
 *
 * Créer et détruire sont deux actions parmi d'autres — redémarrer, étendre un
 * disque, prendre un snapshot. Chacune est un descripteur JSON du même format
 * que le script de création, donc paramétrable de la même façon.
 *
 * Le slug affiché est celui qui sera ENREGISTRÉ : le backend le préfixe par le
 * type, pour que deux types puissent proposer un « reboot » sans se confondre.
 */
export default function HypervisorActionsBlock({ typeName, cible, actions, onChange }: Props) {
  const { t } = useTranslation()

  // Indices dans la liste COMPLÈTE des actions affichées par ce bloc : l'édition
  // et la suppression portent sur la liste complète, l'affichage sur le sous-ensemble.
  const visibles = actions
    .map((action, index) => ({ action, index }))
    .filter(({ action }) => cibleDe(action) === cible)

  function set(i: number, champ: keyof HypervisorAction, valeur: string) {
    onChange(actions.map((a, j) => (j === i ? { ...a, [champ]: valeur } : a)))
  }

  // Le slug suit le libellé tant qu'il n'a pas été saisi à la main : l'inventer
  // deux fois n'apporte rien, et une saisie manuelle ne doit pas être écrasée.
  function setLabel(i: number, label: string) {
    onChange(actions.map((a, j) => (
      j === i ? { ...a, label, slug: a.slugManuel ? a.slug : slugifier(label) } : a
    )))
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        {cible === 'hyperviseur'
          ? t('admin.hypervisorActions.hintHypervisor')
          : t('admin.hypervisorActions.hintMachine')}
      </p>

      {visibles.length === 0 && (
        <p className="rounded-md border border-dashed bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {t('admin.hypervisorActions.empty')}
        </p>
      )}

      {visibles.map(({ action, index: i }) => (
        <div key={i} className="flex flex-col gap-1.5 rounded-md border p-2">
          <div className="flex items-start gap-2">
            <div className="flex flex-1 flex-col gap-1.5">
              <Input
                value={action.label}
                onChange={(e) => setLabel(i, e.target.value)}
                placeholder={t('admin.hypervisorActions.labelPlaceholder')}
              />
              <Input
                value={action.slug}
                onChange={(e) => {
                  onChange(actions.map((a, j) => (
                    j === i ? { ...a, slug: e.target.value, slugManuel: true } : a
                  )))
                }}
                placeholder="reboot"
                pattern="^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$"
                required
              />
              <Input
                type="url"
                value={action.script}
                onChange={(e) => set(i, 'script', e.target.value)}
                placeholder="https://exemple.com/scripts/reboot-vm.json"
              />
            </div>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="text-destructive hover:text-destructive"
              aria-label={t('admin.hypervisorActions.remove')}
              onClick={() => onChange(actions.filter((_, j) => j !== i))}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
          {action.slug && (
            <p className="font-mono text-xs text-muted-foreground">
              {t('admin.hypervisorActions.savedAs')} {qualifierSlugAction(typeName, action.slug)}
            </p>
          )}
        </div>
      ))}

      <Button
        type="button"
        size="sm"
        variant="outline"
        className="self-start"
        onClick={() => onChange([...actions, { label: '', slug: '', script: '', cible }])}
      >
        <Plus className="mr-1 h-3.5 w-3.5" />
        {t('admin.hypervisorActions.add')}
      </Button>
    </div>
  )
}
