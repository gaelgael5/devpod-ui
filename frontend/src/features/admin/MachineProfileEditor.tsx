import { useMemo, useState } from 'react'
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
import { useTypeScriptSpec, flattenArgs, valeursParDefaut } from './useProxmoxScript'
import { useAdminRecipes } from './useAdminRecipes'
import type { RecipeOption } from '@/features/recipes/types'
import {
  nomDeploiementLibre,
  slugifier,
  useSaveMachineProfile,
  type MachineProfile,
} from './useMachineProfiles'
import { useTemplates } from '@/features/compose/hooks/useCompose'

interface Props {
  profile: MachineProfile
  /**
   * Types proposes dans le selecteur. Le couple complet, pas le seul `name` :
   * c'est le libelle qui se lit (« Proxmox4vm »), le `name` n'est que la clef
   * technique stockee dans le profil.
   */
  hypervisorTypes: { name: string; label: string }[]
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
  const { data: spec } = useTypeScriptSpec(brouillon.hypervisor_type)
  const { recipesQuery } = useAdminRecipes()
  const { data: templates = [] } = useTemplates()

  const nouveau = !profile.slug
  // Le slug suit le libelle tant qu'on n'y a pas touche : le derive
  // automatiquement evite d'avoir a l'inventer, mais une saisie manuelle ne
  // doit pas etre ecrasee au caractere suivant.
  const [slugManuel, setSlugManuel] = useState(false)
  const recettes = recipesQuery.data ?? []

  function set<K extends keyof MachineProfile>(clef: K, valeur: MachineProfile[K]) {
    setBrouillon((b) => ({ ...b, [clef]: valeur }))
  }

  // Un profil s'ouvre avec les valeurs que le JSON du script propose, pas vide :
  // sinon les listes fermees (source du template, stockage, type de CPU)
  // s'affichent blanches et se sauvegardent sans valeur, alors que la spec en a
  // une utilisable. Derive plutot qu'ecrit dans le state : la spec arrive apres
  // le montage, et un setState en effet relance un rendu pour rien.
  const defauts = useMemo(() => {
    if (!spec) return {}
    const d = valeursParDefaut(spec.args)
    // L'identifiant (vmid) se choisit machine par machine : le figer dans un
    // profil ecraserait le choix fait a la creation.
    for (const a of flattenArgs(spec.args)) if (a.identifier) delete d[a.arg]
    return d
  }, [spec])
  // Les choix enregistres priment sur les defauts, jamais l'inverse.
  const params = useMemo(
    () => ({ ...defauts, ...brouillon.params }),
    [defauts, brouillon.params],
  )

  function valider() {
    toast.promise(enregistrer.mutateAsync({ ...brouillon, params }), {
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
            <Input
              value={brouillon.label}
              onChange={(e) => {
                const label = e.target.value
                setBrouillon((b) => ({
                  ...b,
                  label,
                  slug: nouveau && !slugManuel ? slugifier(label) : b.slug,
                }))
              }}
            />
          </div>
          <div>
            <Label>{t('admin.machineProfiles.slug')}</Label>
            {/* Le slug est l'identité : le changer désigne un autre profil, et
                les machines déjà créées gardent l'ancien. */}
            <Input
              value={brouillon.slug}
              disabled={!nouveau}
              onChange={(e) => {
                setSlugManuel(true)
                set('slug', e.target.value)
              }}
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
                {/* Meme ordre que l'usage d'un host, sans « portail » : le
                    portail ne se cree pas depuis un profil. */}
                <SelectItem value="workspaces">
                  {t('admin.machineProfiles.type.workspaces')}
                </SelectItem>
                <SelectItem value="test">{t('admin.machineProfiles.type.test')}</SelectItem>
                <SelectItem value="ressources">
                  {t('admin.machineProfiles.type.ressources')}
                </SelectItem>
                <SelectItem value="autres">{t('admin.machineProfiles.type.autres')}</SelectItem>
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
                {hypervisorTypes.map((ty) => (
                  <SelectItem key={ty.name} value={ty.name}>{ty.label || ty.name}</SelectItem>
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
                args={spec.args}
                values={params}
                onChange={(k, v) => set('params', { ...params, [k]: v })}
                excludeIdentifier
                templating
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
                  {Object.entries(meta?.options ?? {}).map(([clef, decl]: [string, RecipeOption]) => (
                    <div key={clef} className="mt-1.5">
                      <Label className="text-xs">
                        {clef}
                        {/* Ce qui s'injecte doit se lire AVANT de lancer, pas
                            se deviner : l'option declare d'ou vient sa valeur. */}
                        {decl.from_context && (
                          <span className="ml-2 font-normal text-muted-foreground">
                            {t('admin.machineProfiles.inherited', { source: decl.from_context })}
                          </span>
                        )}
                      </Label>
                      <Input
                        className="h-8"
                        placeholder={
                          decl.from_context
                            ? t('admin.machineProfiles.inheritedPlaceholder')
                            : decl.default
                        }
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

          <TabsContent value="services" className="flex flex-col gap-2 pt-3">
            {/* Un service est un TEMPLATE COMPOSE existant : il porte deja son
                compose, ses parametres types et sa version. On saisit ici ses
                valeurs et le nom sous lequel il sera deploye. */}
            {brouillon.services.map((sv, i) => {
              const tpl = templates.find((x) => x.id === sv.template_id)
              return (
                <div
                  key={sv.deployment_id}
                  className="rounded border p-2"
                  data-testid={`service-${sv.deployment_id}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{tpl?.name ?? sv.template_id}</span>
                    <Button
                      size="icon" variant="ghost" className="h-6 w-6 text-destructive"
                      onClick={() =>
                        set('services', brouillon.services.filter((_, j) => j !== i))
                      }
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                  <div className="mt-1.5">
                    <Label className="text-xs">{t('admin.machineProfiles.deploymentId')}</Label>
                    {/* Deux instances du meme template doivent pouvoir coexister :
                        c'est ce nom qui les distingue. */}
                    <Input
                      className="h-8"
                      value={sv.deployment_id}
                      onChange={(e) => {
                        const suite = [...brouillon.services]
                        suite[i] = { ...sv, deployment_id: e.target.value }
                        set('services', suite)
                      }}
                    />
                  </div>
                  {(tpl?.parameters ?? []).map((param) => (
                    <div key={param.key} className="mt-1.5">
                      <Label className="text-xs">
                        {param.label}
                        {param.required && ' *'}
                      </Label>
                      <Input
                        className="h-8"
                        placeholder={param.default ?? ''}
                        value={sv.params[param.key] ?? ''}
                        onChange={(e) => {
                          const suite = [...brouillon.services]
                          suite[i] = {
                            ...sv,
                            params: { ...sv.params, [param.key]: e.target.value },
                          }
                          set('services', suite)
                        }}
                      />
                    </div>
                  ))}
                </div>
              )
            })}
            <Select
              value=""
              onValueChange={(id) => {
                set('services', [
                  ...brouillon.services,
                  {
                    template_id: id,
                    deployment_id: nomDeploiementLibre(
                      id,
                      brouillon.services.map((x) => x.deployment_id),
                    ),
                    params: {},
                  },
                ])
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder={t('admin.machineProfiles.addService')} />
              </SelectTrigger>
              <SelectContent>
                {templates.map((tpl) => (
                  <SelectItem key={tpl.id} value={tpl.id}>{tpl.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
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
