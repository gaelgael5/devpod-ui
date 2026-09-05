/**
 * Galerie des templates de création de workspace — l'écran admin.
 *
 * Un template fige recettes, agents, profil devcontainer, limite mémoire et
 * clef SSH ; l'utilisateur ne saisit ensuite que le nom et le repo git.
 * `published` gouverne la visibilité : un brouillon n'apparaît jamais dans le
 * dialogue de création.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRecipes } from '@/features/recipes/useRecipes'
import OrderedRecipePicker from '@/features/recipes/OrderedRecipePicker'
import ProfileSelector from '@/features/workspaces/ProfileSelector'
import { useProfiles } from '@/features/profiles/hooks/useProfiles'
import { useAgentTypes } from '@/features/mcp/api'
import {
  SPEC_VIDE,
  useAdminWorkspaceTemplates,
  useDeleteWorkspaceTemplate,
  useSaveWorkspaceTemplate,
  type WorkspaceTemplate,
} from '@/features/workspaces/useWorkspaceTemplates'

const SLUG_RE = /^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$/

function vide(slug = ''): WorkspaceTemplate {
  return { slug, label: '', description: '', published: false, spec: { ...SPEC_VIDE } }
}

export default function AdminWorkspaceTemplates() {
  const { t } = useTranslation()
  const { data: templates = [], isLoading } = useAdminWorkspaceTemplates()
  const { data: recipes = [] } = useRecipes('install')
  const { data: initializeRecipes = [] } = useRecipes('initialize')
  const { data: profiles = [] } = useProfiles()
  const { data: agentTypes = [] } = useAgentTypes()
  const save = useSaveWorkspaceTemplate()
  const supprimer = useDeleteWorkspaceTemplate()

  // null = aucun éditeur ouvert ; sinon la copie de travail du template.
  const [edite, setEdite] = useState<WorkspaceTemplate | null>(null)
  const [nouveau, setNouveau] = useState(false)
  const [slugError, setSlugError] = useState('')

  function ouvrir(template: WorkspaceTemplate | null) {
    setNouveau(template === null)
    setEdite(template ? structuredClone(template) : vide())
    setSlugError('')
  }

  function poserSpec<K extends keyof WorkspaceTemplate['spec']>(
    champ: K,
    valeur: WorkspaceTemplate['spec'][K],
  ) {
    setEdite((prev) => (prev ? { ...prev, spec: { ...prev.spec, [champ]: valeur } } : prev))
  }

  async function enregistrer() {
    if (!edite) return
    if (!SLUG_RE.test(edite.slug)) {
      setSlugError(t('adminWsTemplates.slugHint'))
      return
    }
    setSlugError('')
    try {
      await save.mutateAsync(edite)
      toast.success(t('adminWsTemplates.saved'))
      setEdite(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('errors.generic'))
    }
  }

  const profilValue = edite?.spec.profile
    ? `${edite.spec.profile.scope}:${edite.spec.profile.slug}`
    : ''

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('adminWsTemplates.title')}</h1>
        <Button onClick={() => ouvrir(null)}>{t('adminWsTemplates.new')}</Button>
      </div>
      <p className="mb-4 text-sm text-muted-foreground">{t('adminWsTemplates.intro')}</p>

      {isLoading && <p className="text-sm text-muted-foreground">…</p>}
      {!isLoading && templates.length === 0 && !edite && (
        <p className="text-sm text-muted-foreground">{t('adminWsTemplates.empty')}</p>
      )}

      <div className="flex flex-col gap-2">
        {templates.map((template) => (
          <div
            key={template.slug}
            className="flex items-center justify-between rounded-md border px-3 py-2"
          >
            <div>
              <span className="font-medium">{template.label || template.slug}</span>
              <span className="ml-2 text-xs text-muted-foreground">{template.slug}</span>
              {!template.published && (
                <span className="ml-2 rounded-sm bg-muted px-1.5 py-0.5 text-xs">
                  {t('adminWsTemplates.draft')}
                </span>
              )}
              <p className="text-xs text-muted-foreground">
                {t('adminWsTemplates.summary', {
                  recipes: template.spec.recipes.length,
                  agents: template.spec.agents.length,
                })}
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => ouvrir(template)}>
                {t('common.edit')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    await supprimer.mutateAsync(template.slug)
                    toast.success(t('adminWsTemplates.deleted'))
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : t('errors.generic'))
                  }
                }}
              >
                {t('common.delete')}
              </Button>
            </div>
          </div>
        ))}
      </div>

      {edite && (
        <div className="mt-6 flex flex-col gap-4 rounded-md border p-4">
          <h2 className="text-lg font-medium">
            {nouveau ? t('adminWsTemplates.new') : edite.slug}
          </h2>

          {nouveau && (
            <div>
              <Label htmlFor="tpl-slug">{t('adminWsTemplates.slug')}</Label>
              <Input
                id="tpl-slug"
                value={edite.slug}
                onChange={(e) => setEdite({ ...edite, slug: e.target.value })}
                placeholder="python-ia"
              />
              {slugError && (
                <p role="alert" className="mt-1 text-sm text-destructive">
                  {slugError}
                </p>
              )}
            </div>
          )}

          <div>
            <Label htmlFor="tpl-label">{t('adminWsTemplates.label')}</Label>
            <Input
              id="tpl-label"
              value={edite.label}
              onChange={(e) => setEdite({ ...edite, label: e.target.value })}
            />
          </div>

          <div>
            <Label htmlFor="tpl-description">{t('adminWsTemplates.description')}</Label>
            <Input
              id="tpl-description"
              value={edite.description}
              onChange={(e) => setEdite({ ...edite, description: e.target.value })}
            />
          </div>

          {recipes.length > 0 && (
            <div>
              <Label>{t('workspaces.form.recipes')}</Label>
              <div className="mt-1">
                <OrderedRecipePicker
                  recipes={recipes}
                  selected={edite.spec.recipes}
                  onChange={(ids) => poserSpec('recipes', ids)}
                />
              </div>
            </div>
          )}

          {initializeRecipes.length > 0 && (
            <div>
              <Label>{t('workspaces.form.initRecipes')}</Label>
              <div className="mt-1 flex flex-wrap gap-1">
                {initializeRecipes.map((r) => {
                  const selected = edite.spec.init_recipes.includes(r.id)
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() =>
                        poserSpec(
                          'init_recipes',
                          selected
                            ? edite.spec.init_recipes.filter((x) => x !== r.id)
                            : [...edite.spec.init_recipes, r.id],
                        )
                      }
                      className={`rounded-sm px-2 py-0.5 text-xs border transition-colors ${
                        selected
                          ? 'bg-primary text-primary-foreground border-primary'
                          : 'bg-muted text-muted-foreground border-border hover:border-primary'
                      }`}
                    >
                      {r.id}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {agentTypes.length > 0 && (
            <div>
              <Label>{t('workspaces.form.agents')}</Label>
              <div className="mt-1 flex flex-wrap gap-1">
                {agentTypes.map((a) => {
                  const selected = edite.spec.agents.includes(a.id)
                  return (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() =>
                        poserSpec(
                          'agents',
                          selected
                            ? edite.spec.agents.filter((x) => x !== a.id)
                            : [...edite.spec.agents, a.id],
                        )
                      }
                      className={`rounded-sm px-2 py-0.5 text-xs border transition-colors ${
                        selected
                          ? 'bg-primary text-primary-foreground border-primary'
                          : 'bg-muted text-muted-foreground border-border hover:border-primary'
                      }`}
                    >
                      {a.id}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          <ProfileSelector
            profiles={profiles}
            value={profilValue}
            onChange={(v) => {
              if (!v) {
                poserSpec('profile', null)
                return
              }
              const [scope, slug] = v.split(':') as ['shared' | 'user', string]
              poserSpec('profile', { scope, slug })
            }}
          />

          <div>
            <Label htmlFor="tpl-memory">{t('adminWsTemplates.memoryLimit')}</Label>
            <Input
              id="tpl-memory"
              value={edite.spec.memory_limit}
              onChange={(e) => poserSpec('memory_limit', e.target.value.trim().toLowerCase())}
              placeholder="8g"
            />
          </div>

          <div>
            <Label htmlFor="tpl-branch">{t('adminWsTemplates.branch')}</Label>
            <Input
              id="tpl-branch"
              value={edite.spec.branch}
              onChange={(e) => poserSpec('branch', e.target.value)}
              placeholder="dev"
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="tpl-sshkey"
              checked={edite.spec.ssh_key}
              onChange={(e) => poserSpec('ssh_key', e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <Label htmlFor="tpl-sshkey" className="cursor-pointer font-normal">
              {t('adminWsTemplates.sshKey')}
            </Label>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="tpl-published"
              checked={edite.published}
              onChange={(e) => setEdite({ ...edite, published: e.target.checked })}
              className="h-4 w-4 rounded border-input"
            />
            <Label htmlFor="tpl-published" className="cursor-pointer font-normal">
              {t('adminWsTemplates.published')}
            </Label>
          </div>

          <div className="flex gap-2">
            <Button onClick={enregistrer} disabled={save.isPending}>
              {t('common.save')}
            </Button>
            <Button variant="outline" onClick={() => setEdite(null)}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
