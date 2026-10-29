import { test, expect, mount } from './fixtures.mjs'

// Visit traversal, errors and retry belong to the shared Document navigation
// scenarios; typed-documents and the Data E2E journey retain JSON draft coverage.
for (const [source, destination] of [
  ['/dataset', '/documents?type=data'],
  ['/dataset/00000000-0000-4000-8000-000000000321', '/documents?document_id=00000000-0000-4000-8000-000000000321'],
]) test(`legacy Data navigation preserves its selection: ${source}`, async ({ page }) => {
  await mount(page, 'test-support/browser/DatasetRouteHarness.vue', { route: source, privileges: ['DOCUMENT_ACCESS'] })
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(destination)
})
