import { test, expect } from './fixtures'
import {
  requireWorkspace,
  workspaceCard,
  seedGrant,
  grantAction,
  listGrants,
  cleanupGrant,
  DEMO_SKILL_ID,
} from './helpers'

/**
 * AT — Placement des skills validées dans les workspaces.
 * Requiert un workspace running (E2E_WS) : le placement exécute réellement
 * `npx skills add` dans le conteneur puis vérifie le hash post-install.
 */
test.describe('AT — Placement des skills', () => {
  test('placer puis retirer une skill validée dans un workspace', async ({ page }) => {
    const ws = requireWorkspace()
    test.setTimeout(180_000) // installation réelle dans le conteneur

    await cleanupGrant(page.request)
    await seedGrant(page.request)
    const g = (await listGrants(page.request)).find((x) => x.skill_id === DEMO_SKILL_ID)!
    await grantAction(page.request, g.id, 'approve')

    await page.goto('/workspaces')
    const card = workspaceCard(page, ws)
    await card.getByRole('button', { name: 'Actions' }).click()
    await page.getByRole('menuitem', { name: /Skills du workspace/ }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(new RegExp(`Skills du workspace ${ws}`))).toBeVisible()

    // Installer la première skill validée disponible (option 0 = placeholder).
    await dialog.getByLabel('Installer une skill validée').selectOption({ index: 1 })
    await dialog.getByRole('button', { name: 'Installer' }).click()

    // Placement affiché (vérifié ou non selon la dérive de hash amont).
    const placedRow = dialog.locator('li').filter({ hasText: DEMO_SKILL_ID })
    await expect(placedRow).toBeVisible({ timeout: 150_000 })

    // Retrait : fichiers + ligne de placement supprimés, grant per-user conservé.
    await placedRow.getByRole('button', { name: /Retirer/ }).click()
    await expect(dialog.getByText('Aucune skill installée dans ce workspace.')).toBeVisible()

    await cleanupGrant(page.request)
  })
})
