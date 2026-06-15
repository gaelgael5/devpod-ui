export type PluginSort = 'relevance' | 'popular' | 'recent' | 'rating'

export interface PluginSummary {
  id: string
  namespace: string
  name: string
  display_name: string
  description: string
  version: string
  downloads: number
  rating: number | null
  icon_url: string | null
}

export interface PluginSearchResult {
  total: number
  offset: number
  items: PluginSummary[]
}

export interface PluginDetail extends PluginSummary {
  categories: string[]
  tags: string[]
  license: string | null
  readme_url: string | null
}
