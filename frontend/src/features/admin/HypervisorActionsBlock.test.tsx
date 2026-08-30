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
      <HypervisorActionsBlock typeName="proxmox" cible="machine" actions={[]} onChange={vi.fn()} />,
    )

    expect(screen.getByText(/aucune action|no action registered/i)).toBeInTheDocument()
  })

  it('montre le slug qualifie de chaque action enregistree', () => {
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        cible="machine"
        actions={[{ label: 'Reboot', slug: 'reboot', script: '' }]}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText(/proxmox-reboot/)).toBeInTheDocument()
  })

  it('ajoute une ligne vide', async () => {
    const onChange = vi.fn()
    renderWithProviders(
      <HypervisorActionsBlock typeName="proxmox" cible="machine" actions={[]} onChange={onChange} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /ajouter une action|add an action/i }))

    expect(onChange).toHaveBeenCalledWith([{ label: '', slug: '', script: '', cible: 'machine' }])
  })

  it('derive le slug du libelle tant qu’il n’a pas ete saisi', async () => {
    const onChange = vi.fn()
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        cible="machine"
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
        cible="machine"
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
        cible="machine"
        actions={[{ label: 'Reboot', slug: 'reboot', script: '' }]}
        onChange={onChange}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /retirer l.action|remove action/i }))

    expect(onChange).toHaveBeenCalledWith([])
  })
})

describe('HypervisorActionsBlock — cible', () => {
  const ACTIONS = [
    { label: 'Increase memory', slug: 'mem', script: '', cible: 'machine' as const },
    { label: 'Inventaire', slug: 'inv', script: '', cible: 'hyperviseur' as const },
  ]

  it('ne montre que les actions de sa cible', () => {
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        cible="hyperviseur"
        actions={ACTIONS}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByDisplayValue('Inventaire')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('Increase memory')).not.toBeInTheDocument()
  })

  it('une action sans cible est une action machine (types anterieurs au champ)', () => {
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        cible="machine"
        actions={[{ label: 'Historique', slug: 'histo', script: '' }]}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByDisplayValue('Historique')).toBeInTheDocument()
  })

  it('edite la bonne action alors que le bloc n’en montre qu’une partie', async () => {
    const onChange = vi.fn()
    renderWithProviders(
      <HypervisorActionsBlock
        typeName="proxmox"
        cible="hyperviseur"
        actions={ACTIONS}
        onChange={onChange}
      />,
    )

    // Le bloc affiche l'action d'indice 1 : editer la ligne visible ne doit pas
    // ecraser l'action machine restee dans l'autre onglet.
    await userEvent.click(screen.getByRole('button', { name: /retirer l.action|remove action/i }))

    expect(onChange).toHaveBeenCalledWith([ACTIONS[0]])
  })
})
