import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

const welcomeTest = test.extend({
  languageSetting: async ({ request }, use) => {
    let previous
    let headers
    await use(async accessToken => {
      headers = { Authorization: `Bearer ${accessToken}` }
      const response = await request.get('/api/params', { headers })
      expect(response.ok()).toBeTruthy()
      previous = (await response.json()).params.find(param => param.name === 'DEFAULT_LANGUAGE').value
      const cleared = await request.put('/api/params/DEFAULT_LANGUAGE', { headers, data: { value: '' } })
      expect(cleared.ok()).toBeTruthy()
    })
    if (headers) {
      const restored = await request.put('/api/params/DEFAULT_LANGUAGE', { headers, data: { value: previous } })
      expect(restored.ok()).toBeTruthy()
    }
  },
})

welcomeTest('welcome persists the default language and opens configuration pages in the assembled app', async ({ page, request, languageSetting }, testInfo) => {
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok()).toBeTruthy()
  const pageErrors = collectPageErrors(page)
  const fixture = await seeded.json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await pageErrors.settle()
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('.home-page, .welcome-page')).toBeVisible()
  await pageErrors.settle()
  await languageSetting(session.access_token)
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
  const overview = await request.get('/api/onboarding/overview', { headers: { Authorization: `Bearer ${session.access_token}` } })
  expect(overview.ok()).toBeTruthy()
  expect(await overview.json()).toMatchObject({
    language_configured: false,
    llm_provider: { has_data: true },
    agents: { has_data: true },
  })
  // The profile is already French; missing instance language must still open Welcome.
  await pageErrors.settle()
  await page.goto('/')

  const errors = []
  page.on('response', response => {
    if (new URL(response.url()).pathname.startsWith('/api/') && response.status() >= 400) {
      errors.push(`${response.status()} ${response.request().method()} ${response.url()}`)
    }
  })
  const language = page.getByRole('combobox', { name: 'Langue par défaut' })
  await expect(language).toBeVisible()
  await language.click()
  // Saving the language mounts Home's independent panels. Wait for those reads
  // before replacing its document to exercise persistence after a reload.
  const homeLoaded = Promise.all([
    '/api/chat/rooms', '/api/tasks/recent', '/api/processes/runs',
    '/api/memory/recent', '/api/incidents/recent', '/api/dashboard',
  ].map(path => page.waitForResponse(response => new URL(response.url()).pathname === path)
    .then(response => response.finished())))
  const saved = page.waitForResponse(response => response.url().endsWith('/api/params/DEFAULT_LANGUAGE') && response.request().method() === 'PUT')
  await page.getByRole('option', { name: 'Français', exact: true }).click()
  expect((await saved).ok()).toBeTruthy()
  await expect(page.locator('.home-page')).toBeVisible()
  await homeLoaded
  await pageErrors.settle()
  await page.reload()
  await expect(page.locator('.home-page')).toBeVisible()
  await expect(language).toHaveCount(0)
  await pageErrors.settle()
  await page.goto('/welcome')
  const languageStep = page.getByRole('article', { name: 'Langue par défaut' })
  await expect(languageStep.getByRole('status')).toContainText('Français')
  await expect(language).toHaveCount(0)
  await expect(languageStep.getByRole('link')).toHaveCount(0)

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await pageErrors.settle()
    await page.goto('/welcome')
    await expect(languageStep).toBeVisible()
    if (width < 1024) {
      const backdrop = page.locator('.q-drawer__backdrop')
      // Resizing and route changes can already close the mobile drawer.
      // Open it explicitly to exercise dismissal regardless of that timing.
      if (!await backdrop.isVisible()) {
        await page.locator('.mobile-taskbar').getByRole('button', { name: 'Déployer la sidebar' }).click()
      }
      await expect(backdrop).toBeVisible()
      await backdrop.click({ position: { x: width - 10, y: 200 } })
      await expect(backdrop).toBeHidden()
    }
    const journey = page.getByRole('region', { name: 'Parcours de configuration' })
    const agent = journey.getByRole('button', { name: /Créer votre premier agent/ })
    await expect(agent).toBeVisible()
    await expect.poll(() => journey.locator('.q-stepper__header').evaluate(header => header.scrollWidth <= header.clientWidth)).toBe(true)
    await journey.screenshot({ path: testInfo.outputPath(`journey-fr-${width}.png`) })
    await agent.focus()
    await page.keyboard.press('Enter')
    const content = page.getByRole('article', { name: 'Créer votre premier agent' })
    await expect(content).toBeVisible()
    await content.getByRole('link').click()
    await expect(page).toHaveURL(/\/agent$/)
    await expect(page.getByRole('heading', { name: 'Agents', exact: true })).toBeVisible()
  }
  expect([...errors, ...pageErrors()]).toEqual([])
})
