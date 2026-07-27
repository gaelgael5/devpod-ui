import { defineConfig } from '@playwright/test'

/**
 * Configuration e2e — cible la stack DÉPLOYÉE (test1), pas un serveur local.
 *
 * Le portail complet (backend + front build) tourne sur test1 ; le navigateur
 * est un Chromium distant (Browserless) sur la même VM. Tout est piloté par
 * variables d'environnement pour rester agnostique de l'IP éphémère de la VM :
 *
 *   E2E_BASE_URL   URL du portail          (ex. http://192.168.10.196:8080)
 *   E2E_CDP_URL    endpoint CDP Browserless (ex. http://192.168.10.196:3000)
 *                  — si absent, un Chromium LOCAL est lancé (npx playwright
 *                    install chromium requis).
 *
 * Voir e2e/README.md pour le cycle complet contre test1.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8080'

export default defineConfig({
  testDir: '.',
  // Placeholders des ATDD encore sans automatisation ⇒ exclure les *.todo.spec.
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    // 1) Établit la session admin (local-login) et la sérialise dans storageState.
    { name: 'setup', testMatch: 'auth.setup.ts' },
    // 2) Les scénarios réutilisent cette session (chargée par le fixture
    //    `context`, cf. fixtures.ts — pas via use.storageState, car on crée le
    //    contexte nous-mêmes depuis le navigateur distant).
    { name: 'chromium', dependencies: ['setup'] },
  ],
})
