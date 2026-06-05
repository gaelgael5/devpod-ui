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

export function renderWithProviders(
  ui: React.ReactElement,
  { route = '/' }: { route?: string } = {}
): RenderResult {
  const queryClient = makeQueryClient()
  const router = createMemoryRouter(
    [{ path: '*', element: <I18nextProvider i18n={i18n}>{ui}</I18nextProvider> }],
    { initialEntries: [route] }
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
