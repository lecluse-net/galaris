import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function library(page) {
  const item = { ...documentFixture, owner_agent_id: null, owner_user_id: 1,
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
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?|$)/, route => route.fulfill({ json: { item: state.item, agent_id: null } }))
  return state
}

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
    await expect(page.locator('.ck-editor__editable')).toContainText('Working copy')
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
  await expect(page.locator('.ck-editor__editable')).toContainText('Working copy')
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
test(`a direct Dataset link reads editor content once and still refreshes remotely (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
  const state = await library(page)
  if (mobile) await page.setViewportSize({ width: 390, height: 844 })
  const id = '00000000-0000-4000-8000-000000000001'
  // Dataset has no thumbnail capture: count editor reads independently of previews.
  state.item = { ...state.item, id, document_type: 'dataset', media_type: 'application/json', payload: { text: '{"value":1}' } }
  let reads = 0, release
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/documents/library', async route => { await gate; return route.fallback() })
  await jsonRoute(page, `**/api/memory/documents/${id}/attachments*`, [])
  await page.route(`**/api/memory/documents/${id}`, route => {
    reads++
    return route.fulfill({ json: { item: state.item, agent_id: null } })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${id}`, privileges: ['MEMORY_EDIT'],
  })
  try {
    await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Test document')
    expect(reads).toBe(1)
  } finally { release() }
  state.item = { ...state.item, title: 'Remote title', revision: state.item.revision + 1, lock_version: state.item.lock_version + 1 }
  await page.evaluate(item => window.testApp.emitSocket('memory.update', { data: item }), state.item)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Remote title')
  expect(reads).toBe(2)
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
