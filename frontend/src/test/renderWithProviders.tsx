import type React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderResult } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import i18n from '@/i18n'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
}

/**
 * `path` sert aux ecrans qui lisent leurs parametres d'URL (`useParams`).
 *
 * Le defaut attrape-tout suffit tant qu'un composant ne lit que son chemin ;
 * des qu'il attend un segment nomme, il faut declarer le motif, sinon
 * `useParams` rend un objet vide et le composant croit sa cible introuvable.
 *
 * `state` sert aux ecrans qui lisent l'etat de navigation (`useLocation`),
 * comme la page forfaits qui y trouve sa page d'origine.
 */
export function renderWithProviders(
  ui: React.ReactElement,
  { route = '/', path = '*', state }: { route?: string; path?: string; state?: unknown } = {}
): RenderResult {
  const queryClient = makeQueryClient()
  const router = createMemoryRouter(
    [{ path, element: <I18nextProvider i18n={i18n}>{ui}</I18nextProvider> }],
    { initialEntries: [{ pathname: route, state }] }
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
