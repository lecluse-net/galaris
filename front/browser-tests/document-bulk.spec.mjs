import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

const folder = { id: 'work', name: 'Work', parent_id: null }
const recipient = { kind: 'user', id: 12, label: 'Reader Example', can_write: false }
const other = { kind: 'team', id: 22, label: 'Other team', can_write: true }

async function fixture(page, { count = 2, folder: initialFolder = folder } = {}) {
  const docs = Array.from({ length: count }, (_, index) => ({ ...structuredClone(document), id: `doc-${index}`,
    revision: index + 3, lock_version: index + 3,
    title: `Report ${String(index).padStart(2, '0')}`, keywords: [`original-${index}`, 'shared'], media_type: 'text/html', payload: { text: '<p>Synthetic report</p>' } }))
  const reads = [], writes = []
  const states = docs.map((item, index) => ({ lock_version: item.lock_version, can_manage: true,
    owner: { kind: 'agent', id: 7, label: 'Owner', can_write: true }, owner_groups: [],
    level: index ? 'public' : 'groups', can_write: false,
    grants: index ? [{ ...recipient, can_write: true }] : [other], options: [recipient, other],
  }))
  let failId = null
  await jsonRoute(page, '**/api/documents/tags/*/sharing', {
    lock_version: 1, can_manage: true, owner: null, owner_groups: [],
    level: 'private', can_write: false, grants: [], options: [recipient, other],
  })
  await page.route('**/api/documents/library', route => {
    const body = route.request().postDataJSON(); reads.push(body)
    const matches = docs.filter(item => !body.query || item.title.includes(body.query))
    return route.fulfill({ json: { entries: matches.slice(body.offset, body.offset + body.limit).map(item => ({
      item, owner_label: 'Owner Example', tags: [folder], agent_ids: [7], writable_agent_ids: [7],
    })), total: matches.length, has_more: body.offset + body.limit < matches.length, keywords: [] } })
  })
  await page.route(/\/api\/documents\/doc-\d+(?:\?|$)/, route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)
    const item = docs.find(item => item.id === id)
    const method = route.request().method()
    if (method === 'GET') return route.fulfill({ json: { item, agent_id: 7 } })
    if (id === failId) return route.fulfill({ status: 409, json: { detail: 'Changed concurrently' } })
    if (method === 'DELETE') { writes.push({ id, method }); docs.splice(docs.indexOf(item), 1); return route.fulfill({ json: { forgotten: true } }) }
    const data = route.request().postDataJSON(); writes.push({ id, ...data })
    expect(data.expected_lock_version).toBe(item.lock_version)
    Object.assign(item, { keywords: data.keywords, lock_version: item.lock_version + 1 })
    return route.fulfill({ json: item })
  })
  await page.route(/\/api\/documents\/doc-\d+\/sharing(?:-level)?$/, async route => {
    const id = new URL(route.request().url()).pathname.split('/')[4]
    const state = states[Number(id.split('-')[1])]
    if (route.request().method() === 'GET') return route.fulfill({ json: state })
    const data = route.request().postDataJSON(); writes.push({ id, ...data })
    expect(data.expected_lock_version).toBe(state.lock_version)
    if ('grants' in data) Object.assign(state, { grants: data.grants.map(grant => ({ ...state.options.find(option => option.kind === grant.kind && option.id === grant.id), ...grant })), level: data.level, can_write: data.can_write })
    else {
      state.grants = state.grants.filter(grant => grant.kind !== data.kind || grant.id !== data.id)
      if (data.can_write !== null) state.grants.push({ ...recipient, ...data })
    }
    state.lock_version++
    await page.evaluate(() => window.testApp.emitSocket('memory.invalidate', { data: {} }))
    return route.fulfill({ json: state })
  })
  await jsonRoute(page, '**/api/documents/owner-options?*', {
    agents: [], users: [{ kind: 'user', id: 1, label: 'New Owner', subtitle: '', is_current_user: true }],
  })
  await page.route('**/api/documents/*/owner', route => {
    const id = new URL(route.request().url()).pathname.split('/')[4]
    const data = route.request().postDataJSON(); writes.push({ documentId: id, ...data })
    return route.fulfill({ json: docs.find(item => item.id === id) })
  })
  await mount(page, 'app/document/components/DocumentBulkList.vue', { props: { folder: initialFolder }, privileges: ['DOCUMENT_EDIT'] })
  await expect(page.getByRole('link', { name: 'Report 00', exact: true })).toBeVisible()
  return { docs, reads, writes, states, fail: id => { failId = id } }
}
async function selectPage(page) { await page.getByRole('checkbox', { name: 'Select this page', exact: true }).check() }
async function action(page, name) {
  await page.getByRole('button', { name: 'Selection actions', exact: true }).click()
  await page.getByRole('combobox', { name: 'Operation', exact: true }).click()
  await page.getByRole('option', { name, exact: true }).click()
}
async function choose(page, field, option) {
  await page.getByRole('combobox', { name: field, exact: true }).click()
  await page.getByRole('option', { name: option, exact: true }).click()
}
async function apply(page) {
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Selection actions', exact: true })).toBeDisabled()
}

