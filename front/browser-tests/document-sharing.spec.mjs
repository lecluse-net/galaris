import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

const recipients = [
  { kind: 'agent', id: 7, label: 'Alice agent', can_write: false, has_avatar: false, group_ids: [42] },
  { kind: 'user', id: 7, label: 'Bob human', can_write: false, avatar_url: null, group_ids: [42] },
  { kind: 'team', id: 42, label: 'Project team', can_write: false },
]
const privateState = () => ({
  lock_version: 1, can_manage: true, grants: [], options: structuredClone(recipients),
  level: 'private', can_write: false,
  owner: { kind: 'agent', id: 99, label: 'Owner', can_write: true },
  owner_groups: [structuredClone(recipients[2])],
})
async function sharingFixture(page, resourceKind, state = privateState()) {
  const writes = []
  const base = resourceKind === 'dataset' ? '/api/datasets/doc-a'
    : resourceKind === 'document' ? '/api/documents/doc-a' : '/api/memory/items/doc-a'
  await page.route('**' + base + '/sharing', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: state })
    return save(route)
  })
  async function save(route) {
    const data = route.request().postDataJSON()
    expect(data.expected_lock_version).toBe(state.lock_version)
    writes.push(data)
    Object.assign(state, {
      level: data.level, can_write: data.can_write, lock_version: state.lock_version + 1,
      grants: data.grants.map(grant => ({ ...state.options.find(option => option.kind === grant.kind && option.id === grant.id), ...grant })),
    })
    return route.fulfill({ json: state })
  }
  if (resourceKind !== 'memory') await page.route('**' + base + '/sharing-level', save)
  await mount(page, resourceKind === 'dataset' ? 'app/dataset/components/DatasetSharing.vue' : 'app/document/components/DocumentSharingPanel.vue', {
    props: resourceKind === 'dataset' ? { id: 'doc-a', lockVersion: 1, editable: true } : { itemId: 'doc-a', resourceKind, editable: true },
  })
  return { state, writes }
}
const picker = page => page.getByRole('combobox', { name: 'Sharing', exact: true })
const toggle = (page, name) => page.getByRole('button', { name: 'Toggle read / write for ' + name, exact: true })
const remove = (page, name) => page.getByRole('button', { name: 'Remove access for ' + name, exact: true })

