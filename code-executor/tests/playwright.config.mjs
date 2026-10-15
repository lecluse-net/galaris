import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: '.', testMatch: 'native-ide.spec.mjs', workers: 1, timeout: 60_000,
  expect: { timeout: 15_000 }, outputDir: '/artifacts/code-results',
  reporter: [['list'], ['json', { outputFile: '/artifacts/code-results.json' }]],
  use: { baseURL: 'http://localhost:8766', screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
