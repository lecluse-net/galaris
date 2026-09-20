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
  const base = resourceKind === 'document' ? '/api/memory/documents/doc-a' : '/api/memory/items/doc-a'
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
  if (resourceKind === 'document') await page.route('**' + base + '/sharing-level', save)
  await mount(page, 'app/memory/components/MemorySharingPanel.vue', {
    props: { itemId: 'doc-a', resourceKind, editable: true },
  })
  return { state, writes }
}
const picker = page => page.getByRole('combobox', { name: 'Sharing', exact: true })
const toggle = (page, name) => page.getByRole('button', { name: 'Toggle read / write for ' + name, exact: true })
const remove = (page, name) => page.getByRole('button', { name: 'Remove access for ' + name, exact: true })

for (const resourceKind of ['document', 'memory']) {
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
  await mount(page, 'core/util/components/SharingPanel.vue', { props: { state, editable: true } })
  await picker(page).click()
  await expect(page.getByText('1–10 of 2000', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Recipient .*: Read/ })).toHaveCount(10)
  await page.getByRole('button', { name: 'Next page', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Recipient 0011: Write', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'People', exact: true }).click()
  await expect(page.getByText('1–10 of 1000', { exact: true })).toBeVisible()
  await page.getByLabel('Search groups, people or agents', { exact: true }).fill('2000')
  await page.getByRole('button', { name: 'Recipient 2000: Write', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value?.grants)).toEqual([
    { kind: 'user', id: 2099, can_write: true },
  ])
})

