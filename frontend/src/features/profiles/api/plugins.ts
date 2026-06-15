import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type { PluginDetail, PluginSearchResult, PluginSort } from './types'

export const PLUGINS_PAGE_SIZE = 24

export function searchPlugins(params: {
  q: string
  sort: PluginSort
  offset: number
  size?: number
}): Promise<PluginSearchResult> {
  const qs = new URLSearchParams({
    sort: params.sort,
    offset: String(params.offset),
    size: String(params.size ?? PLUGINS_PAGE_SIZE),
  })
  if (params.q.trim()) qs.set('q', params.q.trim())
  return apiFetchJson<PluginSearchResult>(`/plugins/search?${qs}`)
}

export function getPlugin(namespace: string, name: string): Promise<PluginDetail> {
  return apiFetchJson<PluginDetail>(
    `/plugins/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
  )
}

export async function getPluginReadme(namespace: string, name: string): Promise<string> {
  const res = await apiFetch(
    `/plugins/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/readme`,
  )
  if (!res.ok) {
    // README is optional enrichment — server returns empty string when unavailable,
    // so non-ok means a real error (502 upstream down, etc.)
    throw new Error(`readme fetch failed: ${res.status}`)
  }
  return res.text()
}
