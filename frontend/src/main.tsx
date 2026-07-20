import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { getWebInstrumentations, initializeFaro } from '@grafana/faro-web-sdk'
import { Toaster } from '@/components/ui/sonner'
import { router } from './router'
import { i18nReady } from './i18n'
import './index.css'

// Avant tout le reste : capte les erreurs/logs même si l'app plante à l'init.
// Même chemin relatif same-origin que le reste des appels API (cf. shared/api/client.ts)
// → Caddy route /faro/collect vers le collecteur Alloy interne (deploy/Caddyfile).
initializeFaro({
  url: '/faro/collect',
  app: {
    name: 'devpod-ui',
    version: __APP_VERSION__,
    environment: import.meta.env.MODE,
  },
  instrumentations: [...getWebInstrumentations({ captureConsole: true })],
})

// Onglet périmé après un redéploiement : une route lazy demande un chunk hashé
// (/assets/*-HASH.js) qui n'existe plus → le serveur répond 404 et Vite émet
// `vite:preloadError`. On recharge UNE fois pour récupérer l'index.html à jour
// (garde sessionStorage anti-boucle si le problème persistait vraiment).
window.addEventListener('vite:preloadError', () => {
  if (sessionStorage.getItem('spaPreloadReloaded')) return
  sessionStorage.setItem('spaPreloadReloaded', '1')
  window.location.reload()
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 0, retry: 1 },
    mutations: { retry: false },
  },
})

i18nReady.then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster />
      </QueryClientProvider>
    </StrictMode>
  )
})
