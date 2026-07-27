import { test, expect } from './fixtures'
import { requireWorkspace, workspaceCard } from './helpers'

/**
 * AT — Réintégrer les actions Initialize (start recipes) du workspace.
 * Requiert un workspace running (E2E_WS). Les initializers n'apparaissent que
 * si le workspace en déclare (GET /me/workspaces/<ws>/initializers non vide).
 */
test.describe('AT — Actions Initialize', () => {
  test('le menu Actions expose les initializers déclarés', async ({ page }) => {
    const ws = requireWorkspace()

    const r = await page.request.get(`/me/workspaces/${ws}/initializers`)
    const inits = r.ok() ? await r.json() : []
    test.skip(!Array.isArray(inits) || inits.length === 0, 'workspace sans initializer déclaré')

    await page.goto('/workspaces')
    const card = workspaceCard(page, ws)
    await card.getByRole('button', { name: 'Actions' }).click()
    await expect(page.getByRole('menuitem', { name: 'Lancer' }).first()).toBeVisible()
  })
})
