import { test, expect } from './fixtures'
import { requireWorkspace } from './helpers'

/**
 * AT — Barre de touches & actions dans la fenêtre de session SSH.
 * Requiert un workspace running (E2E_WS) pour une session terminal réelle.
 * Le comportement d'envoi bas niveau (\x1b / \x03 / presse-papier) est déjà
 * couvert par le test unitaire TerminalKeybar.test.tsx ; ici on valide la
 * présence de la barre et le retour utilisateur « Copier sans sélection ».
 */
test.describe('AT — Barre de touches de session', () => {
  test('la barre expose Échap / Interrompre / Coller / Copier', async ({ page }) => {
    const ws = requireWorkspace()
    const sname = 'e2e-keys'
    await page.request.post(`/me/workspaces/${ws}/sessions`, {
      data: { name: sname, start_recipe: null },
    })

    await page.goto(`/workspaces/${ws}/terminals?session=${sname}`)
    const bar = page.getByRole('toolbar')
    await expect(bar.getByRole('button', { name: 'Échap' })).toBeVisible()
    await expect(bar.getByRole('button', { name: 'Interrompre' })).toBeVisible()
    await expect(bar.getByRole('button', { name: 'Coller' })).toBeVisible()
    await expect(bar.getByRole('button', { name: 'Copier' })).toBeVisible()
  })

  test('Copier sans sélection notifie l’utilisateur', async ({ page }) => {
    const ws = requireWorkspace()
    const sname = 'e2e-keys'
    await page.request.post(`/me/workspaces/${ws}/sessions`, {
      data: { name: sname, start_recipe: null },
    })

    await page.goto(`/workspaces/${ws}/terminals?session=${sname}`)
    await page.getByRole('toolbar').getByRole('button', { name: 'Copier' }).click()
    await expect(page.getByText('Aucune sélection à copier')).toBeVisible()
  })
})
