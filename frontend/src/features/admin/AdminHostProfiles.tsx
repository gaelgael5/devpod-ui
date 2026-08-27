import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Gauge, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { CAPACITY_VARIABLE } from './useAdminHypervisorTypes'
import { useMachineProfiles } from './useMachineProfiles'
import {
  profilHostVide, useDeleteHostProfile, useHostProfiles, type HostProfile,
} from './useHostProfiles'
import HostProfileEditor from './HostProfileEditor'

/**
 * Profils de host : ce qu'un forfait provisionne.
 *
 * Le profil de machine sait CONSTRUIRE la VM — RAM, disque, gabarit. Il ne sait
 * pas ce qu'elle vaut a l'usage. Le profil de host ajoute cette couche : il
 * choisit un profil de machine et value les variables declarees par son type
 * d'hyperviseur, dont la capacite en workspaces.
 */
export default function AdminHostProfiles() {
  const { t } = useTranslation()
  const { data: profils = [], isLoading } = useHostProfiles()
  const { data: machines = [] } = useMachineProfiles()
  const supprimer = useDeleteHostProfile()
  const [edite, setEdite] = useState<HostProfile | null>(null)

  function nouveau() {
    if (machines.length === 0) {
      // Sans profil de machine, il n'y a ni type d'hyperviseur ni variables :
      // le formulaire serait vide et le profil inapplicable.
      toast.error(t('admin.hostProfiles.noMachineProfile'))
      return
    }
    setEdite(profilHostVide(machines[0].slug))
  }

  return (
    <div className="mx-auto max-w-4xl p-4">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t('admin.hostProfiles.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t('admin.hostProfiles.description')}
          </p>
        </div>
        <Button size="sm" onClick={nouveau} className="shrink-0 gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          {t('admin.hostProfiles.new')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

      {!isLoading && profils.length === 0 && (
        <p className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t('admin.hostProfiles.empty')}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {profils.map((p) => {
          const capacite = p.variables[CAPACITY_VARIABLE]
          return (
            <div
              key={p.slug}
              className="flex items-start justify-between gap-3 rounded-lg border p-3"
              data-testid={`host-profil-${p.slug}`}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{p.label}</span>
                  <span className="font-mono text-xs text-muted-foreground">{p.slug}</span>
                  {capacite && (
                    <span className="flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                      <Gauge className="h-3 w-3" />
                      {t('admin.hostProfiles.capacityBadge', { count: Number(capacite) })}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{p.machine_profile}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  aria-label={t('workspaces.actions.edit')}
                  onClick={() => setEdite(p)}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-destructive hover:text-destructive"
                  aria-label={t('workspaces.actions.delete')}
                  onClick={() =>
                    toast.promise(supprimer.mutateAsync(p.slug), {
                      loading: '…',
                      success: t('admin.hostProfiles.deleted'),
                      error: (e: Error) => e.message,
                    })
                  }
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )
        })}
      </div>

      {edite && (
        <HostProfileEditor
          profile={edite}
          machineProfiles={machines}
          onClose={() => setEdite(null)}
        />
      )}
    </div>
  )
}
