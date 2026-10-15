import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: '.', testMatch: 'gateway-ide.spec.mjs', workers: 1, timeout: 90_000,
  expect: { timeout: 20_000 }, outputDir: `/artifacts/gateway-${process.env.CODE_TEST_PROXY}-results`,
  reporter: [['list'], ['json', { outputFile: `/artifacts/gateway-${process.env.CODE_TEST_PROXY}-results.json` }]],
  use: { screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: ['chromium', 'firefox', 'webkit'].map(browserName => ({ name: browserName, use: { browserName } })),
})
