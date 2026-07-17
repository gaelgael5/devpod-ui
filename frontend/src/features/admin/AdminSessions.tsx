import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAdminSessions, useSaveSessions, type SessionDurations } from './useAdminSessions'

const toMinutes = (seconds: number) => Math.round(seconds / 60)
const toSeconds = (minutes: number) => Math.round(minutes * 60)

/** Saisie en MINUTES (plus lisible), convertie en secondes pour l'API. */
function SessionsForm({ initial }: { initial: SessionDurations }) {
  const { t } = useTranslation()
  const save = useSaveSessions()
  const [idleMin, setIdleMin] = useState(String(toMinutes(initial.session_max_age)))
  const [absoluteMin, setAbsoluteMin] = useState(String(toMinutes(initial.session_absolute_max_age)))

  function handleSave() {
    const idle = toSeconds(Number(idleMin))
    const absolute = toSeconds(Number(absoluteMin))
    if (!Number.isFinite(idle) || !Number.isFinite(absolute) || idle < 60 || absolute < 60) {
      toast.error(t('admin.sessions.invalid'))
      return
    }
    if (absolute < idle) {
      toast.error(t('admin.sessions.absoluteBelowIdle'))
      return
    }
    save.mutate(
      { session_max_age: idle, session_absolute_max_age: absolute },
      { onSuccess: () => toast.success(t('admin.sessions.saved')) },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sess-idle">{t('admin.sessions.idleMaxAge')}</Label>
        <Input
          id="sess-idle"
          type="number"
          min={1}
          value={idleMin}
          onChange={(e) => setIdleMin(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t('admin.sessions.idleMaxAgeHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sess-absolute">{t('admin.sessions.absoluteMaxAge')}</Label>
        <Input
          id="sess-absolute"
          type="number"
          min={1}
          value={absoluteMin}
          onChange={(e) => setAbsoluteMin(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t('admin.sessions.absoluteMaxAgeHint')}</p>
      </div>

      <div>
        <Button onClick={handleSave} disabled={save.isPending}>
          {save.isPending ? '…' : t('admin.sessions.save')}
        </Button>
      </div>
    </div>
  )
}

export default function AdminSessions() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useAdminSessions()

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-2 text-2xl font-semibold">{t('admin.sessions.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.sessions.intro')}</p>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && <SessionsForm initial={data} />}
    </div>
  )
}
