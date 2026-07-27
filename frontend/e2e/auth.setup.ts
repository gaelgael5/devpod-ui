import fs from 'node:fs'
import path from 'node:path'
import { test as setup, expect, STORAGE_STATE } from './fixtures'

/**
 * Établit une session admin réutilisable, sans piloter Keycloak headless.
 *
 * `POST /auth/local-login` (dev, `dev_mode` + `allow_local_auth`) pose le cookie
 * de session avec le rôle admin. On sérialise ce cookie dans storageState ; tous
 * les scénarios le rechargent (voir playwright.config.ts, projet `chromium`).
 *
 * Requiert `E2E_LOCAL_USER` / `E2E_LOCAL_PASSWORD` (identifiants locaux de la
 * stack de test), et la stack déployée avec l'auth locale autorisée.
 */
setup('authentifie la session admin via local-login', async ({ page, context }) => {
  const username = process.env.E2E_LOCAL_USER
  const password = process.env.E2E_LOCAL_PASSWORD
  expect(username, 'E2E_LOCAL_USER requis').toBeTruthy()
  expect(password, 'E2E_LOCAL_PASSWORD requis').toBeTruthy()

  const resp = await page.request.post('/auth/local-login', {
    data: { username, password },
  })
  expect(resp.ok(), `local-login a échoué (HTTP ${resp.status()})`).toBeTruthy()

  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true })
  await context.storageState({ path: STORAGE_STATE })
})
