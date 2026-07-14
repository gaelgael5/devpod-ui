import {
  test as base,
  chromium,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test'

/**
 * Fixtures e2e — navigateur DISTANT (Browserless sur test1) + session admin.
 *
 * Playwright, par défaut, lance son propre Chromium. Ici on veut un Chromium
 * distant (celui de test1) : on remplace donc les fixtures `context`/`page` par
 * un contexte issu d'un navigateur connecté via CDP. `E2E_CDP_URL` absent ⇒
 * repli sur un Chromium local (utile pour développer les specs hors test1).
 */

const CDP_URL = process.env.E2E_CDP_URL
const STORAGE_STATE = 'e2e/.auth/state.json'

async function connect(): Promise<Browser> {
  if (CDP_URL) return chromium.connectOverCDP(CDP_URL)
  return chromium.launch()
}

interface Fixtures {
  context: BrowserContext
  page: Page
}

interface WorkerFixtures {
  remoteBrowser: Browser
}

export const test = base.extend<Fixtures, WorkerFixtures>({
  remoteBrowser: [
    async ({}, use) => {
      const browser = await connect()
      await use(browser)
      // connectOverCDP : close() détache la session sans tuer le Chromium distant.
      await browser.close()
    },
    { scope: 'worker' },
  ],
  context: async ({ remoteBrowser }, use, testInfo) => {
    // Le projet `setup` crée la session sans storageState préexistant.
    const useState = testInfo.project.name !== 'setup'
    const context = await remoteBrowser.newContext({
      baseURL: process.env.E2E_BASE_URL,
      storageState: useState ? STORAGE_STATE : undefined,
    })
    await use(context)
    await context.close()
  },
  page: async ({ context }, use) => {
    const page = await context.newPage()
    await use(page)
  },
})

export { expect } from '@playwright/test'
export { STORAGE_STATE }
