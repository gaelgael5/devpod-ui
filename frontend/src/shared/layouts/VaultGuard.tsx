import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useVaultStatus } from '@/features/vault/api'

export default function VaultGuard({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { data, isLoading } = useVaultStatus()

  useEffect(() => {
    if (isLoading) return
    if (data?.status === 'setup_required') {
      if (pathname !== '/vault/setup') navigate('/vault/setup', { replace: true })
    } else if (data?.status === 'locked') {
      if (pathname !== '/vault/unlock' && pathname !== '/vault/recover')
        navigate('/vault/unlock', { replace: true })
    }
  }, [data, isLoading, pathname, navigate])

  return <>{children}</>
}
