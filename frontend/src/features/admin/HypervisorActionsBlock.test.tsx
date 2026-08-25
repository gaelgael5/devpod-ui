/**
 * Actions supplementaires d'un type d'hyperviseur.
 *
 * Ce qui compte : le slug affiche est celui qui sera ENREGISTRE (prefixe par
 * le type), et le slug suit le libelle tant qu'on n'y a pas touche.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import HypervisorActionsBlock from './HypervisorActionsBlock'
import { qualifierSlugAction } from '@/shared/slug'

describe('qualifierSlugAction', () => {
  it('prefixe par le type', () => {
    expect(qualifierSlugAction('proxmox', 'reboot')).toBe('proxmox-reboot')
  })

  it('ne redouble pas un prefixe deja present', () => {
    // Re-editer une action relit son slug DEJA qualifie : sans ca on
    // obtiendrait `proxmox-proxmox-reboot`.
    expect(qualifierSlugAction('proxmox', 'proxmox-reboot')).toBe('proxmox-reboot')
  })
})

describe('HypervisorActionsBlock', () => {
  it('annonce l’absence d’action', () => {
    renderWithProviders(
      <HypervisorActionsBlock typeName="proxmox" actions={[]} onChange={vi.fn()} />,
    )

    expect(screen.getByText(/aucune action|no action registered/i)).toBeInTheDocument()
  })

  it('montre le slug qualifie de chaque action enregistree', () => {
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        actions={[{ label: 'Reboot', slug: 'reboot', script: '' }]}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText(/proxmox-reboot/)).toBeInTheDocument()
  })

  it('ajoute une ligne vide', async () => {
    const onChange = vi.fn()
    renderWithProviders(
      <HypervisorActionsBlock typeName="proxmox" actions={[]} onChange={onChange} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /ajouter une action|add an action/i }))

    expect(onChange).toHaveBeenCalledWith([{ label: '', slug: '', script: '' }])
  })

  it('derive le slug du libelle tant qu’il n’a pas ete saisi', async () => {
    const onChange = vi.fn()
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        actions={[{ label: '', slug: '', script: '' }]}
        onChange={onChange}
      />,
    )

    await userEvent.type(screen.getByPlaceholderText(/redémarrer la vm|reboot the vm/i), 'R')

    expect(onChange).toHaveBeenCalledWith([{ label: 'R', slug: 'r', script: '' }])
  })

  it('ne reecrit pas un slug saisi a la main', async () => {
    const onChange = vi.fn()
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        actions={[{ label: 'Reboot', slug: 'rb', script: '', slugManuel: true }]}
        onChange={onChange}
      />,
    )

    await userEvent.type(screen.getByPlaceholderText(/redémarrer la vm|reboot the vm/i), 'X')

    expect(onChange).toHaveBeenCalledWith([
      { label: 'RebootX', slug: 'rb', script: '', slugManuel: true },
    ])
  })

  it('retire une action', async () => {
    const onChange = vi.fn()
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        actions={[{ label: 'Reboot', slug: 'reboot', script: '' }]}
        onChange={onChange}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /retirer l.action|remove action/i }))

    expect(onChange).toHaveBeenCalledWith([])
  })
})
