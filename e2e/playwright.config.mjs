import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './specs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  outputDir: '/artifacts/results',
  reporter: [['list'], ['html', { outputFolder: '/artifacts/report', open: 'never' }],
    ['junit', { outputFile: '/artifacts/junit.xml' }],
    ['json', { outputFile: '/artifacts/results.json' }]],
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'firefox', use: { browserName: 'firefox' } },
    // Playwright's Linux launcher selects GTK without --headless. WPE build 2336
    // crashes intermittently during MFA input; GTK runs the same assertions and
    // tracing under the runner's Xvfb display (see reliability-operations.md).
    { name: 'webkit', use: { browserName: 'webkit', headless: false } },
  ],
  use: {
    baseURL: 'http://localhost:8484',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'block',
  },
})
