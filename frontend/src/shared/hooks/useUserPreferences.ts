import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

/** Valeur de préférence : le backend range chaque type dans sa colonne dédiée. */
export type PrefValue = number | string | boolean

/** Corps typé discriminé attendu par `PUT /me/preferences/{key}` (exactement un champ). */
function typedBody(value: PrefValue): Record<string, PrefValue> {
  if (typeof value === 'boolean') return { bool: value }
  if (typeof value === 'number') return { int: value }
  return { string: value }
}

const PREFERENCES_KEY = ['preferences'] as const

/** Map complète des préférences de l'utilisateur, chargée à l'ouverture d'une page. */
export function useUserPreferences() {
  return useQuery<Record<string, PrefValue>>({
    queryKey: PREFERENCES_KEY,
    queryFn: () => apiFetchJson<Record<string, PrefValue>>('/me/preferences'),
    staleTime: 60_000,
  })
}

/** Écrit une préférence (PUT par clé) avec mise à jour optimiste + rollback sur erreur. */
export function useSetPreference() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: PrefValue }) =>
      apiFetchVoid(`/me/preferences/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(typedBody(value)),
      }),
    onMutate: async ({ key, value }) => {
      await qc.cancelQueries({ queryKey: PREFERENCES_KEY })
      const prev = qc.getQueryData<Record<string, PrefValue>>(PREFERENCES_KEY)
      qc.setQueryData<Record<string, PrefValue>>(PREFERENCES_KEY, (old) => ({
        ...(old ?? {}),
        [key]: value,
      }))
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(PREFERENCES_KEY, ctx.prev)
    },
  })
}
