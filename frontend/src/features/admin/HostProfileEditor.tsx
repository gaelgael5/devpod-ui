import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Gauge } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { slugifier } from '@/shared/slug'
import { CAPACITY_VARIABLE } from './useAdminHypervisorTypes'
import {
  useHostProfileVariables, useSaveHostProfile, type HostProfile,
} from './useHostProfiles'
import type { MachineProfile } from './useMachineProfiles'

interface Props {
  profile: HostProfile
  machineProfiles: MachineProfile[]
  onClose: () => void
}

/**
 * Edition d'un profil de host.
 *
 * Le formulaire des variables n'est pas fige dans le code : il se construit a
 * partir de ce que DECLARE le type d'hyperviseur du profil de machine choisi.
 * Changer de profil de machine change donc les variables a renseigner — c'est
 * voulu, un gabarit Proxmox et un gabarit AWS n'ont pas les memes grandeurs.
 */
export default function HostProfileEditor({ profile, machineProfiles, onClose }: Props) {
  const { t } = useTranslation()
  const [brouillon, setBrouillon] = useState<HostProfile>(profile)
  const [slugManuel, setSlugManuel] = useState(Boolean(profile.slug))
  const enregistrer = useSaveHostProfile()

  const { data: declarees = [], isLoading } = useHostProfileVariables(brouillon.machine_profile)

  const machine = useMemo(
    () => machineProfiles.find((m) => m.slug === brouillon.machine_profile),
    [machineProfiles, brouillon.machine_profile],
  )

  function setVariable(slug: string, valeur: string) {
    setBrouillon((b) => ({ ...b, variables: { ...b.variables, [slug]: valeur } }))
  }

  // Le slug suit le libelle tant qu'il n'a pas ete saisi a la main.
  function setLabel(label: string) {
    setBrouillon((b) => ({ ...b, label, slug: slugManuel ? b.slug : slugifier(label) }))
  }

  function soumettre(e: React.FormEvent) {
    e.preventDefault()
    // Les variables retirees de la declaration seraient refusees par le
    // backend : on n'envoie que ce qui est encore declare.
    const declares = new Set(declarees.map((v) => v.slug))
    const variables = Object.fromEntries(
      Object.entries(brouillon.variables).filter(([slug, v]) => declares.has(slug) && v !== ''),
    )
    toast.promise(enregistrer.mutateAsync({ ...brouillon, variables }), {
      loading: '…',
      success: () => {
        onClose()
        return t('admin.hostProfiles.saved')
      },
      error: (err: Error) => err.message,
    })
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {profile.slug ? t('admin.hostProfiles.edit') : t('admin.hostProfiles.new')}
          </DialogTitle>
          <DialogDescription>{t('admin.hostProfiles.description')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={soumettre} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="hp-label">{t('admin.hostProfiles.label')}</Label>
            <Input
              id="hp-label"
              value={brouillon.label}
              onChange={(e) => setLabel(e.target.value)}
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="hp-slug">{t('admin.hostProfiles.slug')}</Label>
            <Input
              id="hp-slug"
              className="font-mono"
              value={brouillon.slug}
              onChange={(e) => {
                setSlugManuel(true)
                setBrouillon((b) => ({ ...b, slug: e.target.value }))
              }}
              pattern="^[a-z0-9][a-z0-9-]{0,62}$"
              required
              // Le slug est l'identite : le changer designe un autre profil.
              disabled={Boolean(profile.slug)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="hp-machine">{t('admin.hostProfiles.machineProfile')}</Label>
            <select
              id="hp-machine"
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
              value={brouillon.machine_profile}
              onChange={(e) =>
                setBrouillon((b) => ({ ...b, machine_profile: e.target.value }))
              }
            >
              {machineProfiles.map((m) => (
                <option key={m.slug} value={m.slug}>{m.label}</option>
              ))}
            </select>
            {machine && (
              <p className="text-xs text-muted-foreground">
                {t('admin.hostProfiles.viaType', { type: machine.hypervisor_type })}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label>{t('admin.hostProfiles.variables')}</Label>
            <p className="text-xs text-muted-foreground">
              {t('admin.hostProfiles.variablesHint')}
            </p>

            {isLoading && (
              <p className="text-xs text-muted-foreground">{t('common.loading')}</p>
            )}

            {!isLoading && declarees.length === 0 && (
              <p className="rounded-md border border-dashed bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                {t('admin.hostProfiles.noVariables')}
              </p>
            )}

            {declarees.map((v) => (
              <div key={v.slug} className="flex flex-col gap-1">
                <Label htmlFor={`hp-var-${v.slug}`} className="text-xs font-normal">
                  {v.label || v.slug}
                  <span className="ml-2 font-mono text-muted-foreground">{v.slug}</span>
                </Label>
                <Input
                  id={`hp-var-${v.slug}`}
                  type={v.type === 'int' ? 'number' : 'text'}
                  value={brouillon.variables[v.slug] ?? ''}
                  onChange={(e) => setVariable(v.slug, e.target.value)}
                  // La capacite est ce que le portail LIT pour savoir combien de
                  // workspaces la machine tient : la laisser vide la rend
                  // « non renseignee », pas « illimitee ».
                  required={v.slug === CAPACITY_VARIABLE}
                />
                {v.slug === CAPACITY_VARIABLE && (
                  <p className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Gauge className="h-3 w-3" />
                    {t('admin.hostProfiles.capacityHint')}
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button type="submit" disabled={enregistrer.isPending}>
              {t('admin.form.save')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
