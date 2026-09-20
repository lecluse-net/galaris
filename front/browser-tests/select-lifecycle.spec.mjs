import { test, expect, mount } from './fixtures.mjs'

const choices = {
  agent: {
    component: 'app/agent/components/AgentSelect.vue', pattern: '**/api/agents/selection?*',
    props: { loadAgents: false, options: [
      { value: 7, label: 'Initial choice' }, { value: 8, label: 'Obsolete choice' }, { value: 9, label: 'Current choice' },
    ] },
    response: (id, label) => [{ id, label, has_avatar: false }],
  },
  topic: {
    component: 'app/topic/components/TopicSelect.vue', pattern: '**/api/topics?*', props: {},
    response: (id, label) => ({ items: [{ id: String(id), title: label }], total: 1 }),
  },
}

for (const [kind, contract] of Object.entries(choices)) {
  for (const width of [390, 1440]) {
    for (const failure of [false, true]) {
      test(`${kind} reopening at ${width}px ignores a previous popup's late ${failure ? 'failure' : 'success'}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 })
        let release
        const pending = new Promise(resolve => { release = resolve })
        let requests = 0
        await page.route(contract.pattern, async route => {
          const current = ++requests
          if (current === 2) await pending
          await route.fulfill(current === 2 && failure
            ? { status: 503, json: { detail: 'Obsolete popup failure' } }
            : { json: contract.response(current === 1 ? 7 : current === 2 ? 8 : 9,
              current === 1 ? 'Initial choice' : current === 2 ? 'Obsolete choice' : 'Current choice') })
        })
        await mount(page, contract.component, { props: { ...contract.props, modelValue: null, label: 'Choice' } })
        const input = page.getByRole('combobox', { name: 'Choice', exact: true })
        await input.click()
        await expect(page.getByRole('option', { name: 'Initial choice', exact: true })).toBeVisible()
        await page.keyboard.press('Escape')
        await expect(page.getByRole('listbox')).toHaveCount(0)
        try {
          await input.click()
          await expect.poll(() => requests).toBe(2)
          await page.keyboard.press('Escape')
          await input.click()
          await expect(page.getByRole('option', { name: 'Current choice', exact: true })).toBeVisible()
          const response = page.waitForResponse(contract.pattern)
          release()
          await response
          // Flush the asynchronous response handler before asserting preserved choices.
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
          await expect(page.getByRole('option', { name: 'Obsolete choice', exact: true })).toHaveCount(0)
          await expect(page.getByText('Obsolete popup failure', { exact: false })).toHaveCount(0)
          await page.getByRole('option', { name: 'Current choice', exact: true }).click()
          await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value))
            .toBe(kind === 'agent' ? 9 : '9')
        } finally { release() }
      })
    }
  }
}

for (const status of [403, 500, 503]) {
  test(`agent selection distinguishes permission revocation from transport failure ${status}`, async ({ page }) => {
    let unavailable = false
    const contract = choices.agent
    await page.route(contract.pattern, route => route.fulfill(unavailable
      ? { status, json: { detail: 'Selection temporarily unavailable' } }
      : { json: contract.response(7, 'Initial choice') }))
    await mount(page, contract.component, { props: { ...contract.props, modelValue: 7, label: 'Choice' } })
    await expect(page.getByText('Initial choice', { exact: true })).toBeVisible()
    unavailable = true
    await page.getByRole('combobox').click()
    await expect(page.getByText('Selection temporarily unavailable', { exact: false })).toBeVisible()
    const changes = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').map(event => event.value))
    expect(changes).toEqual(status === 403 ? [null] : [])
    await page.keyboard.press('Escape')
    unavailable = false
    await page.getByRole('combobox').click()
    await page.getByRole('option', { name: 'Initial choice', exact: true }).click()
    await expect(page.getByText('Selection temporarily unavailable', { exact: false })).toHaveCount(0)
    await expect(page.getByRole('listbox')).toHaveCount(0)
    await expect(page.getByText('Initial choice', { exact: true })).toBeVisible()
  })
}

test('a saved topic changed by the parent keeps its newest label when the previous lookup finishes', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/topics/*', async route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)
    if (id === 'old') await pending
    await route.fulfill({ json: { id, title: `${id} saved topic` } })
  })
  const requested = page.waitForRequest('**/api/topics/old')
  await mount(page, choices.topic.component, { props: { modelValue: 'old', label: 'Choice' } })
  await requested
  try {
    await page.evaluate(() => window.testApp.setProps({ modelValue: 'new' }))
    await expect(page.getByText('new saved topic', { exact: true })).toBeVisible()
    const response = page.waitForResponse('**/api/topics/old')
    release()
    await response
    await expect(page.getByText('new saved topic', { exact: true })).toBeVisible()
    await expect(page.getByText('old saved topic', { exact: true })).toHaveCount(0)
    expect(await page.evaluate(() => window.testApp.events)).toEqual([])
  } finally { release() }
})

test('agent choices load on first opening even while another agent-store resource is loading', async ({ page }) => {
  let requests = 0
  await page.route('**/api/agents?*', route => {
    requests += 1
    return route.fulfill({ json: [{ id: 7, first_name: 'Alice', last_name: 'Example' }] })
  })
  await mount(page, choices.agent.component, { props: {
    options: [{ value: 7, label: 'Alice Example' }], modelValue: null, label: 'Choice',
  } })
  await page.evaluate(() => window.testApp.patchStore('app/agent/stores/agentStore.ts', 'useAgentStore', { loading: true }))
  await page.getByRole('combobox', { name: 'Choice', exact: true }).click()
  await expect(page.getByRole('option', { name: 'Alice Example', exact: true })).toBeVisible()
  expect(requests).toBe(1)
})
