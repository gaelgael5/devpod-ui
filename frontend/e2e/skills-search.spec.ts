import { test, expect } from './fixtures'
import { openSkillsTab } from './helpers'

/**
 * AT — Onglet Recherche skills.sh.
 * On vérifie le CÂBLAGE (la recherche interroge le proxy serveur) sans dépendre
 * de la disponibilité/réponse de skills.sh : le proxy peut renvoyer un succès
 * comme une erreur amont, les deux prouvent que le parcours est branché.
 */
test.describe('AT — Recherche skills.sh', () => {
  test("l'onglet Skills expose le champ de recherche", async ({ page }) => {
    await openSkillsTab(page)
    await expect(page.getByPlaceholder('Rechercher une skill…')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Rechercher' })).toBeVisible()
  })

  test('la recherche interroge le proxy /me/skills/search', async ({ page }) => {
    await openSkillsTab(page)
    await page.getByPlaceholder('Rechercher une skill…').fill('git')
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/me/skills/search')),
      page.getByRole('button', { name: 'Rechercher' }).click(),
    ])
    // 200 (résultats) ou erreur amont (clé absente / skills.sh indisponible) :
    // dans tous les cas la requête a bien été émise vers le proxy serveur.
    expect(resp.request().method()).toBe('GET')
  })
})
