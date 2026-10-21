import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function library(page, agentId = null) {
  const item = { ...documentFixture, owner_agent_id: agentId, owner_user_id: agentId === null ? 1 : null,
    media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Working copy</p>' } }
  const state = { item, deleted: false, reads: [] }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [] })
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', {
    agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '' }],
    users: [{ id: 1, kind: 'user', label: 'Me', subtitle: '', is_current_user: true }],
  })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments*', [])
  await page.route('**/api/memory/documents/library', route => {
    state.reads.push(route.request().postDataJSON())
    return route.fulfill({ json: { entries: state.deleted ? [] : [{ item: state.item, tags: [],
      agent_ids: [], writable_agent_ids: [], user_access: item.access }], total: state.deleted ? 0 : 1,
      has_more: false, keywords: ['reference'], owners: [{ id: 1, kind: 'user', label: 'Me', subtitle: '' }] } })
  })
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?|$)/, route => route.fulfill({ json: { item: state.item, agent_id: agentId } }))
  return state
}

for (const location of ['list', 'tree']) test(`dragging a document from the ${location} inserts its titled link, saves and reopens as a card`, async ({ page }, testInfo) => {
  const state = await library(page, 7)
  const id = '00000000-0000-0000-0000-000000000245'
  const source = { ...state.item, id, owner_agent_id: null, owner_user_id: 1, title: 'Reference <notes> & plan', payload: { text: '<p>Referenced content</p>' } }
  const folder = { id: 'references', name: 'References', parent_id: null, position: 1 }
  const writes = [], moves = []
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: location === 'tree' ? [folder] : [] })
  await page.route(new RegExp(`/api/memory/documents/${id}(?:\\?|$)`), route => route.fulfill(
    new URL(route.request().url()).searchParams.has('agent_id')
      ? { status: 403, json: { detail: 'The containing document Agent cannot read this private User document' } }
      : { json: { item: source, agent_id: null } }))
  await jsonRoute(page, `**/api/memory/documents/${id}/attachments*`, [])
  await page.route('**/api/memory/documents/library', route => {
    const query = route.request().postDataJSON()
    const items = query.tag_id ? [source] : location === 'list' ? [state.item, source] : [state.item]
    return route.fulfill({ json: { entries: items.map(item => ({ item, tags: item.id === id && location === 'tree' ? [folder] : [], agent_ids: item.owner_agent_id ? [item.owner_agent_id] : [], writable_agent_ids: item.owner_agent_id ? [item.owner_agent_id] : [], user_access: item.owner_user_id ? item.access : { can_read: false, can_write: false } })), total: items.length, has_more: false, keywords: [] } })
  })
  await page.route('**/api/memory/documents/order', route => { moves.push(route.request().postDataJSON()); return route.fulfill({ status: 204 }) })
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?|$)/, route => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    const change = route.request().postDataJSON(); writes.push(change)
    state.item = { ...state.item, ...change, revision: state.item.revision + 1, lock_version: state.item.lock_version + 1 }
    return route.fulfill({ json: state.item })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  const editor = page.locator('[data-editor-surface]')
  await expect(editor).toContainText('Working copy')
  if (location === 'tree') await page.getByText('References', { exact: true }).click()
  const navigation = location === 'tree' ? page.locator('.document-tree') : page.getByRole('list', { name: 'Unclassified documents', exact: true })
  const row = navigation.getByText(source.title, { exact: true })
  await row.dragTo(editor, { targetPosition: { x: 60, y: 20 } })
  await expect(editor.locator('a')).toHaveText(source.title)
  await expect(editor).toContainText('Working copy')
  expect(await editorHtml(page)).toContain(`href="document://${id}"`)
  expect(moves).toEqual([])
  await editor.locator('a').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Show card', exact: true }).click()
  await expect(editor.locator('.galaris-link-card > p').first()).toHaveText(source.title)
  await expect.poll(() => writes.at(-1)?.payload?.text).toContain('galaris-link-card')
  expect(writes.at(-1).payload.text).toContain(`document://${id}`)
  await page.screenshot({ path: testInfo.outputPath(`document-reference-${location}.png`), animations: 'disabled' })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  await expect(editor.locator('.galaris-link-card > p').first()).toHaveText(source.title)
  await editor.locator('.galaris-link-card > p').first().click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Show URL', exact: true }).click()
  await expect(editor.locator('a')).toHaveText(source.title)
  await editor.locator('a').click({ modifiers: ['Control'] })
  await expect(editor).toHaveText('Referenced content')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Previous document', exact: true }).click()
  await expect(editor).toContainText('Working copy')
  expect(moves).toEqual([])
})

test('document content is usable while optional owner and keyword catalogues are still loading', async ({ page }) => {
  await library(page)
  let release
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/documents/owner-options?*', async route => {
    await gate
    return route.fallback()
  })
  await page.route('**/api/memory/documents/keywords?*', async route => { await gate; return route.fallback() })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  try {
    await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Test document', { timeout: 2000 })
    await expect(page.locator('[data-editor-surface]')).toContainText('Working copy')
  } finally { release() }
})

