import type { APIRequestContext, Page } from '@playwright/test'
import { test, expect } from './fixtures'

/**
 * Helpers e2e : navigation vers les surfaces UI + seeding d'état via l'API du
 * portail (toutes les routes /me/* héritent du cookie de session du contexte).
 */

/** skill_id de démonstration (repris des tests backend) — source/skill. */
export const DEMO_SKILL_ID = 'github/awesome-copilot/git-commit'

/**
 * Workspace running fourni par l'opérateur pour les parcours nécessitant un
 * conteneur provisionné (sessions, terminal, placement, initializers) : ces
 * états ne sont pas seedables à moindre coût (provisioning réel sur un nœud).
 * Absent ⇒ le test se `skip` proprement plutôt que d'échouer.
 */
export const E2E_WS = process.env.E2E_WS

export function requireWorkspace(): string {
  test.skip(!E2E_WS, 'E2E_WS (workspace running) non fourni — parcours ignoré')
  return E2E_WS as string
}

/** Locator de la carte d'un workspace sur /workspaces (racine data-testid). */
export function workspaceCard(page: Page, ws: string) {
  return page.getByTestId(`workspace-card-${ws}`)
}

/** Ouvre l'onglet « Skills » de la page /git-credentials. */
export async function openSkillsTab(page: Page): Promise<void> {
  await page.goto('/git-credentials')
  await page.getByRole('tab', { name: 'Skills' }).click()
  await expect(page.getByRole('heading', { name: /Skills \(skills\.sh\)/ })).toBeVisible()
}

/** Crée (idempotent) un grant pour la skill donnée. Retourne la réponse brute. */
export async function seedGrant(request: APIRequestContext, skillId = DEMO_SKILL_ID) {
  const r = await request.post('/me/skills/grants', { data: { skill_id: skillId } })
  expect(r.ok(), `seed grant a échoué (HTTP ${r.status()})`).toBeTruthy()
  return r
}

/** Applique une transition de cycle de vie sur un grant. */
export async function grantAction(
  request: APIRequestContext,
  grantId: number,
  action: 'approve' | 'revoke' | 'pause' | 'resume',
) {
  const r = await request.post(`/me/skills/grants/${grantId}/${action}`)
  expect(r.ok(), `${action} grant a échoué (HTTP ${r.status()})`).toBeTruthy()
  return r
}

/** Liste les grants de l'utilisateur courant. */
export async function listGrants(request: APIRequestContext) {
  const r = await request.get('/me/skills/grants')
  expect(r.ok()).toBeTruthy()
  return (await r.json()) as Array<{
    id: number
    skill_id: string
    statut: string
    approved_hash: string | null
  }>
}

/** Révoque tout grant résiduel de la skill (nettoyage best-effort d'un test). */
export async function cleanupGrant(request: APIRequestContext, skillId = DEMO_SKILL_ID) {
  const grants = await listGrants(request)
  for (const g of grants.filter((x) => x.skill_id === skillId && x.statut !== 'revoked')) {
    await request.post(`/me/skills/grants/${g.id}/revoke`).catch(() => undefined)
  }
}
