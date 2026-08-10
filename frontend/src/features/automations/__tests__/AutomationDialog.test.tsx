import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import { AutomationDialog } from '../AutomationDialog'

function mockRefs() {
  server.use(
    http.get('/admin/automations/event-types', () =>
      HttpResponse.json(['user.created', 'user.deleted', 'test_server.updated']),
    ),
    http.get('/admin/automations/contracts', () =>
      HttpResponse.json([
        {
          id: 'c1',
          label: 'Termix API',
          category: '',
          source_url: null,
          version: '1',
          created_at: '2026-08-08T00:00:00Z',
          updated_at: '2026-08-08T00:00:00Z',
        },
      ]),
    ),
    http.get('/admin/automations/secrets', () => HttpResponse.json([])),
  )
}

describe('AutomationDialog', () => {
  it('shows the three tabs and derives the slug from the label', async () => {
    mockRefs()
    const user = userEvent.setup()
    const { findByText, getByLabelText } = renderWithProviders(
      <AutomationDialog automation={null} open onOpenChange={() => {}} />,
    )

    expect(await findByText('General')).toBeInTheDocument()
    expect(await findByText('Filter')).toBeInTheDocument()
    expect(await findByText('Call')).toBeInTheDocument()

    const labelInput = getByLabelText('Label')
    await user.type(labelInput, 'Sync Termix Hosts')
    const slugInput = getByLabelText('Slug') as HTMLInputElement
    expect(slugInput.value).toBe('sync-termix-hosts')
  })

  it('lets the user override the slug and stops deriving', async () => {
    mockRefs()
    const user = userEvent.setup()
    const { getByLabelText } = renderWithProviders(
      <AutomationDialog automation={null} open onOpenChange={() => {}} />,
    )
    const slugInput = getByLabelText('Slug') as HTMLInputElement
    await user.type(slugInput, 'custom')
    const labelInput = getByLabelText('Label')
    await user.type(labelInput, 'Autre')
    expect(slugInput.value).toBe('custom') // plus dérivé après édition manuelle
  })

  it('reveals the expected value field only for equals/not_equals operators', async () => {
    mockRefs()
    const user = userEvent.setup()
    const { findByText, getByText, getByLabelText, queryByLabelText } = renderWithProviders(
      <AutomationDialog automation={null} open onOpenChange={() => {}} />,
    )
    await user.click(await findByText('Filter'))
    // exists (défaut vide) → pas de champ « Expected value »
    expect(queryByLabelText('Expected value')).toBeNull()
    await user.selectOptions(getByLabelText('Operator'), 'equals')
    expect(getByText('Expected value')).toBeInTheDocument()
    await user.selectOptions(getByLabelText('Operator'), 'exists')
    expect(queryByLabelText('Expected value')).toBeNull()
  })
})
