import { useQuery } from '@tanstack/react-query'
import { getPlugin } from '../api/plugins'

export function usePluginDetail(namespace?: string, name?: string) {
  return useQuery({
    queryKey: ['plugins', 'detail', namespace, name],
    queryFn: () => getPlugin(namespace!, name!),
    enabled: Boolean(namespace && name),
  })
}
