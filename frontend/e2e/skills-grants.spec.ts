import { test, expect } from './fixtures'
import {
  openSkillsTab,
  seedGrant,
  grantAction,
  listGrants,
  cleanupGrant,
  DEMO_SKILL_ID,
} from './helpers'

/**
 * AT — Onglet Validations : cycle de vie des grants.
 * Entièrement seedable via l'API (aucun workspace requis). L'approbation
 * déclenche le calcul serveur de l'approved_hash (fetch SKILL.md) : la stack de
 * test doit pouvoir joindre la source (GitHub raw).
 */
test.describe('AT — Validations : cycle de vie des grants', () => {
  test.beforeEach(async ({ page }) => {
    await cleanupGrant(page.request)
  })
  test.afterEach(async ({ page }) => {
    await cleanupGrant(page.request)
  })

  const row = (page: import('@playwright/test').Page) =>
    page.locator('li').filter({ hasText: DEMO_SKILL_ID }).first()

  test('une demande pending apparaît sous Validations', async ({ page }) => {
    await seedGrant(page.request)
    await openSkillsTab(page)
    await expect(page.getByRole('heading', { name: 'Validations' })).toBeVisible()
    await expect(row(page)).toBeVisible()
    await expect(row(page).getByText(/En attente de validation/i)).toBeVisible()
  })

  test('examiner affiche le SKILL.md et son hash', async ({ page }) => {
    await seedGrant(page.request)
    await openSkillsTab(page)
    await row(page).getByRole('button', { name: 'Examiner' }).click()
    await expect(page.getByText(/Hash courant/i)).toBeVisible()
  })

  test('approuver fait passer le grant à validée (+ approved_hash)', async ({ page }) => {
    await seedGrant(page.request)
    await openSkillsTab(page)
    await row(page).getByRole('button', { name: 'Valider' }).click()
    await expect(row(page).getByText(/^Validée$/)).toBeVisible()
    const g = (await listGrants(page.request)).find((x) => x.skill_id === DEMO_SKILL_ID)
    expect(g?.statut).toBe('granted')
    expect(g?.approved_hash).toBeTruthy()
  })

  test('mise en pause puis remise en service', async ({ page }) => {
    await seedGrant(page.request)
    const g = (await listGrants(page.request)).find((x) => x.skill_id === DEMO_SKILL_ID)!
    await grantAction(page.request, g.id, 'approve')
    await openSkillsTab(page)
    await row(page).getByRole('button', { name: 'Mettre en pause' }).click()
    await expect(row(page).getByText(/En pause/i)).toBeVisible()
    await row(page).getByRole('button', { name: 'Remettre en service' }).click()
    await expect(row(page).getByText(/^Validée$/)).toBeVisible()
  })

  test('révoquer coupe le grant (cascade)', async ({ page }) => {
    await seedGrant(page.request)
    await openSkillsTab(page)
    await row(page).getByRole('button', { name: 'Révoquer' }).click()
    await expect(async () => {
      const g = (await listGrants(page.request)).find((x) => x.skill_id === DEMO_SKILL_ID)
      expect(g?.statut).toBe('revoked')
    }).toPass()
  })
})
