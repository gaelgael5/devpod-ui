import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useApplyHostRecipe, useHostRecipes, useOperation } from './useHostRecipes'

interface Props {
  hostName: string | null
  onClose: () => void
}

/**
 * Recettes applicables à une machine, et celles qu'elle porte déjà.
 *
 * La liste ne montre que les recettes déclarant la famille de cette machine :
 * une recette de host s'exécute avec les droits d'administration, on ne
 * propose donc jamais d'appliquer ce qui n'a pas été prévu pour elle.
 */
export default function HostRecipesDialog({ hostName, onClose }: Props) {
  const { t } = useTranslation()
  const { data, isLoading } = useHostRecipes(hostName)
  const apply = useApplyHostRecipe(hostName)
  const [operationId, setOperationId] = useState<string | null>(null)
  const { data: operation } = useOperation(operationId)

  const lancer = (recipeId: string) =>
    apply.mutate({ recipeId }, { onSuccess: (res) => setOperationId(res.operation_id) })

  return (
    <Dialog open={!!hostName} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('admin.hostRecipes.title', { host: hostName ?? '' })}</DialogTitle>
          <DialogDescription>{t('admin.hostRecipes.description')}</DialogDescription>
        </DialogHeader>

        {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

        {data && data.available.length === 0 && (
          <p className="text-sm text-muted-foreground" data-testid="aucune-recette">
            {t('admin.hostRecipes.none')}
          </p>
        )}

        <div className="flex flex-col gap-2">
          {data?.available.map((recette) => {
            const posee = data.installed[recette.id]
            const aJour = posee?.version === recette.version
            return (
              <div
                key={recette.id}
                className="flex items-start justify-between gap-3 rounded border px-3 py-2"
                data-testid={`recette-${recette.id}`}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{recette.id}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {recette.version}
                    </span>
                    {/* La version posée compte autant que la présence : une
                        recette installée dans une version ancienne n'est pas
                        « à jour », et c'est ce qu'on veut voir d'un coup d'œil. */}
                    {posee && (
                      <span
                        className={`text-xs ${aJour ? 'text-green-600' : 'text-amber-600'}`}
                        data-testid={`etat-${recette.id}`}
                      >
                        {aJour
                          ? t('admin.hostRecipes.installed')
                          : t('admin.hostRecipes.outdated', { version: posee.version })}
                      </span>
                    )}
                  </div>
                  {recette.description && (
                    <p className="mt-0.5 text-xs text-muted-foreground">{recette.description}</p>
                  )}
                </div>
                <Button
                  size="sm"
                  variant={aJour ? 'outline' : 'default'}
                  className="shrink-0"
                  disabled={apply.isPending}
                  onClick={() => lancer(recette.id)}
                >
                  {aJour ? t('admin.hostRecipes.reapply') : t('admin.hostRecipes.apply')}
                </Button>
              </div>
            )
          })}
        </div>

        {apply.isError && (
          <p className="text-sm text-destructive" data-testid="erreur-application">
            {(apply.error as Error).message}
          </p>
        )}

        {/* Une recette de host peut peser 20 Go : sans ce retour, l'utilisateur
            ne saurait jamais si elle a abouti. */}
        {operationId && (
          <div className="flex items-center gap-2 rounded border px-3 py-2 text-sm" data-testid="suivi">
            {operation?.state === 'done' ? (
              <>
                <CheckCircle2 className="h-4 w-4 text-green-600" />
                <span>{t('admin.hostRecipes.opDone')}</span>
              </>
            ) : operation?.state === 'failed' ? (
              <>
                <XCircle className="h-4 w-4 text-destructive" />
                <span className="min-w-0 break-words">
                  {operation.error || t('admin.hostRecipes.opFailed')}
                </span>
              </>
            ) : (
              <>
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                <span>{t('admin.hostRecipes.opRunning')}</span>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
