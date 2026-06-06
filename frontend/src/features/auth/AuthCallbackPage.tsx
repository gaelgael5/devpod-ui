import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSession } from './useSession'
import { useUserStore } from '@/store/user'
import { useTranslation } from 'react-i18next'

export default function AuthCallbackPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { data, isError } = useSession()
  const setUser = useUserStore((s) => s.setUser)

  useEffect(() => {
    if (data) {
      setUser(data)
      navigate('/workspaces', { replace: true })
    }
  }, [data, setUser, navigate])

  useEffect(() => {
    if (isError) navigate('/auth/login', { replace: true })
  }, [isError, navigate])

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground">{t('auth.loggingIn')}</p>
    </div>
  )
}
