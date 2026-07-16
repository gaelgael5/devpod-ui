import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './server'
import { useUserStore } from '@/store/user'

// jsdom ne fournit pas ResizeObserver — mock minimal pour les composants qui l'utilisent (ex. FullscreenTerminal via xterm FitAddon)
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// jsdom ne fournit pas window.matchMedia — requis par xterm (Terminal._updateDpr) dès qu'un
// terminal est monté (ex. WorkspaceSessionTerminal après création/sélection d'une session)
window.matchMedia ??= () => ({
  matches: false,
  media: '',
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
})

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  useUserStore.getState().clear()
})
afterAll(() => server.close())
