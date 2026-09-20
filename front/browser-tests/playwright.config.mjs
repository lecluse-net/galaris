import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.mjs',
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  outputDir: '/artifacts/results',
  reporter: [['list'], ['html', { outputFolder: '/artifacts/report', open: 'never' }],
    ['junit', { outputFile: '/artifacts/junit.xml' }],
    ['json', { outputFile: '/artifacts/results.json' }]],
  use: {
    baseURL: 'http://localhost:8000',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
