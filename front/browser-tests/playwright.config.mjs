import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.mjs',
  fullyParallel: true,
  workers: 4,
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
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'webkit-links', testMatch: 'galaris-links.spec.mjs', grep: /a document .* navigates without a modal/, use: { browserName: 'webkit' } },
    { name: 'webkit-composer', testMatch: 'chat.spec.mjs', grep: /composer/, use: { browserName: 'webkit' } },
    { name: 'firefox-chat-recovery', testMatch: 'chat-recovery.spec.mjs', grep: /recovers a lost POST response/, use: { browserName: 'firefox' } },
    { name: 'firefox-shortcuts', testMatch: 'document-shortcuts.spec.mjs', use: { browserName: 'firefox' } },
    { name: 'webkit-shortcuts', testMatch: 'document-shortcuts.spec.mjs', use: { browserName: 'webkit' } },
    { name: 'firefox-mindmap-export', testMatch: 'mindmap.spec.mjs', grep: /image export and print/, use: { browserName: 'firefox' } },
    { name: 'webkit-mindmap-export', testMatch: 'mindmap.spec.mjs', grep: /image export and print/, use: { browserName: 'webkit' } },
  ],
})
