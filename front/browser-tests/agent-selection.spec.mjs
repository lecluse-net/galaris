import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent } from './data.mjs'

const harness = 'test-support/browser/AgentSelectionHarness.vue'
const agents = [
  { ...agent, code: 'zzz', first_name: 'Alice', last_name: 'Arbre' },
  { ...agent, id: 8, code: 'aaa', first_name: 'Bob', last_name: 'Exemple' },
]
const options = [{ value: null, label: 'All agents' }, ...agents.map(agent => ({
  value: agent.id, label: `${agent.first_name} ${agent.last_name}`,
}))]
const selections = agents.map(agent => ({ id: agent.id, label: `${agent.first_name} ${agent.last_name}`, has_avatar: false }))

async function fixtures(page) {
  await jsonRoute(page, '**/api/agents?*', agents)
  await jsonRoute(page, '**/api/agents/selection?*', selections)
}

async function choose(page, label) {
  await page.getByRole('combobox').first().click()
  await page.getByRole('option', { name: label, exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
}

test('Memory and Contacts reuse the last chosen agent when navigating between pages', async ({ page }) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/memory/temporal/defaults', { timezone: 'Europe/Paris', lookahead_hours: 24 })
  await jsonRoute(page, '**/api/memory/filter-options?*', { topics: [], contacts: [] })
  await jsonRoute(page, '**/api/memory/findings?*', [])
  const memoryAgents = [], contactAgents = []
  await page.route('**/api/memory/browse', route => {
    memoryAgents.push(route.request().postDataJSON().agent_id)
    return route.fulfill({ json: { hits: [], total: 0, has_more: false } })
  })
  await page.route('**/api/contacts?*', route => {
    contactAgents.push(Number(new URL(route.request().url()).searchParams.get('agent_id')))
    return route.fulfill({ json: { items: [], total: 0 } })
  })
  await mount(page, harness, { route: '/memory', props: { page: 'memory' } })
  await expect.poll(() => memoryAgents.at(-1)).toBe(7)
  await choose(page, 'Bob Exemple')
  await expect.poll(() => memoryAgents.at(-1)).toBe(8)
  await page.evaluate(() => window.testApp.setProps({ page: 'contacts' }))
  await expect.poll(() => contactAgents.at(-1)).toBe(8)
  await expect(page.getByText('Bob Exemple', { exact: true })).toBeVisible()
  await choose(page, 'Alice Arbre')
  await expect.poll(() => contactAgents.at(-1)).toBe(7)
  await page.evaluate(() => window.testApp.setProps({ page: 'memory' }))
  await expect.poll(() => memoryAgents.at(-1)).toBe(7)
  await expect(page.getByText('Alice Arbre', { exact: true })).toBeVisible()
})

test('selectors remember only non-null choices and preserve an explicit initial agent', async ({ page }) => {
  await fixtures(page)
  await mount(page, harness, { props: { page: 'first', options } })
  await choose(page, 'Bob Exemple')
  await choose(page, 'All agents')
  await expect(page.getByText('All agents', { exact: true })).toBeVisible()
  await page.getByRole('combobox').click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(page.getByText('All agents', { exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ page: 'second', modelValue: null }))
  await expect(page.getByText('Bob Exemple', { exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ page: 'third', modelValue: 7 }))
  await expect(page.getByText('Alice Arbre', { exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ page: 'fourth', modelValue: null }))
  await expect(page.getByText('Bob Exemple', { exact: true })).toBeVisible()
})

for (const unavailable of ['unauthorized', 'absent', 'disabled']) {
  test(`a remembered agent is not restored when ${unavailable} in the next selector`, async ({ page }) => {
    await fixtures(page)
    await mount(page, harness, { props: { page: 'first', options } })
    await choose(page, 'Bob Exemple')
    if (unavailable === 'unauthorized') await jsonRoute(page, '**/api/agents/selection?*', selections.slice(0, 1))
    await page.evaluate(({ options, unavailable }) => window.testApp.setProps({
      page: 'second', modelValue: null,
      options: unavailable === 'absent' ? options.filter(option => option.value !== 8)
        : options.map(option => ({ ...option, disable: unavailable === 'disabled' && option.value === 8 })),
    }), { options, unavailable })
    await expect(page.getByText('All agents', { exact: true })).toBeVisible()
    await page.getByRole('combobox').click()
    await expect(page.getByRole('option', { name: 'Alice Arbre', exact: true })).toBeVisible()
    expect(await page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe(8)
    await page.keyboard.press('Escape')
  })
}

test('token renewal keeps the remembered agent, while logout clears it', async ({ page }) => {
  await fixtures(page)
  await mount(page, harness, { props: { page: 'first', options } })
  await choose(page, 'Bob Exemple')
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'renewed' })))
  await page.evaluate(() => window.testApp.setProps({ page: 'renewed', modelValue: null }))
  await expect(page.getByText('Bob Exemple', { exact: true })).toBeVisible()
  await page.evaluate(async () => {
    window.testApp.events.length = 0
    window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: null }))
    await window.testApp.setProps({ page: 'logged-out', modelValue: null })
  })
  await expect(page.getByText('All agents', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.testApp.events)).toEqual([])
})

test('a remembered default waits for options loaded after authorization', async ({ page }) => {
  await fixtures(page)
  await mount(page, harness, { props: { page: 'first', options } })
  await choose(page, 'Bob Exemple')
  const response = page.waitForResponse('**/api/agents/selection?*')
  await page.evaluate(() => window.testApp.setProps({ page: 'pending-options', modelValue: null, options: [] }))
  await response
  await page.evaluate(options => window.testApp.setProps({ options }), options)
  await expect(page.getByText('Bob Exemple', { exact: true })).toBeVisible()
})

test('changing the authenticated session clears the shared default', async ({ page }) => {
  await fixtures(page)
  await mount(page, harness, { props: { page: 'first', options } })
  await choose(page, 'Bob Exemple')
  await page.evaluate(async () => {
    localStorage.setItem('galaris:session-generation', 'different-user')
    window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'different-token' }))
    await window.testApp.setProps({ page: 'different-user', modelValue: null })
  })
  await expect(page.getByText('All agents', { exact: true })).toBeVisible()
})
