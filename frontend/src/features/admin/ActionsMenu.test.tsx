/**
 * Menu Actions d'une ligne.
 *
 * Ce qui compte ici : rien ne s'exécute d'un seul clic, et une ligne sans
 * action déclarée n'affiche pas de bouton mort.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import i18n from '@/i18n'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import ActionsMenu from './ActionsMenu'

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

const ACTION = { slug: 'proxmox4vm-increase-memory-1g', label: 'Increase memory +1G', cible: 'machine' as const }

const SPEC = { args: [], commands: ['qm set {VMID} --memory 2048'] }

describe('ActionsMenu', () => {
  it('n’affiche rien quand la ligne ne déclare aucune action', () => {
    renderWithProviders(<ActionsMenu base="/admin/hosts/rag" cibleLabel="rag" actions={[]} />)

    expect(screen.queryByRole('button', { name: i18n.t('admin.hypervisorActions.menu') })).toBeNull()
  })

  it('demande confirmation avant d’exécuter, en nommant l’action et sa cible', async () => {
    let execute = false
    server.use(
      http.get('/admin/hosts/host-105-1/actions/:slug/script', () => HttpResponse.json(SPEC)),
      http.post('/admin/hosts/host-105-1/actions/:slug/execute', () => {
        execute = true
        return HttpResponse.text('ok\n')
      }),
    )
    renderWithProviders(
      <ActionsMenu base="/admin/hosts/host-105-1" cibleLabel="host-105-1" actions={[ACTION]} />,
    )

    await userEvent.click(screen.getByRole('button', { name: i18n.t('admin.hypervisorActions.menu') }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Increase memory +1G' }))

    // La confirmation nomme l'action ET la cible : un tableau dense ne dit pas
    // sur quelle ligne on vient de cliquer.
    const dialogue = await screen.findByRole('dialog')
    expect(dialogue.textContent).toContain('Increase memory +1G')
    expect(dialogue.textContent).toContain('host-105-1')
    // Ouvrir le menu et choisir n'exécute rien : il reste un bouton à presser.
    expect(execute).toBe(false)

    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.hypervisorActions.run') }))
    expect(await screen.findByText(/ok/)).toBeInTheDocument()
    expect(execute).toBe(true)
  })
})
