import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface RemoteJinjaTemplate {
  filename: string
  key: string
  culture: string
  description: string
  source_url: string
  source_base: string
}

interface ImportArgs {
  source_url: string
  key: string
  culture: string
  overwrite: boolean
}

export function useJinjaTemplateSources() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const sourcesQuery = useQuery<{ sources: string[] }>({
    queryKey: ['admin', 'jinja-template-sources'],
    queryFn: () => apiFetchJson<{ sources: string[] }>('/admin/jinja-template-sources'),
    staleTime: 5 * 60 * 1000,
  })

  const updateSources = useMutation({
    mutationFn: (sources: string[]) =>
      apiFetchJson<{ sources: string[] }>('/admin/jinja-template-sources', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'jinja-template-sources'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const previewQuery = useQuery<{ templates: RemoteJinjaTemplate[] }>({
    queryKey: ['admin', 'jinja-template-sources', 'preview'],
    queryFn: () =>
      apiFetchJson<{ templates: RemoteJinjaTemplate[] }>('/admin/jinja-template-sources/preview'),
    staleTime: 2 * 60 * 1000,
  })

  const importTemplate = useMutation({
    mutationFn: (args: ImportArgs) =>
      apiFetchJson<{ key: string; culture: string }>('/admin/jinja-template-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
      }),
    onSuccess: (data) => {
      toast.success(t('jinjaTemplates.gallery.imported', { key: data.key, culture: data.culture }))
      qc.invalidateQueries({ queryKey: ['jinja-templates'] })
      qc.invalidateQueries({ queryKey: ['admin', 'jinja-template-sources', 'preview'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  async function exportBundle(): Promise<void> {
    const res = await apiFetch('/admin/jinja-templates/export')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'jinja-templates.zip'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return { sourcesQuery, updateSources, previewQuery, importTemplate, exportBundle }
}
