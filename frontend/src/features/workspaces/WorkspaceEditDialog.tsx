import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useRecipes } from '@/features/recipes/useRecipes'
import OrderedRecipePicker from '@/features/recipes/OrderedRecipePicker'
import { useHosts } from '@/features/admin/useHosts'
import { useProfiles } from '@/features/profiles/hooks/useProfiles'
import type { WorkspaceSpec } from './types'
import { useUpdateWorkspace, type WorkspacePatch } from './useUpdateWorkspace'

interface Props {
  spec: WorkspaceSpec
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Proposé quand la modification exige une reconstruction de l'image. */
  onRecreate?: (name: string) => void
}

function profileValue(spec: WorkspaceSpec): string {
  return spec.profile ? `${spec.profile.scope}:${spec.profile.slug}` : ''
}

/**
 * Édition de la configuration d'un workspace DÉJÀ créé.
 *
 * Le serveur décide seul de l'impact (`requires_recreate`) : certains champs
 * n'entrent que dans le devcontainer.json et n'ont donc AUCUN effet tant que
 * l'image n'est pas reconstruite — typiquement l'ajout d'une recette. On
 * enregistre toujours, puis on prévient ; recréer reste une décision de
 * l'utilisateur (l'opération détruit le travail non commité).
 */
export default function WorkspaceEditDialog({ spec, open, onOpenChange, onRecreate }: Props) {
  const { t } = useTranslation()
  const { data: recipes = [] } = useRecipes('install')
  const { data: hosts = [] } = useHosts()
  const { data: profiles = [] } = useProfiles()
  const update = useUpdateWorkspace(spec.name)

  const [branch, setBranch] = useState(spec.branch ?? '')
  const [host, setHost] = useState(spec.host ?? '')
  const [selectedRecipes, setSelectedRecipes] = useState<string[]>(spec.recipes ?? [])
  const [profile, setProfile] = useState(profileValue(spec))
  const [memoryLimit, setMemoryLimit] = useState(spec.memory_limit ?? '')
  const [pending, setPending] = useState<string[]>([])

  async function save() {
    const patch: WorkspacePatch = {
      branch,
      host,
      recipes: selectedRecipes,
      memory_limit: memoryLimit,
      profile: profile
        ? {
            scope: profile.split(':')[0] as 'shared' | 'user',
            slug: profile.split(':')[1],
          }
        : null,
    }
    try {
      const res = await update.mutateAsync(patch)
      if (res.requires_recreate.length > 0) {
        // On NE recrée pas d'office : on expose l'impact et on laisse la main.
        setPending(res.requires_recreate)
        const added = res.added_recipes
        toast.warning(
          added.length > 0
            ? t('workspaces.edit.addedRecipes', {
                list: added.join(', '),
                defaultValue: 'Recettes ajoutées ({{list}}) — recréez pour les installer',
              })
            : t('workspaces.edit.needsRecreate', {
                defaultValue: 'Modification enregistrée — recréez pour l’appliquer',
              }),
        )
        return
      }
      toast.success(t('workspaces.edit.saved', { defaultValue: 'Configuration enregistrée' }))
      onOpenChange(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t('workspaces.edit.title', {
              name: spec.name,
              defaultValue: 'Configuration de {{name}}',
            })}
          </DialogTitle>
          <DialogDescription>
            {t('workspaces.edit.description', {
              defaultValue:
                'Les modifications sont enregistrées immédiatement. Certaines ne prennent effet qu’après recréation du workspace.',
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-branch">{t('workspaces.form.branch')}</Label>
            <Input
              id="edit-branch"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              placeholder="main"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-host">{t('workspaces.form.host')}</Label>
            <select
              id="edit-host"
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={host}
              onChange={(e) => setHost(e.target.value)}
            >
              <option value="">—</option>
              {hosts.map((h) => (
                <option key={h.name} value={h.name}>
                  {h.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-profile">{t('workspaces.form.profile')}</Label>
            <select
              id="edit-profile"
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={profile}
              onChange={(e) => setProfile(e.target.value)}
            >
              <option value="">—</option>
              {profiles.map((p) => (
                <option key={`${p.scope}:${p.slug}`} value={`${p.scope}:${p.slug}`}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>{t('workspaces.form.recipes')}</Label>
            <OrderedRecipePicker
              recipes={recipes}
              selected={selectedRecipes}
              onChange={setSelectedRecipes}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-memory">{t('workspaces.form.memoryLimit')}</Label>
            <Input
              id="edit-memory"
              value={memoryLimit}
              onChange={(e) => setMemoryLimit(e.target.value)}
              placeholder="2g"
            />
          </div>

          {pending.length > 0 && (
            <div
              className="flex flex-col gap-2 rounded-md border border-amber-500/50 bg-amber-50 p-3 text-xs text-amber-800"
              data-testid="edit-recreate-warning"
            >
              <div className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                {t('workspaces.edit.recreateTitle', {
                  defaultValue: 'Recréation nécessaire pour appliquer :',
                })}
              </div>
              <div className="font-mono">{pending.join(', ')}</div>
              <p className="text-amber-700/90">
                {t('workspaces.edit.recreateWarning', {
                  defaultValue:
                    'La recréation reconstruit le conteneur : le travail non commité est perdu.',
                })}
              </p>
              {onRecreate && (
                <Button
                  size="sm"
                  variant="outline"
                  className="self-start"
                  onClick={() => {
                    onRecreate(spec.name)
                    onOpenChange(false)
                  }}
                >
                  {t('workspaces.edit.recreateNow', { defaultValue: 'Recréer maintenant' })}
                </Button>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            {t('workspaces.confirm.cancel')}
          </Button>
          <Button size="sm" onClick={save} disabled={update.isPending}>
            {update.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {t('workspaces.edit.save', { defaultValue: 'Enregistrer' })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
