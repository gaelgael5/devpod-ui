import { useInfiniteQuery } from '@tanstack/react-query'
import { PLUGINS_PAGE_SIZE, searchPlugins } from '../api/plugins'
import type { PluginSort } from '../api/types'

export function usePluginSearch(query: string, sort: PluginSort) {
  return useInfiniteQuery({
    queryKey: ['plugins', 'search', query, sort],
    queryFn: ({ pageParam }) =>
      searchPlugins({ q: query, sort, offset: pageParam as number, size: PLUGINS_PAGE_SIZE }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
}
