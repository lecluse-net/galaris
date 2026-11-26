import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const routes = [
  ['Configure an LLM', '/llm?tab=providers'],
  ['Create your first agent', '/agent'],
  ['Configure messaging', '/services?tab=connections'],
  ['Add tools', '/services'],
  ['Choose skills', '/skill'],
  ['Prepare processes', '/process'],
]
const setupPrivileges = [
  'LANGUAGE_CONFIG_ACCESS', 'LANGUAGE_CONFIG_EDIT', 'LLM_PROVIDER_EDIT', 'AGENT_EDIT',
  'CONNECTION_EDIT', 'SERVICE_EDIT', 'SKILL_ASSIGN', 'PROCESS_EDIT',
]
const admin = { role: { id: 1, code: 'admin' }, privileges: ['LLM_PROVIDER_EDIT'] }

async function welcome(page, privileges = setupPrivileges, allowed = true) {
  const status = { has_data: false, has_privilege: allowed, show: allowed }
  await jsonRoute(page, '**/api/onboarding/overview', { language_configured: false, ...Object.fromEntries(
    ['llm_provider', 'agents', 'connections', 'tools', 'skills', 'processes'].map(key => [key, status]),
  ) })
  await mount(page, 'app/index/pages/welcome.vue', { route: '/welcome', privileges })
  await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toBeVisible()
}

test('the administrator opens Welcome when only the instance language is missing', async ({ page }) => {
    const param = { name: 'DEFAULT_LANGUAGE', value: '', secret: false, configured: false, prompt: null }
    const ready = { has_data: true, has_privilege: false, show: false }
    await page.route('**/api/onboarding/overview', route => route.fulfill({ json: {
      language_configured: Boolean(param.value),
      ...Object.fromEntries(['llm_provider', 'agents', 'connections', 'tools', 'skills', 'processes'].map(key => [key, ready])),
    } }))
    await page.route('**/api/params', route => route.fulfill({ json: { params: [param] } }))
    await page.route('**/api/params/DEFAULT_LANGUAGE', route => {
      param.value = route.request().postDataJSON().value
      return route.fulfill({ json: { ...param, status: 'ok' } })
    })
    const privileges = ['LANGUAGE_CONFIG_ACCESS', 'LANGUAGE_CONFIG_EDIT']
    await mount(page, 'app/index/pages/index.vue', { ...admin, privileges })
    await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toBeVisible()
    await page.getByRole('combobox', { name: 'Default language' }).click()
    await page.getByRole('option', { name: 'English', exact: true }).click()
    await expect.poll(() => param.value).toBe('en')
    await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toBeVisible()
    await mount(page, 'app/index/pages/index.vue', { ...admin, privileges })
    await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toBeVisible()
})

