import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function setup(page, { locale = 'en', privileges = ['PARAMS_ACCESS', 'PARAMS_EDIT'] } = {}) {
  const values = {
    PROCESS_N8N_BASE_URL: 'https://n8n.example.test', PROCESS_N8N_API_TOKEN: null,
    PROCESS_N8N_WEBHOOK_BASE_URL: '', PROCESS_GALARIS_BASE_URL: '',
    PROCESS_N8N_WEBHOOK_AUTH_TOKEN: null, PROCESS_N8N_WEBHOOK_AUTH_HEADER: 'X-Galaris-Webhook-Token',
    PROCESS_N8N_CALLBACK_AUTH_HEADER: 'X-Galaris-Callback-Token',
  }
  const params = Object.entries(values).map(([name, value]) => ({ name, value, secret: name.endsWith('_TOKEN'), configured: Boolean(value) || name === 'PROCESS_N8N_API_TOKEN' }))
  await page.route('**/api/params', route => route.fulfill({ json: { params } }))
  const writes = []
  await page.route('**/api/params/*', route => {
    const name = new URL(route.request().url()).pathname.split('/').at(-1)
    const update = route.request().postDataJSON()
    writes.push({ name, ...update })
    const param = params.find(item => item.name === name)
    param.configured = Boolean(update.value)
    param.value = param.secret ? null : update.value
    return route.fulfill({ json: { ...param, status: 'success' } })
  })
  await jsonRoute(page, '**/api/n8n/settings', { galaris_base_url: 'https://galaris.example.test' })
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', { locale, props: { section: 'process' }, privileges })
  return { params, writes }
}

for (const locale of ['en', 'fr']) {
  test(`n8n setup saves before testing, preserves secrets and explains the test scope (${locale})`, async ({ page }, testInfo) => {
    let tests = 0
    await page.route('**/api/n8n/test', route => {
      tests++
      return route.fulfill({ json: { ok: true, code: 'healthy', message: 'n8n API: 3 workflows' } })
    })
    const { writes } = await setup(page, { locale })
    const url = page.getByLabel(locale === 'fr' ? 'URL de n8n' : 'n8n URL', { exact: true })
    const key = page.getByLabel(locale === 'fr' ? 'Clé API n8n' : 'n8n API key', { exact: true })
    const button = page.getByRole('button', { name: locale === 'fr' ? 'Tester la connexion' : 'Test connection', exact: true })
    // Password managers must not mistake the instance address and API key for a login.
    await expect(url).toHaveAttribute('type', 'url')
    await expect(url).toHaveAttribute('autocomplete', 'off')
    await expect(key).toHaveAttribute('autocomplete', 'new-password')
    await url.fill('login@example.test')
    await button.click()
    expect(tests).toBe(0)
    expect(writes).toEqual([])
    await expect.poll(() => url.evaluate(input => input.validity.typeMismatch)).toBe(true)
    await expect(page.getByText('https://galaris.example.test', { exact: true })).toBeVisible()
    await expect(key).toHaveValue('')
    await expect(page.getByText(locale === 'fr' ? /Le lancement des webhooks/ : /Webhook execution, execution tracking/)).toBeVisible()
    let pending
    await page.route('**/api/params/PROCESS_N8N_BASE_URL', route => { pending = route })
    await url.fill('https://new-n8n.example.test')
    await key.fill('new-secret')
    await button.click()
    await expect.poll(() => Boolean(pending)).toBe(true)
    expect(tests).toBe(0)
    expect(writes).toEqual([])
    await pending.fulfill({ json: { name: 'PROCESS_N8N_BASE_URL', value: 'https://new-n8n.example.test', secret: false, configured: true } })
    await expect(page.getByRole('status')).toContainText('n8n API: 3 workflows')
    expect(writes).toEqual([{ name: 'PROCESS_N8N_API_TOKEN', value: 'new-secret', clear_secret: false }])
    await expect(key).toHaveValue('')
    await button.click()
    await expect.poll(() => tests).toBe(2)
    expect(writes).toHaveLength(1)
    await page.setViewportSize({ width: 390, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`n8n-${locale}-mobile.png`), fullPage: true })
  })
}

test('n8n setup preserves failed saves, retries diagnostics and keeps advanced settings on reopen', async ({ page }) => {
  let tests = 0
  let failSave = true
  let pendingTest
  await page.route('**/api/n8n/test', route => {
    tests++
    if (tests === 3) { pendingTest = route; return }
    return route.fulfill({ json: tests === 1
      ? { ok: false, code: 'unauthorized', message: '' }
      : { ok: true, code: 'healthy', message: 'n8n API reachable' } })
  })
  const { params } = await setup(page)
  const key = page.getByLabel('n8n API key', { exact: true })
  const button = page.getByRole('button', { name: 'Test connection', exact: true })
  await page.route('**/api/params/PROCESS_N8N_API_TOKEN', route => {
    if (failSave) return route.fulfill({ status: 503, json: { detail: 'offline' } })
    return route.fulfill({ json: params.find(item => item.name === 'PROCESS_N8N_API_TOKEN') })
  })
  await key.fill('replacement')
  await button.click()
  await expect(page.getByRole('status')).toContainText('The test was not started')
  await expect(key).toHaveValue('replacement')
  expect(tests).toBe(0)
  failSave = false
  await button.click()
  await expect(page.getByRole('status')).toContainText('API key rejected')
  await button.click()
  await expect(page.getByRole('status')).toContainText('n8n API reachable')
  await page.getByText('Advanced addresses and authentication', { exact: true }).click()
  await page.getByLabel('Galaris URL as seen from n8n', { exact: true }).fill('http://galaris.internal:8000')
  await expect(page.getByRole('status')).toHaveCount(0)
  await page.getByRole('button', { name: 'Generate a secret', exact: true }).click()
  await expect(page.getByLabel('Webhook authentication secret', { exact: true })).toHaveValue(/^[a-f0-9]{64}$/)
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByLabel('Webhook authentication secret', { exact: true })).toHaveValue('')
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', { props: { section: 'process' }, privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT'] })
  await expect(page.getByText('http://galaris.internal:8000', { exact: true })).toBeVisible()
  await button.click()
  await expect.poll(() => Boolean(pendingTest)).toBe(true)
  await setPrivileges(page, ['PARAMS_ACCESS'])
  await pendingTest.fulfill({ json: { ok: true, code: 'healthy', message: 'stale response' } })
  await expect(button).toHaveCount(0)
  await expect(page.getByRole('status')).toHaveCount(0)
  await expect(key).toHaveAttribute('readonly', '')
})

test('n8n automatic addresses can recover after a load failure', async ({ page }) => {
  await setup(page)
  await page.route('**/api/n8n/settings', route => route.fulfill({ status: 503, json: {} }))
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', { props: { section: 'process' }, privileges: ['PARAMS_EDIT'] })
  await expect(page.getByRole('alert')).toContainText('Could not load automatic addresses')
  await expect(page.getByRole('button', { name: 'Test connection', exact: true })).toBeDisabled()
  await jsonRoute(page, '**/api/n8n/settings', { galaris_base_url: 'https://recovered.example.test' })
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('https://recovered.example.test', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Test connection', exact: true })).toBeEnabled()
})
