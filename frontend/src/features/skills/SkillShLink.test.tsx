import { render, screen } from '@testing-library/react'
import SkillShLink from './SkillShLink'
import { skillShUrl } from './skillsSh'

describe('skillShUrl', () => {
  it('compose la page publique skills.sh depuis source/skillId', () => {
    expect(skillShUrl('github/awesome-copilot/git-commit')).toBe(
      'https://skills.sh/github/awesome-copilot/git-commit',
    )
  })

  it('encode chaque segment sans encoder les séparateurs /', () => {
    expect(skillShUrl('vercel-labs/skills/find skills')).toBe(
      'https://skills.sh/vercel-labs/skills/find%20skills',
    )
  })
})

describe('SkillShLink', () => {
  it("pointe vers skills.sh et s'ouvre en nouvel onglet de façon sûre", () => {
    render(<SkillShLink skillId="github/awesome-copilot/git-commit" />)
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', 'https://skills.sh/github/awesome-copilot/git-commit')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })
})