test('pending deletion hides every library row immediately, survives refresh, and restores the latest row on refusal', async ({ page }, testInfo) => {
  const state = await library(page)
  let releaseDelete, deleteStarted = false
  const gate = new Promise(resolve => { releaseDelete = resolve })
  await page.route('**/api/memory/documents/doc-a', async route => {
    if (route.request().method() !== 'DELETE') return route.fallback()
    deleteStarted = true
    await gate
    return route.fulfill({ status: 403, json: { detail: 'Access denied' } })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Test document')
  const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
  await page.getByRole('button', { name: 'Delete document', exact: true }).click()
  const started = Date.now()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete document', exact: true }).click()
  try {
    await expect.poll(() => deleteStarted).toBe(true)
    await expect(list.getByText('Test document', { exact: true })).toHaveCount(0, { timeout: 1500 })
    const removalMs = Date.now() - started
    state.item = { ...state.item, title: 'Latest title', lock_version: state.item.lock_version + 1 }
    await page.evaluate(() => window.testApp.emitSocket('memory.classification', { data: { user_id: 1, list_changed: true } }))
    await expect.poll(() => state.reads.length).toBe(2)
    await expect(list.getByText('Latest title', { exact: true })).toHaveCount(0)
    await testInfo.attach('pending-delete.json', { body: JSON.stringify({ removalMs, serverResponseReleased: false }), contentType: 'application/json' })
  } finally { releaseDelete() }
  await expect(page.getByText('Unable to delete the document.', { exact: true })).toBeVisible()
  await expect(list.getByText('Latest title', { exact: true })).toBeVisible()
  await expect(page.locator('[data-editor-surface]')).toContainText('Working copy')
})

test('slow refreshes coalesce notifications and retain fresh filter catalogues across searches', async ({ page }, testInfo) => {
  const state = await library(page)
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Test document')
  let release, slowReads = 0
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/documents/library', async route => {
    slowReads++
    await gate
    return route.fallback()
  })
  await page.evaluate(() => window.testApp.emitSocket('memory.classification', { data: { user_id: 1, list_changed: true } }))
  await expect.poll(() => slowReads).toBe(1)
  await page.evaluate(async () => {
    for (let i = 0; i < 8; i++) {
      window.testApp.emitSocket('memory.classification', { data: { user_id: 1, list_changed: true } })
      await new Promise(resolve => setTimeout(resolve, 140))
    }
  })
  expect(slowReads).toBe(1)
  release()
  await expect.poll(() => slowReads).toBe(2)
  await expect.poll(() => state.reads.length).toBe(3)
  await page.getByRole('textbox', { name: 'Search document titles and content', exact: true }).fill('Test')
  await expect.poll(() => state.reads.length).toBe(4)
  expect(state.reads.at(-1)).toMatchObject({ include_owners: false, include_keywords: false })
  await testInfo.attach('refresh-requests.json', { body: JSON.stringify({ notificationsDuringRead: 8,
    refreshRequests: slowReads - 1, searchRequest: state.reads.at(-1) }), contentType: 'application/json' })
})

test('a saved title updates every occurrence before the authoritative list and folder reads return', async ({ page }) => {
  const state = await library(page)
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [{ id: 'reports', name: 'Reports', parent_id: null }] })
  await page.route('**/api/memory/documents/doc-a', async route => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    const update = route.request().postDataJSON()
    state.item = { ...state.item, title: update.title, revision: state.item.revision + 1, lock_version: state.item.lock_version + 1 }
    return route.fulfill({ json: state.item })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Test document')
  await page.getByText('Reports', { exact: true }).click()
  const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
  const tree = page.getByRole('tree')
  await expect(list.getByText('Test document', { exact: true })).toBeVisible()
  await expect(tree.getByText('Test document', { exact: true })).toBeVisible()
  let release
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/documents/library', async route => { await gate; return route.fallback() })
  await page.getByLabel('Title', { exact: true }).fill('Saved title')
  try {
    await expect.poll(() => state.item.title).toBe('Saved title')
    await expect(list.getByText('Saved title', { exact: true })).toBeVisible()
    await expect(tree.getByText('Saved title', { exact: true })).toBeVisible()
  } finally { release() }
})

for (const mobile of [false, true]) {
test(`a historical Dataset link resolves once to its own editor (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
  await library(page)
  if (mobile) await page.setViewportSize({ width: 390, height: 844 })
  const id = '00000000-0000-4000-8000-000000000001'
  let reads = 0, release
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/documents/library', async route => { await gate; return route.fallback() })
  await jsonRoute(page, `**/api/memory/documents/${id}/attachments*`, [])
  await page.route(`**/api/memory/documents/${id}`, route => {
    reads++
    return route.fulfill({ json: { resource_type: 'dataset', resource_uri: `data://${id}` } })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${id}`, privileges: ['MEMORY_EDIT'],
  })
  try {
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe(`/dataset/${id}`)
    expect(reads).toBe(1)
    await expect(page.locator('.document-editor-fields')).toHaveCount(0)
  } finally { release() }
})
}

test('a draft from an earlier client keeps its edits and clears after saving without changing sharing', async ({ page }) => {
  const state = await library(page)
  const base = { owner: 'user:1', title: state.item.title, content: state.item.payload.text,
    keywords: [], globalAccess: 0, sharing: { 7: 'none' } }
  await page.addInitScript(saved => sessionStorage.setItem('galaris:document-draft:null:doc-a', JSON.stringify(saved)), {
    revision: state.item.revision, base, draft: { ...base, title: 'Recovered draft' },
  })
  const updates = []
  await page.route('**/api/memory/documents/doc-a', route => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    const update = route.request().postDataJSON()
    updates.push(update)
    state.item = { ...state.item, title: update.title, lock_version: state.item.lock_version + 1 }
    return route.fulfill({ json: state.item })
  })
  await mount(page, 'app/memory/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: null }, privileges: ['MEMORY_EDIT'] })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Recovered draft')
  await page.getByLabel('Title', { exact: true }).fill('Recovered and saved')
  await expect.poll(() => updates.length).toBe(1)
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('galaris:document-draft:null:doc-a'))).toBeNull()
  expect(updates[0]).toMatchObject({ title: 'Recovered and saved' })
  expect(updates[0]).not.toHaveProperty('payload')
})