for (const width of [1440, 390]) {
test(`taking ownership keeps the document usable after revoking the original agent at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  const document = { ...documentFixture, media_type: 'text/html', payload: { text: '<p>Transferred content</p>' } }
  const human = { kind: 'user', id: 1, label: 'Current user', can_write: false }
  const originalAgent = { kind: 'agent', id: 7, label: 'Alice Example', can_write: true }
  const state = { ...privateState(), lock_version: document.lock_version,
    owner: originalAgent, grants: [human], options: [human], owner_groups: [] }
  let revoked = false
  const writes = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', {
    agents: [{ ...originalAgent, subtitle: '' }],
    users: [{ ...human, subtitle: '', is_current_user: true }],
  })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments*', [])
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [] })
  await page.route('**/api/documents/library', route => route.fulfill({ json: {
    entries: [{ item: document, tags: [], agent_ids: revoked ? [] : [7],
      writable_agent_ids: revoked ? [] : [7],
      user_access: { can_read: true, can_write: document.owner_user_id === 1 } }],
    total: 1, has_more: false, keywords: [],
  } }))
  await page.route(/\/api\/documents\/doc-a(?:\?|$)/, route => {
    const url = new URL(route.request().url())
    if (revoked && (url.searchParams.has('agent_id') || url.searchParams.has('actor_agent_id'))) {
      return route.fulfill({ status: 403, json: { detail: 'Original agent access revoked' } })
    }
    if (route.request().method() === 'PATCH') {
      writes.push(route.request().postDataJSON())
      Object.assign(document, writes.at(-1), { revision: document.revision + 1, lock_version: document.lock_version + 1 })
      return route.fulfill({ json: document })
    }
    return route.fulfill({ json: { item: document, agent_id: url.searchParams.has('agent_id') ? 7 : null } })
  })
  await page.route('**/api/documents/doc-a/owner', route => {
    expect(route.request().postDataJSON()).toMatchObject({ kind: 'user', id: 1 })
    Object.assign(document, { owner_agent_id: null, owner_user_id: 1, lock_version: document.lock_version + 1 })
    Object.assign(state, { owner: human, grants: [originalAgent], options: [originalAgent], lock_version: document.lock_version })
    return route.fulfill({ json: document })
  })
  await page.route('**/api/documents/doc-a/sharing', route => route.fulfill({ json: state }))
  await page.route('**/api/documents/doc-a/sharing-level', async route => {
    expect(route.request().postDataJSON().grants).toEqual([])
    revoked = true
    document.lock_version++
    Object.assign(state, { grants: [], lock_version: document.lock_version })
    await page.evaluate(() => window.testApp.emitSocket('document.invalidate', { data: {} }))
    return route.fulfill({ json: state })
  })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT'] })
  if (width < 1024) await page.getByText(document.title, { exact: true }).click()
  const editor = page.locator('[data-editor-surface]')
  await expect(editor).toContainText('Transferred content')
  await page.getByRole('combobox', { name: 'Owner', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Me' }).click()
  await expect(toggle(page, 'Alice Example')).toBeVisible()
  await expect(remove(page, 'Current user')).toHaveCount(0)
  await remove(page, 'Alice Example').click()
  await expect(picker(page)).toContainText('Private')
  await expect(editor).toContainText('Transferred content')
  await expect(page.getByLabel('Unclassified documents', { exact: true }).getByText(document.title, { exact: true })).toBeVisible()
  await editor.fill('Content edited as owner')
  await expect.poll(() => writes.at(-1)?.payload?.text).toContain('Content edited as owner')
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT'] })
  if (width < 1024) await page.getByText(document.title, { exact: true }).click()
  await expect(editor).toContainText('Content edited as owner')
  await expect(picker(page)).toContainText('Private')
})
}

for (const width of [1440, 390]) {
test(`changing rights reconciles the library and open document without remounting at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  const document = { ...documentFixture, media_type: 'text/html', payload: { text: '<p>Keep editing here</p>' } }
  const folder = { id: 'work', name: 'Work', parent_id: null }
  const state = privateState()
  state.lock_version = document.lock_version
  const entry = (id, title) => ({ item: { ...document, id, title }, tags: [folder], agent_ids: [], writable_agent_ids: [], user_access: document.access })
  let readGate = Promise.resolve(), fail = false, denied = false
  let reads = 0, writes = 0
  const contentWrites = []
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  const attachment = { id: 'file-a', name: 'Appendix.docx', media_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', size_bytes: 100, uri: 'document://doc-a/attachments/file-a' }
  await page.route('**/api/documents/doc-a/attachments/file-a/thumbnail?*', route => route.fulfill({ status: 204 }))
  await page.route('**/api/documents/doc-a/attachments', async route => {
    await readGate
    return route.fulfill(fail ? { status: 503, json: { detail: 'Unavailable' } } : { json: [attachment] })
  })
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [folder] })
  await page.route('**/api/documents/library', async route => {
    const request = route.request().postDataJSON()
    reads++
    await readGate
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Temporary failure' } })
    const entries = request.tag_id ? [entry('folder-doc', 'Folder report')]
      : denied ? [] : [entry('doc-a', document.title)]
    await route.fulfill({ json: { entries, total: entries.length, keywords: [], has_more: false } })
  })
  await page.route('**/api/documents/doc-a', async route => {
    if (route.request().method() === 'PATCH') {
      const update = route.request().postDataJSON()
      contentWrites.push(update)
      Object.assign(document, update, { revision: document.revision + 1, lock_version: document.lock_version + 1 })
      return route.fulfill({ json: document })
    }
    reads++
    const snapshot = structuredClone(document)
    await readGate
    if (fail || denied) return route.fulfill({ status: denied ? 403 : 503, json: { detail: 'Unavailable' } })
    await route.fulfill({ json: { item: snapshot, agent_id: null } })
  })
  await jsonRoute(page, '**/api/documents/doc-a/sharing', state)
  let release
  await page.route('**/api/documents/doc-a/sharing-level', async route => {
    writes++
    const update = route.request().postDataJSON()
    Object.assign(state, update, { lock_version: state.lock_version + 1 })
    document.lock_version = state.lock_version
    readGate = new Promise(resolve => { release = resolve })
    await page.evaluate(() => window.testApp.emitSocket('document.invalidate', { data: {} }))
    return route.fulfill({ json: state })
  })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT'] })
  await page.getByText('Work', { exact: true }).click()
  const listRow = await page.getByLabel('Unclassified documents', { exact: true }).getByText(document.title, { exact: true }).elementHandle()
  const folderRow = await page.getByText('Folder report', { exact: true }).elementHandle()
  if (width < 1024) await page.getByText(document.title, { exact: true }).click()
  const editor = page.locator('[data-editor-surface]')
  await expect(editor).toContainText('Keep editing here')
  const editorNode = await editor.elementHandle()
  const attachmentNode = await page.getByText('Appendix.docx', { exact: true }).elementHandle()
  await picker(page).click()
  const before = reads
  await page.getByRole('button', { name: 'Public: Write', exact: true }).click()
  await expect(toggle(page, 'Public')).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => writes).toBe(1)
  await expect.poll(() => reads).toBeGreaterThanOrEqual(before + 3)
  for (const node of [listRow, folderRow, editorNode, attachmentNode]) expect(await node.evaluate(element => element.isConnected)).toBe(true)
  await expect(editor).toContainText('Keep editing here')
  // Typing while the remote snapshot is pending must be included in the eventual merge.
  await editor.fill('Keep this new draft')
  const refreshed = page.waitForResponse(response => response.url().endsWith('/api/documents/doc-a') && response.request().method() === 'GET')
  release()
  await refreshed
  await expect(toggle(page, 'Public')).toHaveAttribute('aria-pressed', 'true')
  await expect(editor).toContainText('Keep this new draft')
  await expect.poll(() => contentWrites.at(-1)?.payload?.text).toContain('Keep this new draft')
  for (const node of [listRow, folderRow, editorNode, attachmentNode]) expect(await node.evaluate(element => element.isConnected)).toBe(true)

  // A temporary read failure preserves usable content; retry updates the same editor.
  fail = true
  await page.evaluate(() => window.testApp.emitSocket('document.invalidate', { data: {} }))
  await expect(page.locator('.document-editor').getByRole('alert')).toBeVisible()
  await expect(editor).toContainText('Keep this new draft')
  expect(await editorNode.evaluate(element => element.isConnected)).toBe(true)
  fail = false
  await page.locator('.document-editor').getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('.document-editor').getByRole('alert')).toHaveCount(0)
  expect(await editorNode.evaluate(element => element.isConnected)).toBe(true)

  // A confirmed denial removes the content, including inside the mobile dialog.
  denied = true
  await page.evaluate(() => window.testApp.emitSocket('document.invalidate', { data: {} }))
  await expect(editor).toHaveCount(0)
  await expect(page.getByLabel('Unclassified documents', { exact: true }).getByText(document.title, { exact: true })).toHaveCount(0)
})
}

