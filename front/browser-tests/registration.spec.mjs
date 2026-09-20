import { test, expect, mount, jsonRoute } from './fixtures.mjs'

test('direct signup redirects to login when closed and rechecks on reopening', async ({ page }) => {
  let open = false
  await page.route('**/api/auth/registration-status', route => route.fulfill({ json: { registration_open: open } }))
  const options = { authenticated: false, route: '/user/register' }
  await mount(page, 'core/user/pages/register.vue', options)
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/user/login')
  await expect(page.getByLabel('Email', { exact: true })).toHaveCount(0)
  open = true
  await page.evaluate(options => window.testApp.mount({ component: 'core/user/pages/register.vue', ...options }), options)
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Log in', exact: true })).toBeVisible()
})

test('signup stays unavailable while checking and offers retry after an error', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/auth/registration-status', async route => {
    await pending
    await route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
  })
  await mount(page, 'core/user/pages/register.vue', { authenticated: false, route: '/user/register' })
  await expect(page.getByLabel('Email', { exact: true })).toHaveCount(0)
  release()
  await expect(page.getByRole('alert')).toContainText('Unable to check whether registration is open')
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: true })
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible()
})

test('an open form handles registration closing during input', async ({ page }) => {
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: true })
  await mount(page, 'core/user/pages/register.vue', { authenticated: false, route: '/user/register' })
  await page.getByLabel('Email', { exact: true }).fill('visitor@example.com')
  await page.getByLabel('Password', { exact: true }).fill('Visitor-password-123')
  await page.getByLabel('Confirm password', { exact: true }).fill('Visitor-password-123')
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: false })
  await page.route('**/api/auth/register', route => route.fulfill({ status: 403, json: { detail: 'Public registration is closed' } }))
  await page.getByRole('button', { name: 'Sign up', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/user/login')
  await expect(page.getByLabel('Email', { exact: true })).toHaveCount(0)
})

for (const open of [true, false]) {
  test(`login offers signup only when registration is ${open ? 'open' : 'closed'}`, async ({ page }) => {
    await jsonRoute(page, '**/api/auth/registration-status', { registration_open: open })
    await mount(page, 'core/user/pages/login.vue', { authenticated: false })
    await expect(page.getByRole('link', { name: 'Sign up', exact: true })).toHaveCount(open ? 1 : 0)
    await expect(page.getByRole('button', { name: 'Log in', exact: true })).toBeVisible()
  })
}

test('a late status response cannot redirect after leaving signup', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/auth/registration-status', async route => {
    await pending
    await route.fulfill({ json: { registration_open: false } })
  })
  await mount(page, 'core/user/pages/register.vue', { authenticated: false, route: '/user/register' })
  await page.evaluate(async () => {
    window.testApp.unmount()
    await window.testApp.router.push('/elsewhere')
  })
  const response = page.waitForResponse('**/api/auth/registration-status')
  release()
  await response
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/elsewhere')
})
