import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const selected = page => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)

for (const form of ['preferences', 'composer', 'assignment']) {
  test(`the ${form} form uses the created topic in its submitted value`, async ({ page }) => {
    await jsonRoute(page, '**/api/topics/keywords', [])
    await page.route('**/api/topics', route => route.fulfill({ status: 201, json: { id: 'created', title: 'Created subject' } }))
    await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
    const components = {
      preferences: ['app/chat/components/RoomPreferencesDialog.vue', { modelValue: true, canEditTopic: true,
        room: { id: 'room-a', label: 'Conversation', topic_id: null, show_last_message: true, archived: false } }],
      composer: ['app/chat/components/Composer.vue', { roomId: 'room-a', sending: false, canSelectTopic: true, commands: ['topic'] }],
      assignment: ['app/topic/components/TopicAssignmentEditor.vue', { topicId: null, editable: true }],
    }
    const [component, props] = components[form]
    await mount(page, component, { privileges: ['TOPIC_EDIT', 'AGENT_MANAGE_ALL'], props })
    if (form === 'composer') await page.locator('textarea').fill('@topic Message draft')
    await page.getByRole('button', { name: 'Create a thematic dossier', exact: true }).click()
    const dialog = page.getByRole('dialog').last()
    await dialog.getByRole('textbox', { name: 'Dossier', exact: true }).fill('Created subject')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    if (form === 'composer') {
      await expect.poll(() => page.evaluate(() => window.testApp.events.find(event => event.name === 'update:topicId')?.args))
        .toEqual(['created'])
      await expect(page.locator('textarea')).toHaveValue('@topic Message draft')
    } else {
      await expect(page.getByText('Created subject', { exact: true })).toBeVisible()
      await page.getByRole('button', { name: form === 'assignment' ? 'Save dossier' : 'Save', exact: true }).click()
      await expect.poll(() => page.evaluate(() => window.testApp.events.find(event => event.name === 'save')?.args))
        .toEqual(form === 'assignment' ? ['created'] : ['Conversation', true, 'created'])
    }
  })
}

test('topic creation is opt-in and requires edit and global management rights', async ({ page }) => {
  await jsonRoute(page, '**/api/topics?*', { items: [{ id: 'existing', title: 'Existing subject' }], total: 1 })
  await mount(page, 'app/topic/components/TopicSelect.vue', {
    privileges: ['TOPIC_EDIT', 'AGENT_MANAGE_ALL'], props: { modelValue: null, label: 'Topic' },
  })
  const create = page.getByRole('button', { name: 'Create a thematic dossier', exact: true })
  await expect(create).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Topic', exact: true }).click()
  await page.getByRole('option', { name: 'Existing subject' }).click()
  await expect.poll(() => selected(page)).toBe('existing')
  await page.evaluate(() => window.testApp.setProps({ allowCreate: true }))
  await expect(create).toBeVisible()
  for (const privileges of [[], ['TOPIC_ACCESS'], ['TOPIC_EDIT'], ['AGENT_MANAGE_ALL']]) {
    await setPrivileges(page, privileges)
    await expect(create).toHaveCount(0)
  }
  await setPrivileges(page, ['TOPIC_EDIT', 'AGENT_MANAGE_ALL'])
  await expect(create).toBeVisible()
  for (const prop of ['readonly', 'disable']) {
    await page.evaluate(prop => window.testApp.setProps({ [prop]: true }), prop)
    await expect(create).toHaveCount(0)
    await page.evaluate(prop => window.testApp.setProps({ [prop]: false }), prop)
    await expect(create).toBeVisible()
  }
})

