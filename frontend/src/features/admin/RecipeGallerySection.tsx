import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { RemoteRecipe } from './useRecipeSources'

/** Vignettes par page. La galerie d'une source bien fournie depasse la centaine
 *  d'entrees : tout rendre repoussait les recettes locales hors de l'ecran. */
const PAR_PAGE = 12

type Filtre = 'all' | 'install' | 'start' | 'initialize'

interface Props {
  recipes: RemoteRecipe[]
  isLoading: boolean
  onRefresh: () => void
  onImport: (sourceUrl: string) => void
  importPendingUrl: string | null
}

/**
 * Galerie distante : repliable et paginee.
 *
 * Repliable parce qu'elle n'a d'interet qu'au moment d'installer quelque chose —
 * le reste du temps elle enterre le catalogue local sous une liste qu'on vient
 * de synchroniser. Paginee pour la meme raison, a l'interieur du bloc.
 */
export default function RecipeGallerySection({
  recipes,
  isLoading,
  onRefresh,
  onImport,
  importPendingUrl,
}: Props) {
  const { t } = useTranslation()
  const [ouvert, setOuvert] = useState(false)
  const [filtre, setFiltre] = useState('')
  const [typeFiltre, setTypeFiltre] = useState<Filtre>('all')
  const [page, setPage] = useState(1)

  const filtrees = useMemo(() => {
    const q = filtre.trim().toLowerCase()
    return recipes.filter((r) => {
      if (typeFiltre !== 'all' && r.type !== typeFiltre) return false
      if (!q) return true
      return (
        r.id.toLowerCase().includes(q) ||
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q)
      )
    })
  }, [recipes, filtre, typeFiltre])

  const pages = Math.max(1, Math.ceil(filtrees.length / PAR_PAGE))
  // Filtrer reduit le nombre de pages : rester sur la page 7 d'un resultat qui
  // n'en compte plus que 2 afficherait une grille vide sans rien expliquer. Le
  // retour page 1 se fait a la SAISIE et non dans un effet — c'est une
  // consequence de l'action, pas du rendu.
  const pageSure = Math.min(page, pages)
  const visibles = filtrees.slice((pageSure - 1) * PAR_PAGE, pageSure * PAR_PAGE)

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setOuvert((o) => !o)}
          aria-expanded={ouvert}
          className="flex items-center gap-2 text-lg font-semibold transition-colors hover:text-muted-foreground"
        >
          <ChevronDown className={`h-4 w-4 transition-transform ${ouvert ? '' : '-rotate-90'}`} />
          {t('admin.gallery')}
          {recipes.length > 0 && (
            <span className="text-sm font-normal text-muted-foreground">
              ({recipes.length})
            </span>
          )}
        </button>
        <Button size="sm" variant="outline" onClick={onRefresh} disabled={isLoading}>
          <RefreshCw className={`mr-1 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
          {t('admin.refreshGallery')}
        </Button>
      </div>

      {ouvert && (
        <>
          {recipes.length > 0 && (
            <div className="mb-4 flex flex-col gap-2">
              <div className="flex gap-1">
                {(['all', 'install', 'start', 'initialize'] as const).map((v) => (
                  <Button
                    key={v}
                    size="sm"
                    variant={typeFiltre === v ? 'default' : 'outline'}
                    onClick={() => { setTypeFiltre(v); setPage(1) }}
                  >
                    {t(`admin.galleryType.${v}`)}
                  </Button>
                ))}
              </div>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder={t('admin.filterGallery')}
                  value={filtre}
                  onChange={(e) => { setFiltre(e.target.value); setPage(1) }}
                  className="pl-8 text-sm"
                />
              </div>
            </div>
          )}

          {isLoading && <p className="text-sm text-muted-foreground">…</p>}
          {!isLoading && recipes.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('admin.recipesEmpty')}</p>
          )}
          {!isLoading && recipes.length > 0 && filtrees.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('admin.galleryNoMatch')}</p>
          )}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {visibles.map((r) => (
              <div key={r.source_url} className="rounded-lg border bg-card p-4">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <div>
                    <div className="font-medium">{r.name}</div>
                    <div className="font-mono text-xs text-muted-foreground">{r.id}</div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => onImport(r.source_url)}
                    disabled={importPendingUrl !== null}
                  >
                    {importPendingUrl === r.source_url
                      ? t('admin.importing')
                      : t('admin.importRecipe')}
                  </Button>
                </div>
                <div className="text-sm text-muted-foreground">{r.description}</div>
                <div className="mt-2 text-xs text-muted-foreground">v{r.version}</div>
              </div>
            ))}
          </div>

          {filtrees.length > PAR_PAGE && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {t('admin.galleryRange', {
                  from: (pageSure - 1) * PAR_PAGE + 1,
                  to: Math.min(pageSure * PAR_PAGE, filtrees.length),
                  total: filtrees.length,
                })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPage(pageSure - 1)}
                  disabled={pageSure <= 1}
                >
                  {t('admin.galleryPrev')}
                </Button>
                <span className="text-xs text-muted-foreground">{pageSure} / {pages}</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPage(pageSure + 1)}
                  disabled={pageSure >= pages}
                >
                  {t('admin.galleryNext')}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}
