import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetchJson } from '@/shared/api/client'

export interface RemoteComposeTemplate {
  id: string
  name: string
  description: string
  version: string
  tags: string[]
  image: string
  source_url: string
}

export function useComposeSources() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const sourcesQuery = useQuery<{ sources: string[] }>({
    queryKey: ['admin', 'compose-sources'],
    queryFn: () => apiFetchJson<{ sources: string[] }>('/admin/compose-sources'),
    staleTime: 5 * 60 * 1000,
  })

  const updateSources = useMutation({
    mutationFn: (sources: string[]) =>
      apiFetchJson<{ sources: string[] }>('/admin/compose-sources', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'compose-sources'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const previewQuery = useQuery<{ templates: RemoteComposeTemplate[] }>({
    queryKey: ['admin', 'compose-sources', 'preview'],
    queryFn: () =>
      apiFetchJson<{ templates: RemoteComposeTemplate[] }>('/admin/compose-sources/preview'),
    staleTime: 2 * 60 * 1000,
    enabled: false,
  })

  const importTemplate = useMutation({
    mutationFn: (source_url: string) =>
      apiFetchJson<{ id: string }>('/admin/compose-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url }),
      }),
    onSuccess: (data) => {
      toast.success(t('compose.catalog.imported', { id: data.id }))
      qc.invalidateQueries({ queryKey: ['compose', 'templates'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { sourcesQuery, updateSources, previewQuery, importTemplate }
}
