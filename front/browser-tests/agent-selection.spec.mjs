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
const research = { id: 20, name: 'Research', order: 1 }, support = { id: 10, name: 'Support', order: 2 }
const groupedAgents = [
  { ...selections[0], teams: [support, research] },
  { ...selections[1], teams: [support] },
  { id: 9, label: 'Charlie Libre', has_avatar: false, teams: [] },
]
const groupedChoices = [...options, { value: 9, label: 'Charlie Libre' }, { value: 10, label: 'Unauthorized' }]

async function fixtures(page) {
  await jsonRoute(page, '**/api/agents?*', agents)
  await jsonRoute(page, '**/api/agents/selection?*', selections)
}

async function choose(page, label) {
  await page.getByRole('combobox').first().click()
  await page.getByRole('option', { name: label, exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
}

for (const width of [390, 1440]) {
  for (const dark of [false, true]) {
    test(`team sections keep duplicate memberships selectable and refresh on reopening (${width}px, dark=${dark})`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 })
      await jsonRoute(page, '**/api/agents/selection?*', groupedAgents)
      await mount(page, harness, { dark, props: { page: 'grouped', options: groupedChoices, modelValue: 8 } })
      const input = page.getByRole('combobox').first()
      await input.click()
      await expect.poll(() => page.getByRole('option').evaluateAll(elements => elements.map(element => element.getAttribute('aria-label'))))
        .toEqual(['All agents', 'Alice Arbre', 'Alice Arbre', 'Bob Exemple', 'Charlie Libre'])
      await expect(page.getByText('Research', { exact: true })).toBeVisible()
      await expect(page.getByText('Support', { exact: true })).toBeVisible()
      await expect(page.getByText('No team', { exact: true })).toBeVisible()
      await expect(page.getByRole('option', { name: 'Unauthorized', exact: true })).toHaveCount(0)
      await testInfo.attach('team-sections', { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
      await page.getByRole('option', { name: 'Alice Arbre', exact: true }).nth(1).click()
      await expect(page.getByRole('listbox')).toHaveCount(0)
      await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe(7)
      await choose(page, 'All agents')
      // Keyboard selection now starts in the popup search and is covered below.
      await jsonRoute(page, '**/api/agents/selection?*', groupedAgents.map(agent => ({ ...agent, teams: [] })))
      await input.click()
      await expect(page.getByText('Research', { exact: true })).toHaveCount(0)
      await expect(page.getByRole('option', { name: 'Alice Arbre', exact: true })).toHaveCount(1)
      await page.keyboard.press('Escape')
    })
  }
}

test('selecting the same agent through two team sections toggles one membership without duplicate chips', async ({ page }) => {
  await jsonRoute(page, '**/api/agents/selection?scope=teams', groupedAgents)
  await mount(page, harness, { props: { page: 'multiple', options: groupedChoices.filter(option => option.value !== null) } })
  await page.getByRole('combobox').click()
  const alice = page.getByRole('option', { name: 'Alice Arbre', exact: true })
  await expect(alice).toHaveCount(2)
  await alice.first().click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toEqual([7])
  await expect(alice.nth(1)).toHaveAttribute('aria-selected', 'true')
  await alice.nth(1).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toEqual([])
  await page.keyboard.press('Escape')
})

test('process agent choices retain their domain options and default choice when grouped', async ({ page }) => {
  await jsonRoute(page, '**/api/agents/selection?scope=management', groupedAgents)
  await mount(page, 'app/process/components/ProcessAgentSelect.vue', { props: {
    modelValue: null, options: [{ id: null, label: 'Launching agent' },
      ...groupedAgents.map(agent => ({ id: agent.id, label: agent.label }))],
  } })
  await page.getByRole('combobox').click()
  await expect(page.getByRole('option', { name: 'Alice Arbre', exact: true })).toHaveCount(2)
  await page.getByRole('option', { name: 'Alice Arbre', exact: true }).last().click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe(7)
  await page.getByRole('combobox').click()
  await page.getByRole('option', { name: 'Launching agent', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBeNull()
})

for (const width of [390, 1440]) {
test(`agent names can be searched from the popup without case or accents or changing the selection (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await jsonRoute(page, '**/api/agents/selection?*', groupedAgents)
  const choices = groupedChoices.map(option => option.value === 9 ? { ...option, label: 'Élodie Exemple' } : option)
  await mount(page, harness, { props: { page: 'search', options: choices, modelValue: 8 } })
  const selector = page.getByRole('combobox').first()
  await expect(page.getByRole('textbox', { name: 'Search agents by name', exact: true })).toHaveCount(0)
  await selector.click()
  const input = page.getByRole('textbox', { name: 'Search agents by name', exact: true })
  await expect(input).toBeFocused()
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  expect(await page.evaluate(() => window.testApp.events)).toEqual([])
  await input.fill('aRbRe')
  await expect(page.getByRole('option', { name: 'Alice Arbre', exact: true })).toHaveCount(2)
  await expect(page.getByRole('option', { name: 'Bob Exemple', exact: true })).toHaveCount(0)
  await testInfo.attach('agent-popup-search', { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
  await input.fill('unmatched name')
  await expect(page.getByRole('option')).toHaveCount(0)
  await expect(page.getByText('No agents match this search.', { exact: true })).toBeVisible()
  await expect(input).toBeFocused()
  expect(await page.evaluate(() => window.testApp.events)).toEqual([])
  await input.fill('elodie')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe(9)
  await expect(input).toHaveCount(0)
  await selector.click()
  await expect(input).toHaveValue('')
  await expect(page.getByRole('option', { name: 'Bob Exemple', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
})
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
  await mount(page, harness, { route: '/memory', props: { page: 'memory' }, privileges: ['MEMORY_ACCESS', 'CONTACT_ACCESS'] })
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
