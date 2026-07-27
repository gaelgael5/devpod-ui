import { test, expect } from './fixtures'
import { requireWorkspace } from './helpers'

/**
 * AT — Reconnexion d'une session depuis son onglet.
 * Requiert un workspace running (E2E_WS). On simule la chute réseau via
 * `context.setOffline` : la WS se ferme, l'overlay de reconnexion apparaît, et
 * « Reconnecter » se rattache au tmux survivant (scrollback préservé).
 */
test.describe('AT — Reconnexion de session', () => {
  test('session vivante — le terminal et la barre de touches sont affichés', async ({ page }) => {
    const ws = requireWorkspace()
    const sname = 'e2e-recon'
    await page.request.post(`/me/workspaces/${ws}/sessions`, {
      data: { name: sname, start_recipe: null },
    })

    await page.goto(`/workspaces/${ws}/terminals?session=${sname}`)
    await expect(page.locator('.xterm')).toBeVisible()
    await expect(page.getByRole('toolbar')).toBeVisible()
  })

  test('chute réseau → overlay, puis reconnexion sur tmux vivant', async ({ page, context }) => {
    const ws = requireWorkspace()
    const sname = 'e2e-recon'
    await page.request.post(`/me/workspaces/${ws}/sessions`, {
      data: { name: sname, start_recipe: null },
    })

    await page.goto(`/workspaces/${ws}/terminals?session=${sname}`)
    await expect(page.locator('.xterm')).toBeVisible()

    // Coupe le réseau → la WebSocket se ferme involontairement.
    await context.setOffline(true)
    await expect(page.getByText('Session déconnectée.')).toBeVisible()

    // Rétablit puis reconnecte : rattachement au tmux survivant.
    await context.setOffline(false)
    await page.getByRole('button', { name: 'Reconnecter' }).click()
    await expect(page.getByText('Session déconnectée.')).toBeHidden()
    await expect(page.locator('.xterm')).toBeVisible()
  })
})
