import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetchJson } from '@/shared/api/client'

export interface RemoteProfile {
  filename: string
  name: string
  description: string
  extension_count: number
  source_url: string
  source_base: string
}

export function useProfileSources() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const sourcesQuery = useQuery<{ sources: string[] }>({
    queryKey: ['admin', 'profile-sources'],
    queryFn: () => apiFetchJson<{ sources: string[] }>('/admin/profile-sources'),
    staleTime: 5 * 60 * 1000,
  })

  const updateSources = useMutation({
    mutationFn: (sources: string[]) =>
      apiFetchJson<{ sources: string[] }>('/admin/profile-sources', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'profile-sources'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const previewQuery = useQuery<{ profiles: RemoteProfile[] }>({
    queryKey: ['admin', 'profile-sources', 'preview'],
    queryFn: () =>
      apiFetchJson<{ profiles: RemoteProfile[] }>('/admin/profile-sources/preview'),
    staleTime: 2 * 60 * 1000,
  })

  const importProfile = useMutation({
    mutationFn: (source_url: string) =>
      apiFetchJson<{ slug: string; name: string }>('/admin/profile-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url }),
      }),
    onSuccess: (data) => {
      toast.success(t('admin.profileSources.imported', { name: data.name }))
      qc.invalidateQueries({ queryKey: ['profiles'] })
      qc.invalidateQueries({ queryKey: ['admin', 'profile-sources', 'preview'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { sourcesQuery, updateSources, previewQuery, importProfile }
}
