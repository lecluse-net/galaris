import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent } from './data.mjs'

async function agentFixtures(page) {
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'hermes', is_owner: true }])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await jsonRoute(page, '**/api/agents/groups?*', [])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'hermes', label: 'Hermes', manages_runtime: true }])
  await jsonRoute(page, '**/api/harnesses/agents/7', { containerized: true })
}

test('built-in titles follow the locale and remain keys until renamed', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/harnesses/agents/7/status', { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: [], available_actions: [], last_error: null })
  await jsonRoute(page, '**/api/agents/titles?*', [
    { id: 1, label: 'agent_titles.ms', gender: 'F' },
    { id: 2, label: 'agent_titles.mr', gender: 'M' },
    { id: 3, label: 'common.save', gender: 'M' },
  ])
  const saves = []
  await page.route('**/api/agents/titles/1', route => {
    const data = route.request().postDataJSON()
    saves.push(data)
    return route.fulfill({ json: { id: 1, ...data } })
  })
  const locale = language => page.evaluate(async language => {
    const { setLocale } = await import('/core/i18n/index.ts')
    setLocale(language)
  }, language)
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT', 'AGENT_MANAGE_ALL'] })
  await page.getByRole('tab', { name: 'Titles' }).click()
  await expect(page.getByRole('cell', { name: 'Ms', exact: true })).toBeVisible()
  await locale('fr')
  await expect(page.getByRole('cell', { name: 'Madame', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Monsieur', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'common.save', exact: true })).toBeVisible()
  await page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'Madame', exact: true }) }).getByRole('button').first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('textbox')).toHaveValue('Madame')
  await locale('en')
  await expect(dialog.getByRole('textbox')).toHaveValue('Ms')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves).toEqual([{ label: 'agent_titles.ms', gender: 'F' }])
  await page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'Ms', exact: true }) }).getByRole('button').first().click()
  await expect(dialog.getByRole('textbox')).toHaveValue('Ms')
  await dialog.getByRole('textbox').fill('Doctor')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves.at(-1)).toEqual({ label: 'Doctor', gender: 'F' })
  await locale('zh')
  await expect(page.getByRole('cell', { name: 'Doctor', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '先生', exact: true })).toBeVisible()
  await expect(page.getByText('agent_titles.', { exact: false })).toHaveCount(0)
})

test('agent page reports an unavailable manager and clears it after successful polling', async ({ page }) => {
  await page.clock.install()
  await agentFixtures(page)
  let healthy = false
  await page.route('**/api/harnesses/agents/7/status', route => route.fulfill(healthy
    ? { json: { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: ['restart', 'stop'], available_actions: ['restart', 'stop'], last_error: null } }
    : { status: 503, json: { detail: 'Manager unavailable' } }))
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
  const warning = page.locator('.q-banner').filter({ hasText: /manager/i })
  await expect(warning).toBeVisible()
  healthy = true
  await page.clock.fastForward(5100)
  await expect(warning).toHaveCount(0)
  await expect(page.getByText('Alice Example', { exact: true }).first()).toBeVisible()
})

test('agent runtime action calls restart once and prevents duplicate submissions', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/harnesses/agents/7/status', { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: ['restart', 'stop'], available_actions: ['restart', 'stop'], last_error: null })
  let release
  const pending = new Promise(resolve => { release = resolve })
  const actions = []
  await page.route('**/api/harnesses/agents/7/actions/restart', async route => {
    actions.push(route.request().method())
    await pending
    await route.fulfill({ json: { status: 'queued', output: '' } })
  })
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
  const restart = page.getByRole('button', { name: 'Restart', exact: true })
  try {
    await restart.click()
    await expect.poll(() => actions).toEqual(['POST'])
    await restart.click({ force: true })
    expect(actions).toEqual(['POST'])
  } finally { release() }
})