for (const resourceKind of ['document', 'dataset']) {
  test(resourceKind + ' sharing adds recipients directly, toggles rights and removes access', async ({ page }) => {
    const { state, writes } = await sharingFixture(page, resourceKind)
    await expect(picker(page)).toContainText('Private')
    await picker(page).press('Enter')
    for (const name of ['Alice agent', 'Bob human']) {
      await page.getByRole('button', { name: name + ': Read', exact: true }).click()
      await expect(toggle(page, name)).toHaveAttribute('aria-pressed', 'false')
      await expect(page.getByRole('button', { name: name + ': Write', exact: true })).toHaveCount(0)
    }
    await page.getByRole('button', { name: 'Project team: Read', exact: true }).click()
    await expect(toggle(page, 'Project team')).toBeVisible()
    await page.keyboard.press('Escape')
    await toggle(page, 'Bob human').press('Space')
    await expect(toggle(page, 'Bob human')).toHaveAttribute('aria-pressed', 'true')
    await remove(page, 'Bob human').press('Enter')
    await expect(toggle(page, 'Bob human')).toHaveCount(0)
    expect(state.grants.map(grant => grant.kind)).toEqual(['agent', 'team'])
    expect(writes).toHaveLength(5)
    await picker(page).click()
    await expect(page.getByRole('button', { name: 'Bob human: Read', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Bob human: Write', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: 'Bob human: Write', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(toggle(page, 'Bob human')).toHaveAttribute('aria-pressed', 'true')
  })

  test(resourceKind + ' public read keeps writers, public write replaces them and revocation becomes private', async ({ page }) => {
    const { state } = await sharingFixture(page, resourceKind)
    await picker(page).click()
    await page.getByRole('button', { name: 'Alice agent: Write', exact: true }).click()
    await page.getByRole('button', { name: 'Public: Read', exact: true }).click()
    await expect(toggle(page, 'Public')).toHaveAttribute('aria-pressed', 'false')
    await expect(toggle(page, 'Alice agent')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('button', { name: 'Bob human: Read', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: 'Bob human: Write', exact: true }).click()
    await page.keyboard.press('Escape')
    await remove(page, 'Public').click()
    await expect(toggle(page, 'Alice agent')).toBeVisible()
    expect(state.level).toBe('private')
    await picker(page).click()
    await page.getByRole('button', { name: 'Public: Read', exact: true }).click()
    await page.keyboard.press('Escape')
    await toggle(page, 'Bob human').click()
    await expect(toggle(page, 'Bob human')).toHaveCount(0)
    expect(state.level).toBe('public')
    await toggle(page, 'Public').click()
    await expect(toggle(page, 'Public')).toHaveAttribute('aria-pressed', 'true')
    expect(state.grants).toEqual([])
    await picker(page).click()
    await expect(page.getByRole('dialog', { name: 'Add sharing' })).toHaveCount(0)
    await remove(page, 'Public').click()
    await expect(picker(page)).toContainText('Private')
  })
}

test('owner group shortcut excludes selected groups and inherited writers', async ({ page }) => {
  await sharingFixture(page, 'document')
  await picker(page).click()
  await page.getByRole('button', { name: 'Groups: Write', exact: true }).click()
  await expect(toggle(page, 'Project team')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Groups: Write', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Alice agent: Write', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Bob human: Write', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await remove(page, 'Project team').click()
  await expect(picker(page)).toContainText('Private')
})

test('search and category filtering reach recipients beyond the first page of 2000', async ({ page }) => {
  const state = privateState()
  state.options = Array.from({ length: 2000 }, (_, id) => ({
    kind: id % 2 ? 'user' : 'agent', id: id + 100, label: 'Recipient ' + String(id + 1).padStart(4, '0'),
    can_write: false, has_avatar: false,
  }))
  state.owner_groups = []
  await mount(page, 'app/share/components/SharingPanel.vue', { props: { state, editable: true } })
  await picker(page).click()
  await expect(page.getByText('1–50 of 2000', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Recipient .*: Read/ })).toHaveCount(50)
  await page.getByRole('button', { name: 'Next page', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Recipient 0051: Write', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'People', exact: true }).click()
  await expect(page.getByText('1–50 of 1000', { exact: true })).toBeVisible()
  await page.getByLabel('Search groups, people or agents', { exact: true }).fill('2000')
  await page.getByRole('button', { name: 'Recipient 2000: Write', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value?.grants)).toEqual([
    { kind: 'user', id: 2099, can_write: true },
  ])
})

test('failed saves preserve confirmed rights, reload recovers, and read-only access cannot mutate', async ({ page }) => {
  const { state } = await sharingFixture(page, 'document')
  await page.route('**/api/documents/doc-a/sharing-level', route => {
    if (route.request().method() === 'PUT') return route.fulfill({ status: 409, json: { detail: 'Changed elsewhere' } })
    return route.fulfill({ json: state })
  })
  await picker(page).click()
  await page.getByRole('button', { name: 'Public: Write', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Unable to load or save sharing')
  await expect(picker(page)).toContainText('Private')
  await page.keyboard.press('Escape')
  state.can_manage = false
  state.grants = [{ ...recipients[0], can_write: false }]
  await page.getByRole('button', { name: 'Reload access', exact: true }).click()
  await expect(picker(page)).toContainText('Alice agent')
  await expect(toggle(page, 'Alice agent')).toHaveCount(0)
  await expect(remove(page, 'Alice agent')).toHaveCount(0)
  await expect(picker(page)).toBeDisabled()
  await expect(page.getByRole('dialog', { name: 'Add sharing' })).toHaveCount(0)
})

test('private memory saves its content draft without independent sharing', async ({ page }) => {
  const initial = privateState()
  initial.lock_version = 3
  const state = initial
  let item = { ...documentFixture, title: 'Integration memory', node_kind: 'memory',
    media_type: 'text/html', content_profile: 'rich-text', content_profile_version: 1, payload: { text: '<p>Preserved memory</p>' } }
  const contentWrites = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/temporal/defaults', { timezone: 'Europe/Paris', lookahead_hours: 24 })
  await jsonRoute(page, '**/api/memory/filter-options?*', { topics: [], contacts: [] })
  await jsonRoute(page, '**/api/memory/findings?*', [])
  await jsonRoute(page, '**/api/memory/items/doc-a/revisions?*', [])
  await jsonRoute(page, '**/api/memory/items/doc-a/links?*', [])
  await page.route('**/api/memory/browse', route => route.fulfill({ json: { hits: [{ item, score: 1 }], total: 1, has_more: false } }))
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON()
      contentWrites.push(body)
      item = { ...item, ...body, revision: item.revision + 1 }
    }
    return route.fulfill({ json: { ...item, lock_version: state.lock_version, visibility: state.level === 'private' ? 'private' : 'shared' } })
  })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
  await page.getByText('Integration memory', { exact: true }).click()
  const editor = page.getByRole('dialog').filter({ has: page.locator('[data-editor-surface]') })
  await editor.locator('[data-editor-surface]').fill('Unsubmitted draft')
  await expect(picker(page)).toHaveCount(0)
  await expect(editor.locator('[data-editor-surface]')).toHaveText('Unsubmitted draft')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => contentWrites.length).toBe(1)
  expect(contentWrites[0]).toMatchObject({ payload: { text: '<p>Unsubmitted draft</p>' }, expected_revision: 3 })
  expect(contentWrites[0]).not.toHaveProperty('visibility')
  expect(state.level).toBe('private')
})

test('switching resource during a pending load ignores the obsolete response', async ({ page }) => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  let requested = false
  await page.route('**/api/documents/slow/sharing', async route => {
    requested = true
    await gate
    await route.fulfill({ json: { ...privateState(), grants: [recipients[0]] } })
  })
  await jsonRoute(page, '**/api/documents/current/sharing', { ...privateState(), grants: [recipients[1]] })
  await mount(page, 'app/document/components/DocumentSharingPanel.vue', { props: { itemId: 'slow', editable: true } })
  await expect.poll(() => requested).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ itemId: 'current' }))
  await expect(toggle(page, 'Bob human')).toBeVisible()
  const obsolete = page.waitForResponse('**/api/documents/slow/sharing')
  release()
  await obsolete
  await expect(toggle(page, 'Bob human')).toBeVisible()
  await expect(toggle(page, 'Alice agent')).toHaveCount(0)
})

