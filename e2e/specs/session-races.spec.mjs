import { test, expect } from '@playwright/test'

async function signIn(page, fixture) {
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
}

function observeSubscriptions(page) {
  let events = []
  let upgraded = false
  page.on('websocket', socket => {
    if (!socket.url().includes('/socket.io/')) return
    socket.on('framesent', ({ payload }) => {
      const frame = String(payload)
      if (frame === '5') upgraded = true
      if (!frame.startsWith('42')) return
      const [name, data] = JSON.parse(frame.slice(2))
      if (name === 'events.subscribe') events = data.events
    })
  })
  const current = () => events
  current.ready = () => upgraded
  return current
}

test('page subscriptions stop on navigation while global message notifications remain active', async ({ page, request }) => {
  const subscriptions = observeSubscriptions(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  await signIn(page, fixture)
  await expect.poll(subscriptions.ready).toBe(true)
  await page.locator('a[href="/params"]').first().click()
  await expect.poll(subscriptions).toEqual(['chat.message'])
  const consumers = [
    { path: '/goal', event: 'goal.update' },
    { path: '/memory/documents', event: 'memory.update' },
    { path: '/task', tab: 'Tâches', event: 'task.update' },
    { path: '/task', tab: 'Activité LLM', event: 'llm_call.update' },
    { path: '/task', tab: 'Processus', event: 'process_run.update' },
    { path: '/task', tab: 'Appels téléphoniques', event: 'voice_conversation.update' },
  ]
  for (const { path, tab, event } of consumers) {
    for (let visit = 0; visit < 2; visit++) {
      await page.locator(`a[href="${path}"]`).first().click()
      if (tab) await page.getByRole('tab', { name: tab, exact: true }).click()
      await expect.poll(subscriptions).toContain(event)
      await page.locator('a[href="/params"]').first().click()
      await expect.poll(subscriptions).toEqual(['chat.message'])
    }
  }
})

test('leaving goals during its initial load does not leave an orphan live subscription', async ({ page, request }) => {
  const subscriptions = observeSubscriptions(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  await signIn(page, fixture)
  await expect.poll(subscriptions.ready).toBe(true)
  await page.locator('a[href="/params"]').first().click()
  await expect.poll(subscriptions).toEqual(['chat.message'])
  let release
  const gate = new Promise(resolve => { release = resolve })
  let intercepted
  const ready = new Promise(resolve => { intercepted = resolve })
  let completed
  const fulfilled = new Promise(resolve => { completed = resolve })
  await page.route('**/api/goals?*', async route => {
    const response = await route.fetch()
    intercepted()
    await gate
    await route.fulfill({ response })
    completed()
  }, { times: 1 })
  try {
    await page.locator('a[href="/goal"]').first().click()
    await ready
    await expect.poll(subscriptions).toContain('goal.update')
    await page.locator('a[href="/params"]').first().click()
    release()
    await fulfilled
    await expect.poll(subscriptions).toEqual(['chat.message'])
  } finally { release() }
})

test('leaving a loading document editor does not restore its subscription after navigation', async ({ page, request }) => {
  const subscriptions = observeSubscriptions(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  await signIn(page, fixture)
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const created = await request.post('/api/memory/items', {
    headers: { Authorization: `Bearer ${token}`, 'X-Editorial-Profile-Version': '1' },
    data: { owner_agent_id: fixture.agent_id, title: `Pending editor ${fixture.agent_id}`,
      node_kind: 'document', memory_type: 'working', media_type: 'text/html', payload: { text: '<p>Existing content</p>' } },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const document = await created.json()
  let release
  const gate = new Promise(resolve => { release = resolve })
  let intercepted
  const ready = new Promise(resolve => { intercepted = resolve })
  const isDocument = url => url.pathname === `/api/memory/items/${document.id}`
  await page.route(isDocument, async route => {
    const response = await route.fetch()
    intercepted()
    await gate
    await route.fulfill({ response })
  }, { times: 1 })
  try {
    await page.goto(`/memory/documents?document_id=${document.id}`)
    await ready
    await page.locator('a[href="/params"]').first().click()
    const response = page.waitForResponse(response => isDocument(new URL(response.url())))
    release()
    await (await response).finished()
    // Let the resolved document load and Vue's next render complete before
    // inspecting the absence of an unwanted late subscription.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)))
    await expect.poll(subscriptions).toEqual(['chat.message'])
  } finally { release() }
})

test('Dream live monitoring follows page navigation without reconnecting the socket', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  const frames = []
  let connections = 0
  page.on('websocket', socket => {
    if (!socket.url().includes('/socket.io/')) return
    connections++
    socket.on('framesent', ({ payload }) => frames.push(String(payload)))
  })
  await signIn(page, fixture)
  // Wait for Engine.IO's transport upgrade, so page subscriptions travel over
  // the observed WebSocket instead of the initial HTTP polling transport.
  await expect.poll(() => frames.includes('5')).toBe(true)
  const initialConnections = connections
  for (const [path, room] of [['/dream', 'DreamRoom:monitoring'], ['/goal', null], ['/dream', 'DreamRoom:monitoring']]) {
    frames.length = 0
    await page.locator(`a[href="${path}"]`).first().click()
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect.poll(() => frames.includes(`42${JSON.stringify(['room.display', { room }])}`)).toBe(true)
    await expect(page.locator('.q-page').first()).toBeVisible()
  }
  expect(connections).toBe(initialConnections)
})

test('a failed identity lookup keeps login open with its diagnostic and allows retry', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  await page.goto('/user/login')
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Identity temporarily unavailable' }),
  }), { times: 1 })
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page.getByText(/Identity temporarily unavailable/)).toBeVisible()
  await expect(page).toHaveURL(/\/user\/login$/)
  await expect(page.locator('.user-menu-wrapper')).toHaveCount(0)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
  await expect(page).toHaveURL(/\/$/)
})

