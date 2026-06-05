import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

export default function LoginPage() {
  const { t } = useTranslation()

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-6">
        <h1 className="text-2xl font-semibold text-foreground">DevPod Portal</h1>
        <Button asChild>
          <a href="/auth/login">{t('auth.login')}</a>
        </Button>
      </div>
    </div>
  )
}
