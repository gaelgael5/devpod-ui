/**
 * Variables declarees par un type d'hyperviseur.
 *
 * Le type dit CE QUI EXISTE, le profil de host dira COMBIEN.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import HypervisorVariablesBlock from './HypervisorVariablesBlock'
import type { HypervisorVariable } from './useAdminHypervisorTypes'

function renderBloc(variables: HypervisorVariable[] = []) {
  const onChange = vi.fn()
  render(
    <I18nextProvider i18n={i18n}>
      <HypervisorVariablesBlock variables={variables} onChange={onChange} />
    </I18nextProvider>,
  )
  return onChange
}

describe('HypervisorVariablesBlock', () => {
  it('dérive le slug du libellé', async () => {
    // L'inventer deux fois n'apporte rien.
    const onChange = renderBloc([{ label: '', slug: '', type: 'string' }])
    await userEvent.type(screen.getByLabelText(/Workspace capacity/), 'Z')

    expect(onChange).toHaveBeenCalledWith([{ label: 'Z', slug: 'z', type: 'string' }])
  })

  it('ajoute la variable de capacité d’un clic, en entier', async () => {
    // Le portail LIT ce slug : une faute de frappe le rendrait invisible sans
    // rien signaler, d'ou le bouton dedie.
    const onChange = renderBloc()
    await userEvent.click(screen.getByRole('button', { name: /Add capacity/ }))

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ slug: 'capacity_workspaces', type: 'int' }),
    ])
  })

  it('ne propose plus la capacité une fois déclarée', () => {
    renderBloc([{ label: 'Capacité', slug: 'capacity_workspaces', type: 'int' }])

    expect(screen.queryByRole('button', { name: /Add capacity/ })).not.toBeInTheDocument()
  })

  it('signale la variable lue par le portail', () => {
    renderBloc([{ label: 'Capacité', slug: 'capacity_workspaces', type: 'int' }])

    expect(screen.getByText(/Read by the portal/)).toBeInTheDocument()
  })

  it('retire une variable', async () => {
    const onChange = renderBloc([{ label: 'Zone', slug: 'zone', type: 'string' }])
    await userEvent.click(screen.getByRole('button', { name: /Remove variable/ }))

    expect(onChange).toHaveBeenCalledWith([])
  })
})