test('a delayed identity response cannot restore account A after account B signs in from another tab', async ({ page, context, request }) => {
  const a = await (await request.post('/api/__test/seed')).json()
  const b = await (await request.post('/api/__test/seed')).json()
  await signIn(page, a)
  const other = await context.newPage()
  await other.goto('/')
  await expect(other.locator('.user-menu-wrapper').first()).toBeVisible()
  let release
  const gate = new Promise(resolve => { release = resolve })
  let intercepted
  const ready = new Promise(resolve => { intercepted = resolve })
  await page.route('**/api/auth/me', async route => {
    const response = await route.fetch()
    intercepted()
    await gate
    await route.fulfill({ response })
  }, { times: 1 })
  try {
    await page.reload({ waitUntil: 'domcontentloaded' })
    await ready
    await other.locator('.user-menu-wrapper').first().click()
    await other.locator('.user-menu-logout').click()
    await other.getByRole('dialog').getByRole('button').last().click()
    await expect(other.locator('.user-menu-wrapper')).toHaveCount(0)
    await signIn(other, b)
    release()
    for (const tab of [page, other]) {
      await expect.poll(() => tab.evaluate(() => JSON.parse(localStorage.getItem('user') || '{}').email)).toBe(b.email)
      await expect(tab.locator('.user-menu-wrapper').first()).toBeVisible()
    }
    // The real shared refresh cookie must also belong to B after both reloads.
    for (const tab of [page, other]) {
      await tab.reload()
      await expect.poll(() => tab.evaluate(() => JSON.parse(localStorage.getItem('user') || '{}').email)).toBe(b.email)
    }
  } finally { release(); await other.close() }
})

test('goals, processes, documents and settings load their authorized production pages', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  const failures = []
  page.on('pageerror', error => failures.push(error.message))
  await signIn(page, fixture)
  for (const path of ['/goal', '/process', '/memory/documents', '/memory', '/params']) {
    // Exercise the application's navigation, preserving the document and its
    // active requests as a real menu click does.
    await page.locator(`a[href="${path}"]`).first().click()
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
    await expect(page.locator('.q-page').first()).toBeVisible()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    await expect(page.locator('.q-page').first()).not.toBeEmpty()
  }
  // Verify completion, not merely an empty page shell while auth is restoring.
  const preview = await page.evaluate(async () => {
    const response = await fetch('/api/processes/retention/preview', { headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` } })
    return { status: response.status, data: await response.json() }
  })
  expect(preview.status).toBe(200)
  expect(Object.keys(preview.data).sort()).toEqual(['events', 'output', 'raw_snapshot', 'runs'])
  expect(failures).toEqual([])
})

for (const width of [390, 1440]) {
  test(`memory and documents show existing data on their first direct load at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 1000 })
    const fixture = await (await request.post('/api/__test/seed')).json()
    await signIn(page, fixture)
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    for (const nodeKind of ['memory', 'document']) {
      const title = `First load ${nodeKind} ${fixture.agent_id}`
      const created = await request.post('/api/memory/items', {
        headers: { Authorization: `Bearer ${token}`, 'X-Editorial-Profile-Version': '1' },
        data: { owner_agent_id: fixture.agent_id, title, node_kind: nodeKind, memory_type: 'working',
          media_type: 'text/html', payload: { text: '<p>Existing content must load without reloading the page.</p>' } },
      })
      expect(created.ok(), await created.text()).toBeTruthy()
      let release
      const pending = new Promise(resolve => { release = resolve })
      await page.route('**/api/auth/refresh', async route => {
        await pending
        await route.continue()
      }, { times: 1 })
      try {
        await page.goto(nodeKind === 'memory' ? `/memory?agent=${fixture.agent_id}` : '/memory/documents', { waitUntil: 'domcontentloaded' })
        release()
        await expect(page.getByText(title, { exact: true }).first()).toBeVisible()
      } finally { release() }
    }
  })
}
