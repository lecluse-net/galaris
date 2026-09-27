import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const routes = [
  ['Configure an LLM', '/llm?tab=providers'],
  ['Create your first agent', '/agent'],
  ['Configure messaging', '/tools?tab=connections'],
  ['Add tools', '/tools'],
  ['Choose skills', '/skill'],
  ['Prepare processes', '/process'],
]

async function welcome(page, privileges = ['PARAMS_ACCESS', 'PARAMS_EDIT'], allowed = true) {
  const status = { has_data: false, has_privilege: allowed, show: allowed }
  await jsonRoute(page, '**/api/onboarding/overview', { language_configured: false, ...Object.fromEntries(
    ['llm_provider', 'agents', 'connections', 'tools', 'skills', 'processes'].map(key => [key, status]),
  ) })
  await mount(page, 'app/index/pages/welcome.vue', { route: '/welcome', privileges })
  await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toBeVisible()
}

for (const canEdit of [true, false]) {
  test(`home opens Welcome when only the instance language is missing (editable: ${canEdit})`, async ({ page }) => {
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
    const privileges = canEdit ? ['PARAMS_ACCESS', 'PARAMS_EDIT'] : []
    await mount(page, 'app/index/pages/index.vue', { privileges })
    await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toBeVisible()
    if (!canEdit) {
      await expect(page.getByRole('combobox', { name: 'Default language' })).toHaveCount(0)
      await expect(page.getByText('Your account does not have the permission', { exact: false })).toBeVisible()
      return
    }
    await page.getByRole('combobox', { name: 'Default language' }).click()
    await page.getByRole('option', { name: 'English', exact: true }).click()
    await expect.poll(() => param.value).toBe('en')
    await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toHaveCount(0)
    await mount(page, 'app/index/pages/index.vue', { privileges })
    await expect(page.locator('.home-page')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Welcome to Galaris' })).toHaveCount(0)
  })
}

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
    await welcome(page, ['PARAMS_ACCESS'])
    await expect(page.getByRole('article', { name: 'Default language' }).locator('.q-select')).toHaveAttribute('aria-disabled', 'true')
    await setPrivileges(page, [])
    await expect(language).toHaveCount(0)
  })
}

test('welcome retries language loading and keeps restricted setup destinations unavailable', async ({ page }) => {
  let failRead = true
  await page.route('**/api/params', route => failRead
    ? route.fulfill({ status: 500, json: { detail: 'Synthetic read failure' } })
    : route.fulfill({ json: { params: [{ name: 'DEFAULT_LANGUAGE', value: '', secret: false, configured: false, prompt: null }] } }))
  await welcome(page, ['PARAMS_ACCESS'], false)
  await expect(page.getByRole('combobox', { name: 'Default language' })).toHaveCount(0)
  failRead = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Default language' }).locator('.q-select')).toHaveAttribute('aria-disabled', 'true')
  await expect(page.getByRole('region', { name: 'Setup journey' }).getByRole('link')).toHaveCount(0)
  await page.getByRole('button', { name: /Create your first agent/ }).click()
  const step = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Create your first agent' }) })
  await expect(step.getByText('Your account does not have the permission', { exact: false })).toBeVisible()
})