for (const tagged of [false, true]) {
test(`a human without managed agents opens a shared document from the ${tagged ? 'tag tree' : 'orphan list'} and autosaves as themselves`, async ({ page }) => {
  await jsonRoute(page, '**/api/documents/icons/resolve', { 'doc-a': 'emoji:1F680' })
  const document = { ...documentFixture, id: 'doc-a', owner_agent_id: 7, media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Human document</p>' }, access: { can_read: true, can_write: true } }
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [{ id: 1, kind: 'user', label: 'Human', subtitle: '', is_current_user: true, avatar_url: null }] })
  await jsonRoute(page, '**/api/documents/doc-a/attachments', [])
  const writes = []
  await page.route('**/api/documents/doc-a', route => {
    if (route.request().method() === 'PATCH') {
      expect(new URL(route.request().url()).searchParams.has('actor_agent_id')).toBe(false)
      writes.push(route.request().postDataJSON())
      Object.assign(document, writes.at(-1), { revision: document.revision + 1, lock_version: document.lock_version + 1 })
      return route.fulfill({ json: document })
    }
    return route.fulfill({ json: { item: document, agent_id: null } })
  })
  const tags = tagged ? [{ id: 'reading', name: 'Reading', parent_id: null }] : []
  await page.route('**/api/documents/library', route => {
    const request = route.request().postDataJSON()
    const visible = tagged ? request.tag_id === 'reading' : request.classification === 'unclassified'
    return route.fulfill({ json: { entries: visible ? [{ item: document, tags, agent_ids: [], writable_agent_ids: [], user_access: document.access }] : [], total: visible ? 1 : 0, keywords: [], has_more: false } })
  })
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT'] })
  if (tagged) await page.getByText('Reading', { exact: true }).click()
  const list = page.getByLabel(tagged ? 'Documents in folder Reading' : 'Unclassified documents', { exact: true })
  await expect(list.getByText(document.title, { exact: true })).toBeVisible()
  await page.getByText(document.title, { exact: true }).first().click()
  await expect(page.locator('[data-editor-surface]')).toContainText('Human document')
  await expect(list.getByRole('img', { name: `Icon for document ${document.title}`, exact: true })).toContainText('🚀')
  await expect(page.locator('.document-editor-toolbar').getByRole('button', { name: `Icon for document ${document.title}`, exact: true })).toContainText('🚀')
  await page.locator('[data-editor-surface]').click()
  await page.keyboard.press('Control+End')
  await page.keyboard.type(' edited')
  await expect.poll(() => writes.at(-1)?.payload?.text).toContain('edited')
})
}




