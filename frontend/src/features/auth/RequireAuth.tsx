import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { useSession } from './useSession'
import { useUserStore } from '@/store/user'

interface Props {
  children: ReactNode
}

export default function RequireAuth({ children }: Props) {
  const { data, isLoading, isError } = useSession()
  const setUser = useUserStore((s) => s.setUser)

  useEffect(() => {
    if (data) setUser(data)
  }, [data, setUser])

  if (isLoading) return null
  if (isError) return null // apiFetch redirige vers /auth/login sur 401

  if (!data) return null

  return <>{children}</>
}