for (const change of ['cancel', 'selection', 'privileges']) {
  test(`a late topic creation cannot overwrite a changed context: ${change}`, async ({ page }) => {
    let release
    const pending = new Promise(resolve => { release = resolve })
    await jsonRoute(page, '**/api/topics/keywords', [])
    await jsonRoute(page, '**/api/topics/existing', { id: 'existing', title: 'Existing subject' })
    await page.route('**/api/topics', async route => {
      await pending
      await route.fulfill({ status: 201, json: { id: 'late', title: 'Late subject' } })
    })
    await mount(page, 'app/topic/components/TopicSelect.vue', {
      privileges: ['TOPIC_EDIT', 'AGENT_MANAGE_ALL'], props: { modelValue: null, allowCreate: true, label: 'Topic' },
    })
    const create = page.getByRole('button', { name: 'Create a thematic dossier', exact: true })
    await create.click()
    await page.getByRole('textbox', { name: 'Dossier', exact: true }).fill('Late subject')
    const request = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/topics'))
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await request
    try {
      if (change === 'cancel') await page.getByRole('button', { name: 'Cancel', exact: true }).last().click()
      if (change === 'selection') await page.evaluate(() => window.testApp.setProps({ modelValue: 'existing' }))
      if (change === 'privileges') await setPrivileges(page, ['TOPIC_ACCESS'])
      await expect(page.getByRole('dialog')).toHaveCount(0)
      if (change === 'cancel') {
        await create.click()
        await page.getByRole('textbox', { name: 'Dossier', exact: true }).fill('Current draft')
      }
      const response = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/topics'))
      release()
      await response
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      expect(await selected(page)).toBeUndefined()
      if (change === 'cancel') await expect(page.getByRole('textbox', { name: 'Dossier', exact: true })).toHaveValue('Current draft')
      if (change === 'selection') await expect(page.getByText('Existing subject', { exact: true })).toBeVisible()
    } finally { release() }
  })
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`topic participant counts keep large groups inspectable at viewport ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const teams = ['Planning', 'Design', 'Support', 'Research', 'Sales'].map((name, id) => ({ id, name }))
    const agents = Array.from({ length: 5 }, (_, id) => ({ id, name: `Agent ${id}` }))
    const users = Array.from({ length: 5 }, (_, id) => ({ id: `contact-${id}`, display_name: `User ${id}`, user_id: `user-${id}` }))
    await page.route('**/api/topics?*', route => route.fulfill({ json: {
      items: [{
        id: 'renovation', revision: 1, title: 'Renovation', description: '', keywords: [],
        memory_item_id: null, created_at: '2026-09-01T12:00:00Z', updated_at: null,
        inference_cost: 0, llm_calls: 0,
        agents,
        users,
        teams,
        documents: [{ id: 'brief', title: 'Renovation brief', filename: 'brief.md' }],
      }],
      total: 1, month: '2026-09', available_months: ['2026-09'],
    } }))
    await mount(page, 'app/topic/pages/index.vue', { privileges: ['TOPIC_ACCESS'] })
    await expect(page.getByText('Renovation', { exact: true })).toBeVisible()
    for (const name of [...agents.map(agent => agent.name), ...users.map(user => user.display_name), ...teams.map(team => team.name)]) {
      await expect(page.getByText(name, { exact: true })).toBeVisible()
    }
    await expect(page.getByText('Renovation brief', { exact: true })).toHaveCount(0)
    agents.push({ id: 5, name: 'Agent 5' })
    users.push({ id: 'contact-5', display_name: 'User 5', user_id: 'user-5' })
    teams.push({ id: 5, name: 'Operations' })
    await page.getByRole('button', { name: 'Refresh costs', exact: true }).click()
    for (const [label, names] of [
      ['6 agents', agents.map(agent => agent.name)],
      ['6 users', users.map(user => user.display_name)],
      ['6 teams', teams.map(team => team.name)],
    ]) {
      const counter = page.getByRole('button', { name: label, exact: true })
      await expect(counter).toBeVisible()
      for (const name of names) await expect(page.getByText(name, { exact: true })).not.toBeVisible()
      await counter.click()
      for (const name of names) await expect(page.getByText(name, { exact: true })).toBeVisible()
      await page.keyboard.press('Escape')
    }
  })
}

test('a topic outside the first page can be searched and selected by keyboard', async ({ page }) => {
  const searches = []
  await page.route('**/api/topics?*', route => {
    const search = new URL(route.request().url()).searchParams.get('q')
    searches.push(search)
    return route.fulfill({ json: { items: search === 'Rare' ? [{ id: 'rare', title: 'Rare topic' }] : [], total: search === 'Rare' ? 1 : 0 } })
  })
  await mount(page, 'app/topic/components/TopicSelect.vue', { props: { modelValue: null, label: 'Topic' } })
  const input = page.getByRole('combobox', { name: 'Topic', exact: true })
  await input.fill('Rare')
  await expect(page.getByRole('option', { name: 'Rare topic', exact: true })).toBeVisible()
  expect(searches).toContain('Rare')
  await input.press('ArrowDown')
  await input.press('Enter')
  await expect.poll(() => selected(page)).toBe('rare')
})

test('a failed topic lookup explains the error and recovers on the next search', async ({ page }) => {
  await page.route('**/api/topics?*', route => route.fulfill({ status: 503, json: { detail: 'Topic lookup unavailable' } }))
  await mount(page, 'app/topic/components/TopicSelect.vue', { props: { modelValue: null, label: 'Topic' } })
  await page.getByRole('combobox', { name: 'Topic', exact: true }).click()
  await expect(page.getByText('Topic lookup unavailable', { exact: false })).toBeVisible()
  await jsonRoute(page, '**/api/topics?*', { items: [{ id: 'recovered', title: 'Recovered topic' }], total: 1 })
  await page.getByRole('combobox', { name: 'Topic', exact: true }).fill('Recovered')
  await page.getByRole('option', { name: 'Recovered topic', exact: true }).click()
  await expect.poll(() => selected(page)).toBe('recovered')
  await expect(page.getByText('Topic lookup unavailable', { exact: false })).toHaveCount(0)
})

test('late topic searches cannot replace a newer result or its selection', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/topics?*', async route => {
    const search = new URL(route.request().url()).searchParams.get('q')
    if (search === 'Old') await pending
    await route.fulfill({ json: { items: search ? [{ id: search, title: `${search} topic` }] : [], total: search ? 1 : 0 } })
  })
  await mount(page, 'app/topic/components/TopicSelect.vue', { props: { modelValue: null, label: 'Topic' } })
  const input = page.getByRole('combobox', { name: 'Topic', exact: true })
  const oldRequest = page.waitForRequest(request => request.url().includes('q=Old'))
  await input.fill('Old')
  await oldRequest
  try {
    await input.fill('New')
    await expect(page.getByRole('option', { name: 'New topic', exact: true })).toBeVisible()
    const oldResponse = page.waitForResponse(response => response.url().includes('q=Old'))
    release()
    await oldResponse
    await expect(page.getByRole('option', { name: 'Old topic', exact: true })).toHaveCount(0)
    await page.getByRole('option', { name: 'New topic', exact: true }).click()
    await expect.poll(() => selected(page)).toBe('New')
  } finally { release() }
})

test('scrolling the topic choices reaches the next server page without losing the first', async ({ page }) => {
  const topics = Array.from({ length: 51 }, (_, index) => ({ id: `topic-${index}`, title: `Topic ${String(index).padStart(2, '0')}` }))
  const offsets = []
  await page.route('**/api/topics?*', route => {
    const query = new URL(route.request().url()).searchParams
    const skip = Number(query.get('skip') ?? 0)
    offsets.push(skip)
    return route.fulfill({ json: { items: topics.slice(skip, skip + Number(query.get('limit'))), total: topics.length } })
  })
  await mount(page, 'app/topic/components/TopicSelect.vue', { props: { modelValue: null, label: 'Topic' } })
  await page.getByRole('combobox', { name: 'Topic', exact: true }).click()
  const choices = page.getByRole('listbox')
  await expect(page.getByRole('option', { name: 'Topic 00', exact: true })).toBeVisible()
  await choices.hover()
  await page.mouse.wheel(0, 5000)
  await expect.poll(() => offsets.includes(50)).toBe(true)
  await page.mouse.wheel(0, 5000)
  await page.getByRole('option', { name: 'Topic 50', exact: true }).click()
  await expect.poll(() => selected(page)).toBe('topic-50')
})

test('merging searches for a destination and excludes the source topic', async ({ page }) => {
  const source = { id: 'source', title: 'Source subject', keywords: [], agents: [], users: [], teams: [],
    documents: [], created_at: '2026-09-01T12:00:00Z', inference_cost: 0, llm_calls: 0 }
  const target = { ...source, id: 'target', title: 'Remote subject' }
  await page.route('**/api/topics?*', route => {
    const searching = new URL(route.request().url()).searchParams.get('q') === 'Remote'
    return route.fulfill({ json: { items: searching ? [source, target] : [source], total: searching ? 2 : 1,
      month: '2026-09', available_months: ['2026-09'] } })
  })
  let merged
  await page.route('**/api/topics/source/merge', route => {
    merged = route.request().postDataJSON()
    return route.fulfill({ json: { topic: target, moved_memory_links: 0 } })
  })
  await mount(page, 'app/topic/pages/index.vue', { privileges: ['TOPIC_ACCESS', 'TOPIC_EDIT', 'AGENT_MANAGE_ALL'] })
  await page.getByRole('button', { name: 'Merge', exact: true }).click()
  const input = page.getByRole('combobox', { name: 'Destination dossier', exact: true })
  await input.fill('Remote')
  await expect(page.getByRole('option', { name: 'Remote subject', exact: true })).toBeVisible()
  await expect(page.getByRole('option', { name: 'Source subject', exact: true })).toHaveCount(0)
  await page.getByRole('option', { name: 'Remote subject', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect.poll(() => merged).toEqual({ target_topic_id: 'target' })
})

test('closing topic merge discards a late failure loading its target choices', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let requests = 0
  await page.route('**/api/topics?*', async route => {
    if (++requests > 1) {
      await pending
      await route.fulfill({ status: 503, json: { detail: 'Obsolete merge failure' } })
    } else await route.fulfill({ json: {
      items: [{ id: 'topic-a', title: 'Topic A', keywords: [], agents: [], users: [], teams: [],
        documents: [], created_at: '2026-09-01T12:00:00Z', inference_cost: 0, llm_calls: 0 }],
      total: 1, month: '2026-09', available_months: ['2026-09'],
    } })
  })
  await mount(page, 'app/topic/pages/index.vue', { privileges: ['TOPIC_ACCESS', 'TOPIC_EDIT', 'AGENT_MANAGE_ALL'] })
  await page.getByRole('button', { name: 'Merge', exact: true }).click()
  const request = page.waitForRequest('**/api/topics?*')
  await page.getByRole('combobox', { name: 'Destination dossier', exact: true }).click()
  try {
    await request
    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const response = page.waitForResponse(response => response.url().includes('/topics?') && response.status() === 503)
    release()
    await response
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(page.locator('.q-notification')).toHaveCount(0)
  } finally { release() }
})
