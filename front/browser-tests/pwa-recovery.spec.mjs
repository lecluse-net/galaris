import { test, expect } from '@playwright/test'

test('the development module worker starts without caching and removes its previous caches', async ({ page }) => {
  await page.goto('/test-support/browser/index.html')
  await page.evaluate(async () => {
    await caches.open('workbox-precache-v2-http://localhost:8000/pwa/')
    await caches.open('user-content')
    await navigator.serviceWorker.register('/pwa/sw.ts', { type: 'module' })
  })
  await expect.poll(() => page.evaluate(async () => (
    await navigator.serviceWorker.getRegistration('/pwa/')
  )?.active?.state)).toBe('activated')
  expect(await page.evaluate(() => caches.keys())).toEqual(['user-content'])
  await page.reload()
  expect(await page.evaluate(() => caches.keys())).toEqual(['user-content'])
})

test('an old production worker releases the cached shell when returning to development', async ({ page }) => {
  await page.goto('/test-support/browser/index.html')
  await page.evaluate(async () => {
    await caches.open('user-content')
    await navigator.serviceWorker.register(`/sw.js?legacy-fixture=${crypto.randomUUID()}`, { scope: '/', updateViaCache: 'none' })
    await navigator.serviceWorker.ready
  })
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Old application' })).toBeVisible()
  expect(await page.evaluate(() => caches.keys())).toContain('workbox-precache-v2-http://localhost:8000/')
  // A normal refresh still serves the old shell, as in the reported failure.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Old application' })).toBeVisible()
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration()
    await registration.update()
  })
  await expect.poll(() => page.evaluate(() => !!window.testApp?.mount)).toBe(true)
  await expect(page.getByRole('heading', { name: 'Old application' })).toHaveCount(0)
  expect(await page.evaluate(() => caches.keys())).toEqual(['user-content'])
  await page.reload()
  await expect.poll(() => page.evaluate(() => !!window.testApp?.mount)).toBe(true)
  expect(await page.evaluate(() => caches.keys())).toEqual(['user-content'])
  expect(await page.evaluate(async () => !!await navigator.serviceWorker.getRegistration())).toBe(true)
})