for (const scenario of [
  { name: 'global creation after cancelling folder creation', folder: null, width: 1440 },
  { name: 'creation in a closed root folder', folder: 'work', width: 1440 },
  { name: 'creation in a nested folder on mobile', folder: 'project', width: 390 },
  { name: 'failed classification preserves the created document', folder: 'work', width: 1440, failClassification: true },
]) {
test(`a private human-owned document opens using the human identity: ${scenario.name}`, async ({ page }) => {
  await page.setViewportSize({ width: scenario.width, height: 1000 })
  const tags = [{ id: 'work', name: 'Work', parent_id: null }, { id: 'project', name: 'Project', parent_id: 'work' }]
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags })
  let created = false
  let classified = null
  const creations = [], moves = []
  const document = { ...documentFixture, id: 'doc-a', title: 'Personal notes', owner_agent_id: null, owner_user_id: 1, global_access: 0, grants: [], access: { can_read: true, can_write: true }, payload: { text: '<p>Private notes</p>' } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [{ id: 1, kind: 'user', label: 'Human owner', subtitle: '', avatar_url: null, is_current_user: true }] })
  await jsonRoute(page, '**/api/documents/folders?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments', [])
  await jsonRoute(page, '**/api/documents/doc-a', { item: document, agent_id: null })
  await page.route('**/api/documents/library', route => {
    const body = route.request().postDataJSON()
    const visible = created && (body.tag_id ? body.tag_id === classified : body.classification !== 'unclassified' || !classified)
    const entries = visible ? [{ item: document, agent_ids: [], writable_agent_ids: [], user_access: document.access, tags: tags.filter(tag => tag.id === classified) }] : []
    return route.fulfill({ json: { entries, total: entries.length, keywords: [], has_more: false } })
  })
  await page.route('**/api/documents/doc-a/tags', route => {
    moves.push(route.request().postDataJSON())
    if (scenario.failClassification) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
    classified = route.request().postDataJSON().tag_id
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/documents', route => {
    expect(route.request().method()).toBe('POST')
    creations.push(route.request().postDataJSON())
    expect(creations.at(-1)).toMatchObject({ owner_kind: 'user', owner_id: 1, title: 'Personal notes' })
    created = true
    return route.fulfill({ json: document })
  })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT'] })
  if (!scenario.folder) {
    await page.getByRole('button', { name: 'New document in Work', exact: true }).press('Enter')
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: 'Create document', exact: true }).press('Enter')
  } else {
    if (scenario.folder === 'project') await page.getByText('Work', { exact: true }).click()
    const folder = tags.find(tag => tag.id === scenario.folder)
    await page.getByRole('button', { name: `New document in ${folder.name}`, exact: true }).press('Enter')
    await expect(page.getByRole('dialog')).toContainText(`New document in ${folder.name}`)
  }
  await page.getByRole('dialog').getByLabel('Title', { exact: true }).fill('Personal notes')
  await page.getByRole('dialog').getByRole('button', { name: 'Create', exact: true }).click()
  if (scenario.width >= 1024) await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('[data-editor-surface]')).toContainText('Private notes')
  expect(creations).toHaveLength(1)
  expect(moves).toEqual(scenario.folder ? [{ tag_id: scenario.folder }] : [])
  if (scenario.width < 1024) await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).first().click()
  if (scenario.folder && !scenario.failClassification) {
    const folder = tags.find(tag => tag.id === scenario.folder)
    await expect(page.getByLabel(`Documents in folder ${folder.name}`, { exact: true }).getByText('Personal notes', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Unclassified documents', { exact: true }).getByText('Personal notes', { exact: true })).toHaveCount(0)
  } else {
    await expect(page.getByLabel('Unclassified documents', { exact: true }).getByText('Personal notes', { exact: true })).toBeVisible()
    if (scenario.failClassification) await expect(page.getByText('The document was created, but could not be placed in Work. You can move it there.', { exact: true })).toBeVisible()
  }
})
}
