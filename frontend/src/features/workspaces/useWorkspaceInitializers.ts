import { useQuery, useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface WorkspaceInitializer {
  id: string
  description: string
  version: string
}

export interface RunInitializerResult {
  applied: boolean
  already_applied: boolean
  log: string
}

export function useWorkspaceInitializers(wsName: string | undefined) {
  return useQuery({
    queryKey: ['workspace-initializers', wsName],
    queryFn: () =>
      apiFetchJson<WorkspaceInitializer[]>(`/me/workspaces/${wsName}/initializers`),
    enabled: !!wsName,
    staleTime: 60_000,
  })
}

interface RunInput {
  wsName: string
  id: string
  force?: boolean
}

export function useRunInitializer() {
  return useMutation({
    mutationFn: ({ wsName, id, force }: RunInput) =>
      apiFetchJson<RunInitializerResult>(
        `/me/workspaces/${wsName}/initializers/${id}/run${force ? '?force=true' : ''}`,
        { method: 'POST' },
      ),
  })
}

/** Lance un initializer avec le retour toast standard — partagé entre les menus qui l'exposent. */
export function useRunInitializerWithToast(wsName: string) {
  const { t } = useTranslation()
  const run = useRunInitializer()

  function handleRun(id: string, force: boolean) {
    toast.promise(run.mutateAsync({ wsName, id, force }), {
      loading: t('workspaces.initializers.running'),
      success: (res) =>
        res.already_applied
          ? t('workspaces.initializers.alreadyApplied')
          : t('workspaces.initializers.applied'),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.initializers.failed')),
    })
  }

  return { handleRun, isPending: run.isPending }
}
