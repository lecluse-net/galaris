import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

test('Browser preferences appear only for an active connection and refresh after connection changes', async ({ page }) => {
  let enabled = false
  await page.route('**/api/browser/status', route => route.fulfill({ json: { enabled } }))
  await jsonRoute(page, '**/api/connections/7', { id: 7, tool_id: 2, agent_id: 1, active: true })
  await mount(page, 'core/params/pages/index.vue', { privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT'] })
  const link = page.getByRole('link', { name: /Browser/ })
  await expect(link).toHaveCount(0)
  enabled = true
  await page.evaluate(async () => {
    const { default: connectionService } = await import('/app/connection/services/connectionService.ts')
    await connectionService.updateConnection(7, { active: true })
  })
  await expect(link).toBeVisible()
  enabled = false
  await page.evaluate(async () => {
    const { default: connectionService } = await import('/app/connection/services/connectionService.ts')
    await connectionService.updateConnection(7, { active: false })
  })
  await expect(link).toHaveCount(0)
})

test('direct Browser preferences access recovers status failures and returns home when unused', async ({ page }) => {
  let failed = true
  await page.route('**/api/browser/status', route => route.fulfill(failed
    ? { status: 503, json: { detail: 'offline' } } : { json: { enabled: false } }))
  await mount(page, 'app/browser/pages/settings.vue', {
    route: '/browser/settings', privileges: ['PARAMS_ACCESS'],
  })
  await expect(page.getByText('Browser preferences could not be loaded.')).toBeVisible()
  await expect(page.locator('input')).toHaveCount(0)
  failed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/params')
  await expect(page.locator('input')).toHaveCount(0)
})

for (const [name, label, initial, saved, rejected, divisor = 1] of [
  ['BROWSER_VIEWPORT_WIDTH', 'Default window width (pixels)', '1200', '1600', '2000'],
  ['BROWSER_SESSION_TTL_SECONDS', 'Maximum session idle time (seconds)', '120', '180', '240'],
  ['BROWSER_MAX_SESSIONS', 'Maximum concurrent sessions', '32', '48', '64'],
  ['BROWSER_HTML_MAX_BYTES', 'Maximum HTML size (MB)', '10000', '300000', '500000', 1000000],
  ['BROWSER_SCREENSHOT_MAX_TOTAL_BYTES', 'Maximum total screenshot size (MB)', '20000000', '25000000', '50000000', 1000000],
]) {
test(`${name} preserves values across saves, errors, reopen and read-only access`, async ({ page }) => {
  await jsonRoute(page, '**/api/browser/status', { enabled: true })
  const param = { name, value: initial, configured: true, secret: false }
  await page.route('**/api/params', route => route.fulfill({ json: { params: [param] } }))
  let fail = false
  await page.route(`**/api/params/${name}`, route => {
    if (fail) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
    param.value = route.request().postDataJSON().value
    return route.fulfill({ json: { ...param, status: 'success' } })
  })
  await mount(page, 'app/browser/pages/settings.vue', { privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT'] })
  const width = page.getByLabel(label, { exact: true })
  const display = value => String(Number(value) / divisor)
  await expect(width).toHaveValue(display(initial))
  await width.fill(display(saved))
  await width.press('Tab')
  await expect.poll(() => param.value).toBe(saved)
  fail = true
  await width.fill(display(rejected))
  await width.press('Tab')
  await expect(width).toHaveValue(display(saved))
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(width).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.evaluate(() => window.testApp.mount({ component: 'app/browser/pages/settings.vue' }))
  await expect(width).toHaveValue(display(saved))
  await setPrivileges(page, ['PARAMS_ACCESS'])
  await expect(width).toHaveAttribute('readonly', '')
})
}

test('a late Browser availability response cannot restore a signed-out preference page', async ({ page }) => {
  let pending
  await page.route('**/api/browser/status', route => { pending = route })
  await mount(page, 'core/params/pages/index.vue', { privileges: ['PARAMS_ACCESS'] })
  await expect.poll(() => Boolean(pending)).toBe(true)
  await page.evaluate(() => window.testApp.auth.$patch({ token: null }))
  await pending.fulfill({ json: { enabled: true } })
  await expect(page.getByRole('link', { name: /Browser/ })).toHaveCount(0)
})
