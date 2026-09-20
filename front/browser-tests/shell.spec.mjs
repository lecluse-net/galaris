import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

test('home cards and links follow granted privileges, including revocation', async ({ page }) => {
  await mount(page, 'app/index/components/HomeActionCenter.vue')
  await expect(page.locator('.attention-card')).toHaveCount(0)
  await expect(page.locator('.quick-card')).toHaveCount(0)
  await expect(page.locator('.home-metrics')).toHaveCount(0)
  await jsonRoute(page, '**/api/chat/rooms*', { items: [], total: 0, page: 1, page_size: 50 })
  await setPrivileges(page, ['CHAT_ACCESS'])
  await expect(page.locator('.attention-card')).toBeVisible()
  await expect(page.locator('.quick-card a[href="/chat"]')).toBeVisible()
  await expect(page.locator('.quick-card a[href="/agent"]')).toHaveCount(0)
  // Retain another quick action so removing the card's own v-if is observable.
  await setPrivileges(page, ['AGENT_ACCESS'])
  await expect(page.locator('.attention-card')).toHaveCount(0)
  await expect(page.locator('.quick-card a[href="/agent"]')).toBeVisible()
})

for (const width of [390, 1440]) {
  for (const registrationOpen of [true, false]) {
    test(`public home opens ${registrationOpen ? 'registration' : 'login'} with the keyboard at ${width}px`, async ({ page }) => {
      await jsonRoute(page, '**/api/auth/registration-status', { registration_open: registrationOpen, initial_admin_required: registrationOpen })
      await page.setViewportSize({ width, height: 950 })
      await mount(page, 'app/index/components/HomePublic.vue', { authenticated: false })
      const destination = registrationOpen ? '/user/register' : '/user/login'
      const login = page.locator(`a[href="${destination}"]`)
      await expect(login).toBeVisible()
      await login.press('Enter')
      await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe(destination)
      await page.evaluate(() => window.testApp.dark(true))
      await expect(login).toBeVisible()
    })
  }
}

for (const registrationOpen of [true, false]) {
  test(`guest menu opens ${registrationOpen ? 'registration' : 'login'}`, async ({ page }) => {
    await jsonRoute(page, '**/api/auth/registration-status', { registration_open: registrationOpen, initial_admin_required: registrationOpen })
    await mount(page, 'core/user/components/UserMenu.vue', { authenticated: false })
    const destination = registrationOpen ? '/user/register' : '/user/login'
    const login = page.locator(`a[href="${destination}"]`)
    await expect(login).toBeVisible()
    await login.click()
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe(destination)
  })
}

test('login rechecks when another visitor has created the first account', async ({ page }) => {
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: true, initial_admin_required: true })
  await mount(page, 'app/index/components/HomePublic.vue', { authenticated: false })
  const login = page.locator('a[href="/user/register"]')
  await expect(login).toBeVisible()
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: false, initial_admin_required: false })
  await login.click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/user/login')
})

test('login still opens login for existing users when ordinary signup is enabled', async ({ page }) => {
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: true, initial_admin_required: false })
  await mount(page, 'app/index/components/HomePublic.vue', { authenticated: false })
  await page.locator('a[href="/user/login"]').click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/user/login')
})

test('a failed account check remains retryable without guessing a destination', async ({ page }) => {
  await page.route('**/api/auth/registration-status', route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }))
  await mount(page, 'app/index/components/HomePublic.vue', { authenticated: false })
  await expect(page.getByText('Unable to check whether registration is open. Please try again.')).toBeVisible()
  expect(await page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/')
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: true, initial_admin_required: true })
  await page.locator('.public-actions__primary').click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/user/register')
})
