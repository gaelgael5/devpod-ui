import { test, expect } from './fixtures'
import { requireWorkspace, workspaceCard } from './helpers'

/**
 * AT — Suppression d'une session depuis le menu Sessions (N).
 * Requiert un workspace running (E2E_WS) : la session est seedée via l'API.
 */
test.describe('AT — Suppression de session', () => {
  test('supprime une session via le menu et la confirmation', async ({ page }) => {
    const ws = requireWorkspace()
    const sname = 'e2e-del'

    // Seed de la session (idempotent : 409 toléré si elle existe déjà).
    await page.request.post(`/me/workspaces/${ws}/sessions`, {
      data: { name: sname, start_recipe: null },
    })

    await page.goto('/workspaces')
    const card = workspaceCard(page, ws)
    await card.getByRole('button', { name: /Sessions \(/ }).click()

    const menu = page.getByRole('menu')
    await expect(menu.getByRole('menuitem', { name: sname })).toBeVisible()
    await menu.getByRole('button', { name: `Supprimer la session ${sname}` }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Supprimer la session ?')).toBeVisible()
    await dialog.getByRole('button', { name: 'Supprimer' }).click()

    await expect(page.getByText(`Session « ${sname} » supprimée.`)).toBeVisible()
  })
})
