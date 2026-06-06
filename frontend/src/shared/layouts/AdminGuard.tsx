import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useUserStore } from '@/store/user'

interface Props {
  children: ReactNode
}

export default function AdminGuard({ children }: Props) {
  const { t } = useTranslation()
  const isAdmin = useUserStore((s) => s.isAdmin())

  if (!isAdmin) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-muted-foreground">{t('errors.forbidden')}</p>
      </div>
    )
  }

  return <>{children}</>
}
