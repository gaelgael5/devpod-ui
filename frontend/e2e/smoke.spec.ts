import { test, expect } from './fixtures'

/** Fume : la session admin établie par auth.setup.ts est bien exploitable. */
test.describe('Smoke', () => {
  test('la session est authentifiée et admin (/me)', async ({ page }) => {
    const r = await page.request.get('/me')
    expect(r.ok(), `/me a répondu HTTP ${r.status()}`).toBeTruthy()
    const me = await r.json()
    expect(me.is_admin).toBe(true)
  })

  test('accès authentifié — /workspaces ne redirige pas vers le login', async ({ page }) => {
    await page.goto('/workspaces')
    await expect(page).toHaveURL(/\/workspaces/)
  })
})
