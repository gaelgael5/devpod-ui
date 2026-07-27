import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import TestHostShareDialog from './TestHostShareDialog'

const WORKSPACES = [
  { name: 'owner-ws', source: '' },
  { name: 'ws-run', source: '' },
  { name: 'ws-stopped', source: '' },
]
const STATUS: Record<string, string> = {
  'owner-ws': 'running',
  'ws-run': 'running',
  'ws-stopped': 'stopped',
}

function seed(currentShared: string[], onPut?: (body: unknown) => void) {
  server.use(
    http.get('/me/workspaces', () => HttpResponse.json(WORKSPACES)),
    http.get('/me/workspaces/:name/status', ({ params }) =>
      HttpResponse.json({ status: STATUS[String(params.name)] ?? 'unknown' }),
    ),
    http.get('/me/workspaces/:ws/test-hosts/:host/shares', () =>
      HttpResponse.json({ shared: currentShared }),
    ),
    http.put('/me/workspaces/:ws/test-hosts/:host/shares', async ({ request }) => {
      const body = await request.json()
      onPut?.(body)
      return HttpResponse.json({ shared: (body as { workspaces: string[] }).workspaces })
    }),
  )
}

describe('TestHostShareDialog', () => {
  it('liste les workspaces running (hors propriétaire) et pré-coche les partages courants', async () => {
    seed(['ws-stopped'])
    renderWithProviders(
      <TestHostShareDialog wsName="owner-ws" hostName="h1" hostAlias="test1" onClose={vi.fn()} />,
    )
    const dialog = await screen.findByRole('dialog')
    // Le propriétaire n'apparaît jamais.
    expect(within(dialog).queryByText('owner-ws')).not.toBeInTheDocument()
    // ws-run (running, non partagé) présent et décoché.
    const run = await within(dialog).findByText('ws-run')
    expect(run).toBeInTheDocument()
    // ws-stopped déjà partagé → affiché (pour pouvoir décocher) et coché.
    const stoppedRow = within(dialog).getByText('ws-stopped').closest('label')!
    expect(within(stoppedRow).getByRole('checkbox')).toBeChecked()
  })

  it('coche un workspace running et enregistre l’ensemble (PUT)', async () => {
    let putBody: unknown = null
    seed([], (b) => { putBody = b })
    const user = userEvent.setup()
    renderWithProviders(
      <TestHostShareDialog wsName="owner-ws" hostName="h1" hostAlias="test1" onClose={vi.fn()} />,
    )
    const dialog = await screen.findByRole('dialog')
    await user.click(await within(dialog).findByText('ws-run'))
    await user.click(within(dialog).getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() =>
      expect((putBody as { workspaces: string[] })?.workspaces).toEqual(['ws-run']),
    )
  })

  it('décocher un partage existant le retire de l’ensemble envoyé', async () => {
    let putBody: unknown = null
    seed(['ws-stopped'], (b) => { putBody = b })
    const user = userEvent.setup()
    renderWithProviders(
      <TestHostShareDialog wsName="owner-ws" hostName="h1" hostAlias="test1" onClose={vi.fn()} />,
    )
    const dialog = await screen.findByRole('dialog')
    const stoppedRow = (await within(dialog).findByText('ws-stopped')).closest('label')!
    await user.click(within(stoppedRow).getByRole('checkbox'))
    await user.click(within(dialog).getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() =>
      expect((putBody as { workspaces: string[] })?.workspaces).toEqual([]),
    )
  })
})
