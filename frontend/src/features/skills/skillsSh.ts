const SKILLS_SH_BASE = 'https://skills.sh'

/**
 * Page publique d'une skill sur skills.sh.
 * L'identifiant est `source/skillId` (ex. `github/awesome-copilot/git-commit`)
 * et la page vit à `https://skills.sh/<source>/<skillId>`. Chaque segment est
 * encodé, les `/` restant des séparateurs de chemin.
 */
export function skillShUrl(skillId: string): string {
  const path = skillId.split('/').map(encodeURIComponent).join('/')
  return `${SKILLS_SH_BASE}/${path}`
}