test('failed saves preserve confirmed rights, reload recovers, and read-only access cannot mutate', async ({ page }) => {
  const { state } = await sharingFixture(page, 'memory')
  await page.route('**/api/memory/items/doc-a/sharing', route => {
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

test('memory detail and editor share the common control without overwriting a content draft', async ({ page }) => {
  const initial = privateState()
  initial.lock_version = 3
  const { state } = await sharingFixture(page, 'memory', initial)
  let item = { ...documentFixture, title: 'Integration memory', node_kind: 'memory', memory_type: 'semantic',
    media_type: 'text/html', content_profile: 'rich-text', content_profile_version: 1, payload: { text: '<p>Preserved memory</p>' } }
  const contentWrites = []
  await jsonRoute(page, '**/api/agents?*', [agent])
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
  await picker(page).click()
  await page.getByRole('button', { name: 'Alice agent: Read', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(toggle(page, 'Alice agent')).toBeVisible()
  const editor = page.getByRole('dialog').filter({ has: page.getByLabel('Title', { exact: true }) })
  await editor.getByLabel('Title', { exact: true }).fill('Unsubmitted draft')
  await editor.getByRole('combobox', { name: 'Sharing', exact: true }).click()
  await page.getByRole('button', { name: 'Public: Read', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(editor.getByLabel('Title', { exact: true })).toHaveValue('Unsubmitted draft')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => contentWrites.length).toBe(1)
  expect(contentWrites[0]).toMatchObject({ title: 'Unsubmitted draft', expected_revision: 3 })
  expect(contentWrites[0]).not.toHaveProperty('visibility')
  expect(state.level).toBe('public')
})

test('switching resource during a pending load ignores the obsolete response', async ({ page }) => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  let requested = false
  await page.route('**/api/memory/items/slow/sharing', async route => {
    requested = true
    await gate
    await route.fulfill({ json: { ...privateState(), grants: [recipients[0]] } })
  })
  await jsonRoute(page, '**/api/memory/items/current/sharing', { ...privateState(), grants: [recipients[1]] })
  await mount(page, 'app/memory/components/MemorySharingPanel.vue', { props: { itemId: 'slow', editable: true } })
  await expect.poll(() => requested).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ itemId: 'current' }))
  await expect(toggle(page, 'Bob human')).toBeVisible()
  const obsolete = page.waitForResponse('**/api/memory/items/slow/sharing')
  release()
  await obsolete
  await expect(toggle(page, 'Bob human')).toBeVisible()
  await expect(toggle(page, 'Alice agent')).toHaveCount(0)
})

for (const tagged of [false, true]) {
test(`a human without managed agents opens a shared document from the ${tagged ? 'tag tree' : 'orphan list'} and autosaves as themselves`, async ({ page }) => {
  await jsonRoute(page, '**/api/memory/documents/icons/resolve', { 'doc-a': 'emoji:1F680' })
  const document = { ...documentFixture, id: 'doc-a', owner_agent_id: 7, media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Human document</p>' }, access: { can_read: true, can_write: true } }
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [], users: [{ id: 1, kind: 'user', label: 'Human', subtitle: '', is_current_user: true, avatar_url: null }] })
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments', [])
  const writes = []
  await page.route('**/api/memory/documents/doc-a', route => {
    if (route.request().method() === 'PATCH') {
      expect(new URL(route.request().url()).searchParams.has('actor_agent_id')).toBe(false)
      writes.push(route.request().postDataJSON())
      Object.assign(document, writes.at(-1), { revision: document.revision + 1, lock_version: document.lock_version + 1 })
      return route.fulfill({ json: document })
    }
    return route.fulfill({ json: { item: document, agent_id: null } })
  })
  const tags = tagged ? [{ id: 'reading', name: 'Reading', parent_id: null }] : []
  await page.route('**/api/memory/documents/library', route => {
    const request = route.request().postDataJSON()
    const visible = tagged ? request.tag_id === 'reading' : request.classification === 'unclassified'
    return route.fulfill({ json: { entries: visible ? [{ item: document, tags, agent_ids: [], writable_agent_ids: [], user_access: document.access }] : [], total: visible ? 1 : 0, keywords: [], has_more: false } })
  })
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  if (tagged) await page.getByText('Reading', { exact: true }).click()
  const list = page.getByLabel(tagged ? 'Documents in folder Reading' : 'Unclassified documents', { exact: true })
  await expect(list.getByText(document.title, { exact: true })).toBeVisible()
  await page.getByText(document.title, { exact: true }).first().click()
  await expect(page.locator('.ck-editor__editable')).toContainText('Human document')
  await expect(list.getByRole(tagged ? 'img' : 'button', { name: `Icon for document ${document.title}`, exact: true })).toContainText('🚀')
  await expect(page.locator('.document-editor-toolbar').getByRole('button', { name: `Icon for document ${document.title}`, exact: true })).toContainText('🚀')
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('Control+End')
  await page.keyboard.type(' edited')
  await expect.poll(() => writes.at(-1)?.payload?.text).toContain('edited')
})
}




test('creating a private human-owned document opens it using the human identity', async ({ page }) => {
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [] })
  let created = false
  const document = { ...documentFixture, id: 'doc-a', title: 'Personal notes', owner_agent_id: null, owner_user_id: 1, global_access: 0, grants: [], access: { can_read: true, can_write: true }, payload: { text: '<p>Private notes</p>' } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [{ id: 1, kind: 'user', label: 'Human owner', subtitle: '', avatar_url: null, is_current_user: true }] })
  await jsonRoute(page, '**/api/memory/documents/folders?*', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a', { item: document, agent_id: null })
  await page.route('**/api/memory/documents/library', route => route.fulfill({ json: { entries: created ? [{ item: document, agent_ids: [], writable_agent_ids: [], user_access: document.access }] : [], total: created ? 1 : 0, keywords: [], has_more: false } }))
  await page.route('**/api/memory/documents', route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().postDataJSON()).toMatchObject({ owner_kind: 'user', owner_id: 1, title: 'Personal notes' })
    created = true
    return route.fulfill({ json: document })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  await page.getByRole('button', { name: 'Create document', exact: true }).first().click()
  await page.getByRole('dialog').getByLabel('Title', { exact: true }).fill('Personal notes')
  await page.getByRole('dialog').getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable')).toContainText('Private notes')
})
