import { useQuery } from '@tanstack/react-query'
import { getPluginReadme } from '../api/plugins'

export function usePluginReadme(namespace?: string, name?: string) {
  return useQuery({
    queryKey: ['plugins', 'readme', namespace, name],
    queryFn: () => getPluginReadme(namespace!, name!),
    enabled: Boolean(namespace && name),
    staleTime: 5 * 60 * 1000,
  })
}
