import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests', testMatch: '*.spec.ts', workers: 1, retries: 0,
  timeout: 45_000, expect: { timeout: 10_000 },
  outputDir: '../artifacts/desktop/browser', reporter: [['list']]
})
