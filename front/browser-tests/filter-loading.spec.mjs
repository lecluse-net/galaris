import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent } from './data.mjs'

for (const kind of ['agent', 'topic']) {
  test(`${kind} choices are requested only when the empty filter is opened and can recover`, async ({ page }) => {
    const requests = []
    let unavailable = true
    if (kind === 'agent') await page.route('**/api/agents?*', route => {
      requests.push(route.request().url())
      return route.fulfill({ json: [agent] })
    })
    const pattern = kind === 'agent' ? '**/api/agents/selection?*' : '**/api/topics?*'
    const choices = kind === 'agent'
      ? [{ id: 7, label: 'Recovered choice', has_avatar: false }]
      : { items: [{ id: 'recovered', title: 'Recovered choice' }], total: 1 }
    await page.route(pattern, route => {
      requests.push(route.request().url())
      return route.fulfill(unavailable
        ? { status: 503, json: { detail: 'Lookup unavailable' } }
        : { json: choices })
    })
    await mount(page, `app/${kind}/components/${kind === 'agent' ? 'Agent' : 'Topic'}Select.vue`, {
      props: { modelValue: null, label: 'Filter', ...(kind === 'agent' ? {
        options: [{ value: 7, label: 'Recovered choice' }],
      } : {}) },
    })
    const input = page.getByRole('combobox', { name: 'Filter', exact: true })
    await expect(input).toBeVisible()
    expect(requests).toEqual([])
    await expect(page.getByText('Lookup unavailable', { exact: false })).toHaveCount(0)
    await input.click()
    await expect(page.getByText('Lookup unavailable', { exact: false })).toBeVisible()
    await page.keyboard.press('Escape')
    unavailable = false
    await input.click()
    await page.getByRole('option', { name: 'Recovered choice', exact: true }).click()
    await expect(page.getByText('Lookup unavailable', { exact: false })).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe(kind === 'agent' ? 7 : 'recovered')
  })
}

test('a selected topic resolves its label without loading the catalogue', async ({ page }) => {
  const catalogues = []
  await page.route('**/api/topics?*', route => {
    catalogues.push(route.request().url())
    return route.fulfill({ status: 503, json: { detail: 'Catalogue unavailable' } })
  })
  await page.route('**/api/topics/chosen', route => route.fulfill({ json: { id: 'chosen', title: 'Chosen topic' } }))
  await mount(page, 'app/topic/components/TopicSelect.vue', { props: { modelValue: 'chosen', label: 'Topic' } })
  await expect(page.getByText('Chosen topic', { exact: true })).toBeVisible()
  expect(catalogues).toEqual([])
  await expect(page.getByText('Catalogue unavailable', { exact: false })).toHaveCount(0)
})

test('a stale human search failure cannot abort the next search', async ({ page }) => {
  let releaseOld, releaseNew
  const old = new Promise(resolve => { releaseOld = resolve })
  const next = new Promise(resolve => { releaseNew = resolve })
  await page.route('**/api/teams/humans?*', async route => {
    const search = new URL(route.request().url()).searchParams.get('search')
    if (search === 'Old') {
      await old
      await route.fulfill({ status: 503, json: { detail: 'Obsolete failure' } })
    } else {
      if (search === 'New') await next
      await route.fulfill({ json: search === 'New' ? [{ id: 2, label: 'New human', active: true, avatar_url: null }] : [] })
    }
  })
  await mount(page, 'core/team/components/TeamEditor.vue', {
    privileges: ['TEAM_ACCESS', 'TEAM_EDIT', 'TEAM_MEMBERS_EDIT'], props: { contributions: [] },
  })
  const input = page.getByRole('combobox', { name: 'Add a human', exact: true })
  try {
    const oldRequest = page.waitForRequest('**/api/teams/humans?search=Old')
    await input.fill('Old')
    await oldRequest
    const newRequest = page.waitForRequest('**/api/teams/humans?search=New')
    await input.fill('New')
    await newRequest
    const oldResponse = page.waitForResponse('**/api/teams/humans?search=Old')
    releaseOld()
    await oldResponse
    // Let the old response's error handler run before the new response arrives.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    releaseNew()
    await page.getByRole('option', { name: 'New human', exact: true }).click()
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.getByText('New human', { exact: true })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally { releaseOld(); releaseNew() }
})

test('a topic request superseded by a session change is not a lookup error', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/topics?*', async route => {
    await pending
    await route.fulfill({ json: { items: [], total: 0 } })
  })
  await mount(page, 'app/topic/components/TopicSelect.vue', { props: { modelValue: null, label: 'Topic' } })
  const request = page.waitForRequest('**/api/topics?*')
  await page.getByRole('combobox').click()
  await request
  try {
    await page.evaluate(async () => (await import('/core/api.ts')).invalidateSessionRequests())
    const response = page.waitForResponse('**/api/topics?*')
    release()
    await response
    await expect(page.locator('.q-field--loading')).toHaveCount(0)
    await expect(page.locator('.q-field--error')).toHaveCount(0)
  } finally { release() }
})

test('user assignment search reports a real failure and recovers without an unhandled rejection', async ({ page }) => {
  await jsonRoute(page, '**/api/authorize/assignments?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/authorize/roles', [])
  await page.route('**/api/auth/users?*', route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }))
  await mount(page, 'core/authorize/components/AssignmentManager.vue', { privileges: ['MANAGE_ASSIGNMENT'] })
  await page.getByRole('button', { name: 'New Assignment', exact: true }).click()
  const input = page.getByRole('combobox', { name: 'User *', exact: true })
  await input.fill('Alice')
  await expect(page.locator('.q-field--error')).toBeVisible()
  await jsonRoute(page, '**/api/auth/users?*', [{ id: 2, email: 'alice@example.invalid', display_name: 'Alice' }])
  await input.fill('alice@example')
  await page.getByRole('option').filter({ hasText: 'alice@example.invalid' }).click()
  await expect(page.locator('.q-field--error')).toHaveCount(0)
})

test('memory filter options ignore failures from the previously selected agent', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let requested = false
  await jsonRoute(page, '**/api/agents?*', [agent, { ...agent, id: 8, first_name: 'Bob' }])
  await jsonRoute(page, '**/api/agents/selection?*', [
    { id: 7, label: 'Alice Example', has_avatar: false }, { id: 8, label: 'Bob Example', has_avatar: false },
  ])
  await jsonRoute(page, '**/api/memory/browse', { hits: [], total: 0, has_more: false })
  await jsonRoute(page, '**/api/memory/findings?*', [])
  await page.route('**/api/memory/filter-options?*', async route => {
    if (new URL(route.request().url()).searchParams.get('agent_id') === '7') {
      requested = true
      await pending
      await route.fulfill({ status: 503, json: { detail: 'Obsolete agent filter failure' } })
    } else await route.fulfill({ json: { topics: [], contacts: [] } })
  })
  await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
  try {
    await expect.poll(() => requested).toBe(true)
    await page.getByRole('combobox', { name: 'Agent', exact: true }).click()
    await page.getByRole('option').filter({ hasText: 'Bob Example' }).click()
    await expect(page.getByRole('combobox', { name: 'Agent', exact: true })).toHaveValue('Bob Example')
    const response = page.waitForResponse(response => response.url().includes('/memory/filter-options?') && response.status() === 503)
    release()
    await response
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(page.getByText('Obsolete agent filter failure', { exact: false })).toHaveCount(0)
  } finally { release() }
})
