import { test, expect } from '@playwright/test'

test('a late document library response cannot cancel navigation to another lazy page', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const title = `Navigation race ${fixture.agent_id}`
  const created = await request.post('/api/memory/items', {
    headers: { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' },
    data: { owner_agent_id: fixture.agent_id, title, node_kind: 'document', memory_type: 'working',
      media_type: 'text/html', payload: { text: '<p>Preserved document</p>' } },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  let releaseLibrary, releaseNavigation
  const library = new Promise(resolve => { releaseLibrary = resolve })
  const navigation = new Promise(resolve => { releaseNavigation = resolve })
  // Delay the real list response: the library now loads classification tags,
  // so the old folder-options endpoint no longer exercises this race.
  await page.route('**/api/memory/documents/library', async route => { await library; await route.continue() })
  const libraryRequest = page.waitForRequest('**/api/memory/documents/library')
  try {
    await page.goto('/memory/documents')
    await libraryRequest
    await expect(page.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible()
    await expect(page.getByText(title, { exact: true })).toHaveCount(0)
    // Hold the next page's actual lazy JS chunk while the previous API request finishes.
    await page.route('**/assets/*.js', async route => { await navigation; await route.continue() })
    const chunk = page.waitForRequest(request => new URL(request.url()).pathname.startsWith('/assets/') && request.url().endsWith('.js'))
    await page.locator('a[href="/memory"]').first().click()
    await chunk
    releaseLibrary()
    await expect(page.getByText(title, { exact: true }).first()).toBeVisible()
    releaseNavigation()
    await expect(page).toHaveURL(/\/memory$/)
    await expect(page.getByRole('tab', { name: 'Recherche', exact: true })).toBeVisible()
  } finally { releaseLibrary(); releaseNavigation() }
})

// Exercise lazy consumers against the real API, permissions and PostgreSQL.
// No connector account or remote model is needed to browse local configuration.
for (const width of [390, 1440]) {
  for (const scenario of [
    { path: '/tools', tab: 'Connexions', other: 'Outils' },
    { path: '/tools', tab: 'Autorisations', other: 'Outils' },
    { path: '/skill', tab: 'Autorisations', other: 'Compétences' },
  ]) {
    test(`${scenario.path} ${scenario.tab} loads usable agent choices and preserves them across tabs at ${width}px`, async ({ page, request }) => {
      await page.setViewportSize({ width, height: 900 })
      const seeded = await request.post('/api/__test/seed')
      expect(seeded.ok()).toBeTruthy()
      const fixture = await seeded.json()
      const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
      await page.goto('/user/login')
      await refresh
      await page.locator('input[type=email]').fill(fixture.email)
      await page.locator('input[type=password]').fill(fixture.password)
      await page.locator('button[type=submit]').click()
      await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
      const failures = []
      page.on('pageerror', error => failures.push(error.message))
      page.on('response', response => {
        if (new URL(response.url()).pathname.startsWith('/api/') && response.status() >= 400) {
          failures.push(`${response.status()} ${response.request().method()} ${response.url()}`)
        }
      })
      // Use the real menu: a full reload immediately after login can make
      // WebKit report the discarded home page's requests as page errors.
      if (width < 1024) {
        await expect(page.locator('.mobile-taskbar')).toBeVisible()
        if (!await page.locator('.q-drawer__backdrop').isVisible()) {
          await page.locator('.mobile-taskbar').getByRole('button', { name: 'Déployer la sidebar' }).click()
        }
      }
      await page.locator(`a[href="${scenario.path}"]`).first().click()
      await expect(page).toHaveURL(new RegExp(`${scenario.path}$`))
      if (width < 1024) {
        // Navigation may already have closed during login. Dismiss it only if
        // it obstructs the next action, including a late mobile layout update.
        await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
          await backdrop.click({ position: { x: width - 10, y: 200 } })
        }, { times: 1 })
      }
      await page.getByRole('tab', { name: scenario.tab, exact: true }).click()
      const filter = page.getByRole('combobox', { name: 'Filtrer par agent', exact: true })
      await filter.click()
      const option = page.getByRole('option').filter({ hasText: /Browser/ }).first()
      await expect(option).toBeVisible()
      const label = await option.getAttribute('aria-label')
      expect(label).toBeTruthy()
      await option.click()
      await expect(page.getByRole('listbox')).toHaveCount(0)
      await expect(page.locator('.q-field').filter({ has: filter })).toContainText(label)
      await page.getByRole('tab', { name: scenario.other, exact: true }).click()
      await page.getByRole('tab', { name: scenario.tab, exact: true }).click()
      await expect(page.locator('.q-field').filter({ has: filter })).toContainText(label)
      // Opening again must still resolve the server-authorized selection.
      await filter.click()
      await expect(page.getByRole('option', { name: label, exact: true })).toBeVisible()
      await page.keyboard.press('Escape')
      expect(failures).toEqual([])
    })
  }
}
