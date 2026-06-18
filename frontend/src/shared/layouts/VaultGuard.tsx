import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useVaultStatus } from '@/features/vault/api'

const VAULT_PATHS = ['/vault/setup', '/vault/unlock', '/vault/recover']

export default function VaultGuard({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { data, isLoading } = useVaultStatus()

  useEffect(() => {
    if (isLoading || VAULT_PATHS.includes(pathname)) return
    if (data?.status === 'setup_required') navigate('/vault/setup', { replace: true })
    else if (data?.status === 'locked') navigate('/vault/unlock', { replace: true })
  }, [data, isLoading, pathname, navigate])

  return <>{children}</>
}
