import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import HypervisorArgsForm from './HypervisorArgsForm'
import { useTypeScriptSpec, flattenArgs } from './useProxmoxScript'
import { useAdminRecipes } from './useAdminRecipes'
import { useSaveMachineProfile, type MachineProfile } from './useMachineProfiles'

interface Props {
  profile: MachineProfile
  hypervisorTypes: string[]
  onClose: () => void
}

/**
 * Éditeur d'un profil : identité, paramètres de création, recettes, services.
 *
 * Les paramètres sont générés depuis la spec du script du type d'hyperviseur —
 * c'est ce qui permet de les valider et de les présenter comme à la création
 * d'une machine, plutôt qu'en couples clé/valeur libres.
 */
export default function MachineProfileEditor({ profile, hypervisorTypes, onClose }: Props) {
  const { t } = useTranslation()
  const [brouillon, setBrouillon] = useState<MachineProfile>(profile)
  const enregistrer = useSaveMachineProfile()
  const { spec } = useTypeScriptSpec(brouillon.hypervisor_type)
  const { recipesQuery } = useAdminRecipes()

  const nouveau = !profile.slug
  const recettes = recipesQuery.data ?? []

  function set<K extends keyof MachineProfile>(clef: K, valeur: MachineProfile[K]) {
    setBrouillon((b) => ({ ...b, [clef]: valeur }))
  }

  function valider() {
    toast.promise(enregistrer.mutateAsync(brouillon), {
      loading: '…',
      success: () => {
        onClose()
        return t('admin.machineProfiles.saved')
      },
      error: (e: Error) => e.message,
    })
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {nouveau ? t('admin.machineProfiles.new') : brouillon.label}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label>{t('admin.machineProfiles.label')}</Label>
            <Input value={brouillon.label} onChange={(e) => set('label', e.target.value)} />
          </div>
          <div>
            <Label>{t('admin.machineProfiles.slug')}</Label>
            {/* Le slug est l'identité : le changer désigne un autre profil, et
                les machines déjà créées gardent l'ancien. */}
            <Input
              value={brouillon.slug}
              disabled={!nouveau}
              onChange={(e) => set('slug', e.target.value)}
            />
          </div>
          <div>
            <Label>{t('admin.machineProfiles.machineType')}</Label>
            <Select
              value={brouillon.machine_type}
              onValueChange={(v) => set('machine_type', v as MachineProfile['machine_type'])}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="test">{t('admin.machineProfiles.type.test')}</SelectItem>
                <SelectItem value="ressources">
                  {t('admin.machineProfiles.type.ressources')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>{t('admin.machineProfiles.hypervisorType')}</Label>
            <Select
              value={brouillon.hypervisor_type}
              onValueChange={(v) => set('hypervisor_type', v)}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {hypervisorTypes.map((n) => (
                  <SelectItem key={n} value={n}>{n}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <Tabs defaultValue="params" className="mt-2">
          <TabsList>
            <TabsTrigger value="params">{t('admin.machineProfiles.tabParams')}</TabsTrigger>
            <TabsTrigger value="recipes">{t('admin.machineProfiles.tabRecipes')}</TabsTrigger>
            <TabsTrigger value="services">{t('admin.machineProfiles.tabServices')}</TabsTrigger>
          </TabsList>

          <TabsContent value="params" className="pt-3">
            {spec ? (
              <HypervisorArgsForm
                args={flattenArgs(spec)}
                values={brouillon.params}
                onChange={(k, v) => set('params', { ...brouillon.params, [k]: v })}
                excludeIdentifier
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                {t('admin.machineProfiles.noSpec')}
              </p>
            )}
          </TabsContent>

          <TabsContent value="recipes" className="flex flex-col gap-2 pt-3">
            {/* Une recette se choisit AVEC ses options : l'AVD, la RAM, le
                niveau d'API se décident ici, pas à la création. */}
            {brouillon.recipes.map((r, i) => {
              const meta = recettes.find((x) => x.key === r.key)
              return (
                <div key={r.key} className="rounded border p-2" data-testid={`recette-${r.key}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{meta?.id ?? r.key}</span>
                    <Button
                      size="icon" variant="ghost" className="h-6 w-6 text-destructive"
                      onClick={() =>
                        set('recipes', brouillon.recipes.filter((_, j) => j !== i))
                      }
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                  {Object.entries(meta?.options ?? {}).map(([clef, decl]) => (
                    <div key={clef} className="mt-1.5">
                      <Label className="text-xs">{clef}</Label>
                      <Input
                        className="h-8"
                        placeholder={decl.default}
                        value={r.options[clef] ?? ''}
                        onChange={(e) => {
                          const suite = [...brouillon.recipes]
                          suite[i] = { ...r, options: { ...r.options, [clef]: e.target.value } }
                          set('recipes', suite)
                        }}
                      />
                    </div>
                  ))}
                </div>
              )
            })}
            <Select
              value=""
              onValueChange={(key) =>
                set('recipes', [...brouillon.recipes, { key, options: {} }])
              }
            >
              <SelectTrigger><SelectValue placeholder={t('admin.machineProfiles.addRecipe')} /></SelectTrigger>
              <SelectContent>
                {recettes
                  .filter((r) => !brouillon.recipes.some((x) => x.key === r.key))
                  .map((r) => (
                    <SelectItem key={r.key} value={r.key}>{r.id}</SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </TabsContent>

          <TabsContent value="services" className="pt-3">
            <p className="text-sm text-muted-foreground">
              {t('admin.machineProfiles.servicesSoon')}
            </p>
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={valider} disabled={!brouillon.slug || !brouillon.label}>
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
