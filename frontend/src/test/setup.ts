import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './server'
import { useUserStore } from '@/store/user'

// jsdom ne fournit pas ResizeObserver — mock minimal pour les composants qui l'utilisent (ex. SshTerminalWindow via xterm FitAddon)
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  useUserStore.getState().clear()
})
afterAll(() => server.close())