for (const width of [390, 1440]) {
  test(`preconfigured home keeps Welcome until confirmation is saved (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const ready = { has_data: true, has_privilege: true, show: false }
    await jsonRoute(page, '**/api/onboarding/overview', { language_configured: true, ...Object.fromEntries(
      ['llm_provider', 'agents', 'connections', 'tools', 'skills', 'processes'].map(key => [key, ready]),
    ) })
    const dismissed = []
    let fail = true
    await page.route('**/api/auth/me/help-dismissals', route => route.fulfill({ json: dismissed }))
    await page.route('**/api/auth/me/help-dismissals/onboarding.welcome', route => {
      if (fail) return route.fulfill({ status: 503 })
      dismissed.push('onboarding.welcome')
      return route.fulfill({ status: 204 })
    })
    await mount(page, 'app/index/pages/index.vue', admin)
    const title = page.getByRole('heading', { name: 'Welcome to Galaris' })
    await expect(title).toBeVisible()
    await page.getByRole('button', { name: /Configure an LLM/ }).click()
    await page.getByRole('article', { name: 'Configure an LLM' }).getByRole('link').click()
    // Returning home from provider setup must preserve access to Welcome.
    await mount(page, 'app/index/pages/index.vue', admin)
    await expect(title).toBeVisible()
    const confirm = page.getByRole('button', { name: 'Setup complete — open home', exact: true })
    await confirm.press('Enter')
    await expect(page.getByRole('alert')).toContainText('not saved')
    await expect(title).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('welcome-confirmation-light.png'), fullPage: true })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('welcome-confirmation-dark.png'), fullPage: true })
    fail = false
    await confirm.click()
    await expect(title).toHaveCount(0)
    expect(dismissed).toEqual(['onboarding.welcome'])
    await mount(page, 'app/index/pages/index.vue', admin)
    await expect(title).toHaveCount(0)
    // Another account still gets its own first-run journey.
    dismissed.length = 0
    await page.evaluate(() => { window.testApp.auth.user = { ...window.testApp.auth.user, id: 2 } })
    await expect(title).toBeVisible()
    await mount(page, 'app/index/pages/welcome.vue', { ...admin, route: '/welcome' })
    await expect(title).toBeVisible()
  })
}

test('home keeps a failed confirmation read visible and recovers on explicit retry', async ({ page }) => {
  const ready = { has_data: true, has_privilege: false, show: false }
  await jsonRoute(page, '**/api/onboarding/overview', { language_configured: true, ...Object.fromEntries(
    ['llm_provider', 'agents', 'connections', 'tools', 'skills', 'processes'].map(key => [key, ready]),
  ) })
  let failed = true
  let reads = 0
  await page.route('**/api/auth/me/help-dismissals', route => {
    reads++
    return failed ? route.fulfill({ status: 503 }) : route.fulfill({ json: ['onboarding.welcome'] })
  })
  await mount(page, 'app/index/pages/index.vue', admin)
  await expect(page.getByRole('alert')).toContainText('Unable to check your setup confirmation')
  await expect(page.getByRole('button', { name: 'Setup complete — open home', exact: true })).toBeDisabled()
  expect(reads).toBe(1)
  failed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('.home-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toHaveCount(0)
  expect(reads).toBe(2)
})

for (const width of [320, 390, 768, 1024, 1440]) {
  test(`welcome saves the default language and opens every setup destination at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const param = { name: 'DEFAULT_LANGUAGE', value: '', secret: false, configured: false, prompt: null }
    let failSave = true
    const writes = []
    await page.route('**/api/params', route => route.fulfill({ json: { params: [param] } }))
    await page.route('**/api/params/DEFAULT_LANGUAGE', route => {
      writes.push(route.request().postDataJSON().value)
      if (failSave) return route.fulfill({ status: 500, json: { detail: 'Synthetic save failure' } })
      param.value = writes.at(-1)
      return route.fulfill({ json: { ...param, status: 'ok' } })
    })
    await welcome(page)
    const language = page.getByRole('combobox', { name: 'Default language' })
    const languageStep = page.getByRole('article', { name: 'Default language', exact: true })
    await expect(languageStep.getByText('Step 1 of 7')).toBeVisible()
    await expect(languageStep.getByRole('link')).toHaveCount(0)
    await expect(language).toHaveValue('Not set')
    await language.click()
    await page.getByRole('option', { name: 'English', exact: true }).click()
    await expect.poll(() => writes.at(-1)).toBe('en')
    await expect(language).toHaveValue('Not set')
    failSave = false
    await language.click()
    await page.getByRole('option', { name: 'French', exact: true }).click()
    await expect.poll(() => param.value).toBe('fr')
    await expect(language).toHaveCount(0)
    await expect(languageStep.getByRole('status')).toContainText('French')
    await welcome(page)
    await expect(languageStep.getByRole('status')).toContainText('French')
    await expect(language).toHaveCount(0)

    const journey = page.getByRole('region', { name: 'Setup journey' })
    const timeline = journey.locator('.q-stepper__header')
    // Every step must fit horizontally, even when the timeline spans several rows.
    await expect.poll(() => timeline.evaluate(header => {
      const bounds = header.getBoundingClientRect()
      return header.scrollWidth <= header.clientWidth && [...header.children].every(step => {
        const rect = step.getBoundingClientRect()
        return rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1
      })
    })).toBe(true)
    await expect(journey.getByRole('button', { name: /Default language/ })).toHaveAttribute('aria-current', 'step')
    await languageStep.getByRole('button', { name: 'Next step', exact: true }).click()
    const llmStep = page.getByRole('article', { name: 'Configure an LLM', exact: true })
    await expect(llmStep).toBeVisible()
    await llmStep.getByRole('button', { name: 'Previous step', exact: true }).click()
    await expect(languageStep.getByRole('status')).toContainText('French')
    await journey.screenshot({ path: testInfo.outputPath('journey-light.png') })
    await page.evaluate(() => window.testApp.dark(true))
    await journey.screenshot({ path: testInfo.outputPath('journey-dark.png') })
    await page.evaluate(() => window.testApp.dark(false))
    for (const [label, destination] of routes) {
      const tab = journey.getByRole('button', { name: new RegExp(label) })
      await tab.focus()
      await page.keyboard.press('Enter')
      const content = page.getByRole('article', { name: label, exact: true })
      await expect(content).toBeVisible()
      const link = content.getByRole('link')
      await expect(link).toHaveAttribute('href', destination)
      await link.focus()
      await page.keyboard.press('Enter')
      await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(destination)
      await page.evaluate(() => window.testApp.navigate('/welcome'))
    }
    param.value = ''
    await welcome(page, ['LANGUAGE_CONFIG_ACCESS'])
    await expect(page.getByRole('article', { name: 'Default language' }).locator('.q-select')).toHaveAttribute('aria-disabled', 'true')
    await jsonRoute(page, '**/api/teams/human-selection?self_only=true', [])
    await setPrivileges(page, [])
    await expect(language).toHaveCount(0)
  })
}

