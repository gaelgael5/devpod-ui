import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  useDeleteMachineProfile,
  useMachineProfiles,
  profilVide,
  type MachineProfile,
} from './useMachineProfiles'
import MachineProfileEditor from './MachineProfileEditor'
import { useAdminHypervisorTypes } from './useAdminHypervisorTypes'

/**
 * Profils de machine : modèles prêts à l'emploi pour créer une machine.
 *
 * Remplace le bouton « Test host config » de la page Hosts, qui n'offrait
 * qu'UN seul jeu de paramètres par type d'hyperviseur. Un profil est nommé,
 * porte ses paramètres, les recettes à installer et les services à lancer.
 */
export default function AdminMachineProfiles() {
  const { t } = useTranslation()
  const { data: profils = [], isLoading } = useMachineProfiles()
  const { typesQuery } = useAdminHypervisorTypes()
  const supprimer = useDeleteMachineProfile()
  const [edite, setEdite] = useState<MachineProfile | null>(null)

  const types = typesQuery.data ?? []

  function nouveau() {
    if (types.length === 0) {
      // Un profil sans type d'hyperviseur n'a pas de paramètres à afficher :
      // ils sont typés par la spec du script de ce type.
      toast.error(t('admin.machineProfiles.noHypervisorType'))
      return
    }
    setEdite(profilVide(types[0].name))
  }

  return (
    <div className="mx-auto max-w-4xl p-4">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t('admin.machineProfiles.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t('admin.machineProfiles.description')}
          </p>
        </div>
        <Button size="sm" onClick={nouveau} className="shrink-0 gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          {t('admin.machineProfiles.new')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

      {!isLoading && profils.length === 0 && (
        <p className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t('admin.machineProfiles.empty')}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {profils.map((p) => (
          <div
            key={p.slug}
            className="flex items-start justify-between gap-3 rounded-lg border p-3"
            data-testid={`profil-${p.slug}`}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{p.label}</span>
                <span className="font-mono text-xs text-muted-foreground">{p.slug}</span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                  {t(`admin.machineProfiles.type.${p.machine_type}`)}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {p.hypervisor_type}
                {' · '}
                {t('admin.machineProfiles.counts', {
                  recipes: p.recipes.length,
                  services: p.services.length,
                })}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setEdite(p)}>
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive hover:text-destructive"
                onClick={() =>
                  toast.promise(supprimer.mutateAsync(p.slug), {
                    loading: '…',
                    success: t('admin.machineProfiles.deleted'),
                    error: (e: Error) => e.message,
                  })
                }
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      {edite && (
        <MachineProfileEditor
          profile={edite}
          hypervisorTypes={types.map((ty) => ({ name: ty.name, label: ty.label }))}
          onClose={() => setEdite(null)}
        />
      )}
    </div>
  )
}
