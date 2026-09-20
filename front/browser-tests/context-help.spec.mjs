import { test, expect, mount } from './fixtures.mjs'

const endpoint = '**/api/auth/me/help-dismissals'
const component = 'core/util/components/PageHeader.vue'
const props = { icon: 'help', title: 'Agents', helpKey: 'agents', helpText: 'Choose an agent and start a conversation.' }
const help = page => page.getByRole('complementary', { name: 'Contextual help' })

test('the preferences menu remains usable without contextual help', async ({ page }) => {
  await mount(page, 'core/params/pages/index.vue')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(help(page)).toHaveCount(0)
})

for (const action of ['Got it', 'Permanently dismiss this help']) {
  test(`${action} persists dismissal and leaves other help available`, async ({ page }) => {
    const dismissed = []
    await page.route(endpoint, route => route.fulfill({ json: dismissed }))
    await page.route(`${endpoint}/*`, route => {
      expect(route.request().method()).toBe('PUT')
      dismissed.push(route.request().url().split('/').at(-1))
      return route.fulfill({ status: 204 })
    })
    await mount(page, component, { props })
    await expect(help(page)).toContainText(props.helpText)
    await page.getByRole('button', { name: action, exact: true }).press('Enter')
    await expect(help(page)).toHaveCount(0)
    expect(dismissed).toEqual(['agents'])
    await page.evaluate(() => window.testApp.setProps({ helpKey: 'documents', helpText: 'Keep your documents here.' }))
    await expect(help(page)).toContainText('Keep your documents here.')
    // A fresh app instance reads durable account state rather than browser storage.
    await mount(page, component, { props })
    await expect(help(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible()
  })
}

test('a failed dismissal stays visible and can be retried', async ({ page }) => {
  let attempts = 0
  await page.route(`${endpoint}/*`, route => route.fulfill({ status: ++attempts === 1 ? 503 : 204 }))
  await mount(page, component, { props })
  await page.getByRole('button', { name: 'Got it', exact: true }).click()
  await expect(help(page).getByRole('alert')).toContainText('not saved')
  await page.getByRole('button', { name: 'Permanently dismiss this help' }).click()
  await expect(help(page)).toHaveCount(0)
  expect(attempts).toBe(2)
})

test('unknown preferences never flash previously dismissed help and loading can be retried', async ({ page }) => {
  let respond
  await page.route(endpoint, route => new Promise(resolve => {
    respond = async () => { await route.fulfill({ status: 503 }); resolve() }
  }))
  await mount(page, component, { props })
  await expect.poll(() => Boolean(respond)).toBe(true)
  await expect(help(page)).toHaveCount(0)
  await respond()
  await expect(help(page).getByRole('alert')).toContainText('Unable to load')
  await expect(help(page)).not.toContainText(props.helpText)
  await page.route(endpoint, route => route.fulfill({ json: ['agents'] }))
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(help(page)).toHaveCount(0)
})

test('late saves cannot hide help for a different account', async ({ page }) => {
  let finish
  await page.route(`${endpoint}/*`, route => new Promise(resolve => {
    finish = async () => { await route.fulfill({ status: 204 }); resolve() }
  }))
  await mount(page, component, { props })
  await page.getByRole('button', { name: 'Got it', exact: true }).click()
  await expect.poll(() => Boolean(finish)).toBe(true)
  await page.evaluate(() => { window.testApp.auth.user = { ...window.testApp.auth.user, id: 2 } })
  await finish()
  await expect(help(page)).toContainText(props.helpText)
  await expect(page.getByRole('button', { name: 'Got it', exact: true })).toBeEnabled()
  await page.evaluate(() => { window.testApp.auth.user = null })
  await expect(help(page)).toHaveCount(0)
})

test('late reads from another account do not restore or dismiss the current help', async ({ page }) => {
  let finish
  let calls = 0
  await page.route(endpoint, route => {
    if (++calls > 1) return route.fulfill({ json: [] })
    return new Promise(resolve => {
      finish = async () => { await route.fulfill({ json: ['agents'] }); resolve() }
    })
  })
  await mount(page, component, { props })
  await expect.poll(() => Boolean(finish)).toBe(true)
  await page.evaluate(() => { window.testApp.auth.user = { ...window.testApp.auth.user, id: 2 } })
  await expect(help(page)).toBeVisible()
  await finish()
  await expect(help(page)).toContainText(props.helpText)
})

test('help remains usable in French on a narrow screen in both themes', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 })
  await page.route(`${endpoint}/*`, route => route.fulfill({ status: 204 }))
  await mount(page, component, { props, locale: 'fr' })
  await page.evaluate(async () => {
    const { default: messages } = await import('/app/tools/i18n.ts')
    await window.testApp.setProps({ helpKey: 'tools', helpText: messages.fr.contextHelpPages.tools })
  })
  const banner = page.getByRole('complementary', { name: 'Aide contextuelle' })
  await expect(banner).toContainText('Model Context Protocol')
  await page.screenshot({ path: test.info().outputPath('help-mobile-light.png'), fullPage: true })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: test.info().outputPath('help-mobile-dark.png'), fullPage: true })
  await page.getByRole('button', { name: 'J’ai compris', exact: true }).click()
  await expect(banner).toHaveCount(0)
})
