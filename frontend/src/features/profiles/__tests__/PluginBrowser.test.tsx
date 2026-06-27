import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { PluginBrowser } from '../components/PluginBrowser'

const MOCK_PLUGIN = {
  id: 'ms-python.python',
  namespace: 'ms-python',
  name: 'python',
  display_name: 'Python',
  description: 'Python language support',
  version: '2024.0.1',
  downloads: 100000,
  rating: 4.5,
  icon_url: null,
}

function renderBrowser(
  selectedIds: Set<string> = new Set(),
  onToggle: (id: string) => void = () => {},
) {
  return renderWithProviders(
    <PluginBrowser selectedIds={selectedIds} onToggle={onToggle} />,
  )
}

describe('PluginBrowser', () => {
  it('affiche les plugins au rendu initial', async () => {
    renderBrowser()
    await waitFor(() => expect(screen.getByText('Python')).toBeInTheDocument())
    expect(screen.getByText('Python language support')).toBeInTheDocument()
  })

  it("clic sur Ajouter → appelle onToggle avec l'id du plugin", async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()

    renderBrowser(new Set(), onToggle)
    await waitFor(() => screen.getByText('Python'))

    const addBtn = screen.getByRole('button', { name: /^(add|ajouter)$/i })
    await user.click(addBtn)
    expect(onToggle).toHaveBeenCalledWith('ms-python.python')
  })

  it('carte sélectionnée → bouton dit "Retirer" et ring-primary visible', async () => {
    renderBrowser(new Set(['ms-python.python']))
    await waitFor(() => screen.getByText('Python'))

    const removeBtn = screen.getByRole('button', { name: /^(remove|retirer)$/i })
    expect(removeBtn).toBeDefined()
    const card = removeBtn.closest('[role="button"]')
    expect(card?.className).toContain('ring-primary')
  })

  it('clic sur le corps de la carte → dialog détail visible', async () => {
    const user = userEvent.setup()

    renderBrowser()
    await waitFor(() => screen.getByText('Python'))

    await user.click(screen.getByText('Python language support'))

    await waitFor(() => {
      const dialog = screen.getByRole('dialog')
      expect(dialog).toBeInTheDocument()
      expect(within(dialog).getByText('Python')).toBeInTheDocument()
    })
  })

  it('dialog affiche le README markdown rendu', async () => {
    const user = userEvent.setup()

    server.use(
      http.get('/plugins/:namespace/:name/readme', () =>
        new HttpResponse('# Python README', { headers: { 'Content-Type': 'text/markdown' } }),
      ),
    )

    renderBrowser()
    await waitFor(() => screen.getByText('Python'))
    await user.click(screen.getByText('Python language support'))

    await waitFor(() => screen.getByRole('dialog'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Python README')
    })
  })

  it("erreur readme → message d'erreur readme affiché dans la dialog", async () => {
    const user = userEvent.setup()

    server.use(
      http.get('/plugins/:namespace/:name/readme', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    )

    renderBrowser()
    await waitFor(() => screen.getByText('Python'))
    await user.click(screen.getByText('Python language support'))

    await waitFor(() => screen.getByRole('dialog'))
    await waitFor(() => {
      expect(
        screen.getByText(/impossible de charger le readme|could not load plugin readme/i),
      ).toBeInTheDocument()
    })
  })

  it('affiche le bouton "Charger plus" quand total > items chargés', async () => {
    server.use(
      http.get('/plugins/search', () =>
        HttpResponse.json({ total: 50, offset: 0, items: [MOCK_PLUGIN] }),
      ),
    )
    renderBrowser()
    await waitFor(() => screen.getByRole('button', { name: /load more|charger plus/i }))
  })

  it('pas de bouton "Charger plus" quand tout est chargé', async () => {
    renderBrowser()
    await waitFor(() => screen.getByText('Python'))
    expect(screen.queryByRole('button', { name: /load more|charger plus/i })).not.toBeInTheDocument()
  })

  it("erreur 502 → message d'erreur traduit affiché", async () => {
    server.use(
      http.get('/plugins/search', () =>
        HttpResponse.json({ detail: 'Bad Gateway' }, { status: 502 }),
      ),
    )
    renderBrowser()
    await waitFor(() =>
      expect(
        screen.getByText(/impossible de contacter|unable to reach|registry/i),
      ).toBeInTheDocument(),
    )
  })
})