test('welcome retries language loading and navigates only between permitted setup steps', async ({ page }) => {
  let failRead = true
  await page.route('**/api/params', route => failRead
    ? route.fulfill({ status: 500, json: { detail: 'Synthetic read failure' } })
    : route.fulfill({ json: { params: [{ name: 'DEFAULT_LANGUAGE', value: '', secret: false, configured: false, prompt: null }] } }))
  await welcome(page, ['LANGUAGE_CONFIG_ACCESS', 'CONNECTION_ACCESS', 'LLM_MODEL_ACCESS', 'TEAM_ACCESS'], false)
  await expect(page.getByRole('combobox', { name: 'Default language' })).toHaveCount(0)
  failRead = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Default language' }).locator('.q-select')).toHaveAttribute('aria-disabled', 'true')
  const journey = page.getByRole('region', { name: 'Setup journey' })
  for (const [label] of routes.filter(([, destination]) => destination !== '/services?tab=connections')) {
    await expect(journey.getByRole('button', { name: new RegExp(label) })).toHaveCount(0)
  }
  await journey.getByRole('button', { name: 'Next step', exact: true }).click()
  const step = journey.getByRole('article', { name: 'Configure messaging', exact: true })
  await expect(step.getByText('Step 2 of 2')).toBeVisible()
  await expect(step.getByText('Your account does not have the permission', { exact: false })).toBeVisible()
  await expect(step.getByRole('link', { name: 'Open page' })).toHaveAttribute('href', '/services?tab=connections')
  await setPrivileges(page, ['LLM_PROVIDER_ACCESS'])
  await expect(journey.getByRole('article', { name: 'Configure an LLM' }).getByText('Step 1 of 1')).toBeVisible()
})

test('members see their own teams, contact profiles and only their available uses', async ({ page }, testInfo) => {
  await jsonRoute(page, '**/api/teams/human-selection?self_only=true', [{ id: 1, teams: [{ id: 8, name: 'Research', order: 1 }] }])
  await jsonRoute(page, '**/api/chat/recipients?page=1&page_size=50', {
    agents: [{ agent_id: 7, display_name: 'Alice Example', active: true }], total: 1,
  })
  await jsonRoute(page, '**/api/chat/agents/7/profile', {
    job_title: 'Research analyst', job_description: '<p>Prepare <strong>briefing notes</strong>.</p>',
    personality: '<p>Curious and precise.</p>', external_services: [{ code: 'external_docs', label: 'External Docs' }],
  })
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({
    contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j6WQAAAAASUVORK5CYII=', 'base64'),
  }))
  await page.setViewportSize({ width: 1440, height: 900 })
  await mount(page, 'app/index/pages/index.vue', { privileges: ['DOCUMENT_ACCESS', 'CHAT_ACCESS', 'CHAT_SEND', 'AGENT_ACCESS'] })
  await expect(page.getByRole('region', { name: 'Your teams' })).toContainText('Research')
  await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toHaveCount(0)
  const uses = page.getByRole('region', { name: 'What you can do' })
  await expect(uses.getByRole('link', { name: 'Open Documents' })).toHaveAttribute('href', '/documents')
  await expect(uses).toContainText('Find and read documents you can access')
  await expect(uses.getByRole('link', { name: 'Open Processes' })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('member-home-light.png'), fullPage: true })

  const agent = page.getByRole('button', { name: /Alice Example/ })
  await agent.press('Enter')
  const profile = page.getByRole('dialog', { name: 'Alice Example' })
  await expect(profile).toContainText('Research analyst')
  await expect(profile).toContainText('briefing notes')
  await expect(profile).toContainText('Curious and precise.')
  await expect(profile).toContainText('External Docs')
  await expect(profile.getByRole('img', { name: 'Alice Example' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 900 })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('member-profile-mobile-dark.png'), fullPage: true })
  await page.keyboard.press('Escape')
  await expect(profile).toHaveCount(0)
  await expect(agent).toBeFocused()
  await page.screenshot({ path: testInfo.outputPath('member-home-mobile-dark.png'), fullPage: true })
  await agent.click()
  await setPrivileges(page, ['DOCUMENT_EDIT'])
  await expect(profile).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Agents you can contact' })).toHaveCount(0)
  await expect(uses).toContainText('Create working documents')
})
