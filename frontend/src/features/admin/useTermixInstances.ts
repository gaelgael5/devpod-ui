import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

/** Une instance Termix enregistrée (registre admin, spec 18 T2). */
export interface TermixInstance {
  id: string
  name: string
  url: string
  apikey_secret: string
  oidc_client_id: string
  is_default: boolean
  created_at?: string
  updated_at?: string
}

/** Corps de création. `apikey_secret` = slug d'un secret système (apikey `tmx_`). */
export interface TermixInstanceBody {
  name: string
  url: string
  apikey_secret: string
  oidc_client_id: string
  is_default: boolean
}

const BASE = '/admin/termix-instances'
const QK = ['admin', 'termix-instances'] as const

export function useTermixInstances() {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: QK })

  const listQuery = useQuery<TermixInstance[]>({
    queryKey: QK,
    queryFn: () => apiFetchJson<TermixInstance[]>(BASE),
    staleTime: 60_000,
  })

  const create = useMutation({
    mutationFn: (body: TermixInstanceBody) =>
      apiFetchJson<TermixInstance>(BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
    onError: (e: Error) => toast.error(e.message),
  })

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<TermixInstanceBody> }) =>
      apiFetchJson<TermixInstance>(`${BASE}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
    onError: (e: Error) => toast.error(e.message),
  })

  const remove = useMutation({
    mutationFn: (id: string) => apiFetchVoid(`${BASE}/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
    onError: (e: Error) => toast.error(e.message),
  })

  return { listQuery, create, update, remove }
}