for (const width of [1440, 390]) {
  test(`folder list scopes recursion and page selection, preserves each keyword set and reopens at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const { docs, reads } = await fixture(page, { count: 51 })
    expect(reads[0]).toMatchObject({ tag_id: 'work', include_descendants: false, limit: 50, offset: 0 })
    await page.getByRole('checkbox', { name: 'Include subfolders and sub-documents', exact: true }).check()
    await expect.poll(() => reads.at(-1).include_descendants).toBe(true)
    await selectPage(page)
    await expect(page.getByText('50 selected', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '2', exact: true }).click()
    await expect(page.getByText('0 selected', { exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Report 50', exact: true })).toBeVisible()
    await selectPage(page)
    await action(page, 'Add keywords')
    await page.getByRole('combobox', { name: 'Keywords', exact: true }).fill('SHARED')
    await page.getByRole('combobox', { name: 'Keywords', exact: true }).press('Enter')
    await page.getByRole('combobox', { name: 'Keywords', exact: true }).fill('new-keyword')
    await page.getByRole('combobox', { name: 'Keywords', exact: true }).press('Enter')
    await apply(page)
    expect(docs[50].keywords).toEqual(['original-50', 'shared', 'new-keyword'])
    expect(docs[0].keywords).toEqual(['original-0', 'shared'])
    await selectPage(page)
    await action(page, 'Remove keywords')
    await page.getByRole('combobox', { name: 'Keywords', exact: true }).fill('SHARED')
    await page.getByRole('combobox', { name: 'Keywords', exact: true }).press('Enter')
    await apply(page)
    expect(docs[50].keywords).toEqual(['original-50', 'new-keyword'])
    await page.getByRole('link', { name: 'Report 50', exact: true }).click()
    expect(await page.evaluate(() => window.testApp.events.find(event => event.name === 'select').value.item.id)).toBe('doc-50')
    await page.screenshot({ path: testInfo.outputPath(`document-bulk-${width}.png`), animations: 'disabled', fullPage: true })
  })
}

test('sharing commands preserve different existing shares and update or remove only the chosen recipient', async ({ page }) => {
  const { states, writes } = await fixture(page)
  for (const access of ['Add / set read access', 'Add / set write access', 'Remove this share']) {
    await selectPage(page)
    await action(page, 'Change sharing')
    await choose(page, 'Recipient', 'Reader Example (User)')
    await choose(page, 'Sharing action', access)
    await apply(page)
    expect(states[0].grants).toContainEqual(other)
    expect(states[1].level).toBe('public')
    if (access === 'Remove this share') {
      expect(states.every(state => !state.grants.some(grant => grant.kind === 'user' && grant.id === 12))).toBe(true)
    } else {
      expect(states.every(state => state.grants.some(grant => grant.kind === 'user' && grant.id === 12 && grant.can_write === access.includes('write')))).toBe(true)
    }
  }
  expect(writes).toHaveLength(6)
  expect(writes.every(write => !('grants' in write))).toBe(true)
  await selectPage(page)
  await action(page, 'Change sharing')
  await choose(page, 'Sharing action', 'Add / set write access')
  await apply(page)
  expect(states.every(state => state.level === 'public' && state.can_write)).toBe(true)
  expect(states[0].grants).toEqual([other])
  await selectPage(page)
  await action(page, 'Change sharing')
  await choose(page, 'Sharing action', 'Remove this share')
  await apply(page)
  expect(states[0].level).toBe('groups')
  expect(states[1].level).toBe('private')
  expect(states[0].grants).toEqual([other])
})

test('ownership uses each current revision', async ({ page }) => {
  const { writes, docs } = await fixture(page)
  await selectPage(page)
  await action(page, 'Change owner')
  await choose(page, 'Owner', 'Me')
  await apply(page)
  expect(writes).toEqual(docs.map(item => ({ documentId: item.id, expected_revision: item.revision, expected_lock_version: item.lock_version, kind: 'user', id: 1 })))
})

test('shortcuts on a paginated document row target that document and preserve the bulk selection', async ({ page }) => {
  const { writes } = await fixture(page)
  await selectPage(page)
  await page.getByRole('link', { name: 'Report 01', exact: true }).hover()
  await page.keyboard.press('F3')
  await page.keyboard.press('F2')
  await page.keyboard.press('Delete')
  expect(await page.evaluate(() => window.testApp.events.filter(event => ['create', 'action'].includes(event.name))
    .map(event => [event.name, event.args[0].item.id, event.args[1]]))).toEqual([
    ['create', 'doc-1', undefined], ['action', 'doc-1', 'rename'], ['action', 'doc-1', 'delete'],
  ])
  await expect(page.getByText('2 selected', { exact: true })).toBeVisible()
  expect(writes).toEqual([])
})

test('unclassified lists require delete confirmation and retain failed documents', async ({ page }) => {
  const { docs, reads, fail } = await fixture(page, { folder: null })
  expect(reads[0]).toMatchObject({ tag_id: null, classification: 'unclassified' })
  await expect(page.getByRole('checkbox', { name: 'Include subfolders and sub-documents' })).toHaveCount(0)
  await selectPage(page)
  await action(page, 'Delete documents')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(docs).toHaveLength(2)
  fail('doc-1')
  await action(page, 'Delete documents')
  await page.getByRole('button', { name: 'Delete documents', exact: true }).click()
  await expect(page.getByText('Report 01 — The document changed. Review it before retrying.')).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'Select Report 01', exact: true })).toBeChecked()
  expect(docs.map(item => item.id)).toEqual(['doc-1'])
  fail(null)
  await action(page, 'Delete documents')
  await page.getByRole('button', { name: 'Delete documents', exact: true }).click()
  await expect(page.getByRole('link')).toHaveCount(0)
})

test('late folder reads cannot replace the current scope; failed reads can be retried', async ({ page }) => {
  await fixture(page)
  let release
  const gate = new Promise(resolve => { release = resolve })
  let fail = true
  await page.route('**/api/documents/library', async route => {
    const body = route.request().postDataJSON()
    if (body.query === 'older') {
      await gate
      return route.fulfill({ json: { entries: [{ item: { ...document, id: 'old', title: 'Obsolete title' }, agent_ids: [7], writable_agent_ids: [7] }], total: 1, keywords: [], has_more: false } })
    }
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
    return route.fallback()
  })
  const search = page.getByRole('textbox', { name: 'Search document titles and content', exact: true })
  const pending = page.waitForRequest(request => request.url().endsWith('/documents/library') && request.postDataJSON().query === 'older')
  await search.fill('older')
  await pending
  await search.fill('Report 01')
  await expect(page.getByRole('alert')).toBeVisible()
  fail = false
  await page.getByRole('alert').getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Report 01', exact: true })).toBeVisible()
  release()
  await expect(page.getByRole('link', { name: 'Obsolete title', exact: true })).toHaveCount(0)
  await expect(page.getByText('0 selected', { exact: true })).toBeVisible()
})

test('a session change stops unsent operations and discards the former selection', async ({ page }) => {
  const { writes } = await fixture(page)
  let release
  const gate = new Promise(resolve => { release = resolve })
  await page.route(/\/api\/documents\/doc-0(?:\?|$)/, async route => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    await gate
    return route.fulfill({ json: { ...document, id: 'doc-0', keywords: ['added'] } })
  })
  await selectPage(page)
  await action(page, 'Add keywords')
  const keywords = page.getByRole('combobox', { name: 'Keywords', exact: true })
  await keywords.fill('added'); await keywords.press('Enter')
  const pending = page.waitForRequest(request => request.url().includes('/documents/doc-0') && request.method() === 'PATCH')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await pending
  await page.evaluate(async () => {
    const api = await import('/core/api.ts')
    api.invalidateSessionRequests()
    window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'different-session' }))
  })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('0 selected', { exact: true })).toBeVisible()
  const completed = page.waitForResponse(response => response.url().includes('/documents/doc-0') && response.request().method() === 'PATCH')
  release()
  await (await completed).finished()
  await expect(page.getByRole('button', { name: 'Selection actions', exact: true })).toBeDisabled()
  expect(writes).toEqual([])
})
