import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink } from 'lucide-react'
import { skillShUrl } from './skillsSh'

interface Props {
  skillId: string
  className?: string
  children?: ReactNode
}

/** Lien externe vers la page skills.sh d'une skill (icône par défaut). */
export default function SkillShLink({ skillId, className, children }: Props) {
  const { t } = useTranslation()
  return (
    <a
      href={skillShUrl(skillId)}
      target="_blank"
      rel="noopener noreferrer"
      title={t('skills.viewOnSkillsSh')}
      aria-label={t('skills.viewOnSkillsSh')}
      onClick={(e) => e.stopPropagation()}
      className={
        className ??
        'inline-flex shrink-0 items-center text-muted-foreground transition-colors hover:text-primary'
      }
    >
      {children ?? <ExternalLink className="h-3.5 w-3.5" />}
    </a>
  )
}
