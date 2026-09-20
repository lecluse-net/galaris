import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

async function fixture(page, { writable = true } = {}) {
  let current = { ...document, document_type: 'dataset', media_type: 'application/json',
    content_profile_version: null, payload: { text: '{\n  "amount": 1200,\n  "label": "<b>Literal</b>"\n}' },
    access: { can_read: true, can_write: writable } }
  const writes = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: current })
    const body = route.request().postDataJSON()
    writes.push(body)
    current = { ...current, ...body, revision: current.revision + 1, lock_version: current.lock_version + 1 }
    return route.fulfill({ json: current })
  })
  return { writes, current: () => current, remote: value => { current = { ...current, ...value } } }
}

const editorOptions = { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['MEMORY_EDIT'] }

test('Dataset autosave preserves JSON source, invalid drafts and read-only access', async ({ page }) => {
  const state = await fixture(page)
  await mount(page, 'app/memory/components/DocumentEditor.vue', editorOptions)
  const input = page.getByRole('textbox', { name: 'Content', exact: true })
  await expect(input).toHaveValue(state.current().payload.text)
  await page.clock.install()
  await input.fill('{')
  await page.clock.runFor(1000)
  await expect(page.getByRole('alert')).toContainText('JSON must be valid')
  expect(state.writes).toEqual([])
  await mount(page, 'app/memory/components/DocumentEditor.vue', editorOptions)
  await expect(input).toHaveValue('{')
  const source = '{\n  "amount": 2400,\n  "label": "<b>Literal</b>"\n}\n'
  await input.fill(source)
  await page.clock.runFor(1000)
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.writes[0]).toMatchObject({ expected_revision: 3, media_type: 'application/json', payload: { text: source } })
  await expect(page.getByText('Saved automatically')).toBeVisible()
  await mount(page, 'app/memory/components/DocumentEditor.vue', editorOptions)
  await expect(input).toHaveValue(source)
  await page.evaluate(() => window.testApp.setProps({ editable: false }))
  await expect(input).not.toBeEditable()
  expect(state.writes).toHaveLength(1)
})

test('Dataset read-only grants prevent editing and JSON history stays literal', async ({ page }) => {
  const state = await fixture(page, { writable: false })
  const version = { revision: 3, media_type: 'application/json', content: state.current().payload.text,
    content_hash: 'synthetic', created_at: document.created_at, author_agent_id: 7, task_id: null }
  await jsonRoute(page, '**/api/memory/documents/doc-a/content-revisions?*', { items: [version], total: 1, limit: 50, offset: 0, has_more: false })
  await jsonRoute(page, '**/api/memory/documents/doc-a/content-revisions/3', version)
  await jsonRoute(page, '**/api/memory/documents/doc-a/content-revisions/3/diff', { revision: 3, current_revision: 3, hunks: [], structure_changed: false })
  await mount(page, 'app/memory/components/DocumentEditor.vue', editorOptions)
  await expect(page.getByRole('textbox', { name: 'Content', exact: true })).not.toBeEditable()
  await page.getByRole('button', { name: 'Open content history', exact: true }).click()
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  const preview = page.getByRole('textbox', { name: 'Preview', exact: true })
  await expect(preview).toHaveValue(version.content)
  await expect(preview).not.toBeEditable()
  expect(state.writes).toEqual([])
})

test('a concurrent Dataset edit keeps the local JSON until conflict resolution', async ({ page }) => {
  const state = await fixture(page)
  await mount(page, 'app/memory/components/DocumentEditor.vue', editorOptions)
  const input = page.getByRole('textbox', { name: 'Content', exact: true })
  await expect(input).toHaveValue(state.current().payload.text)
  await page.clock.install()
  await input.fill('{"local":true}')
  state.remote({ revision: 4, lock_version: 4, payload: { text: '{"remote":true}' } })
  await page.evaluate(() => window.testApp.emitSocket('memory.update', { data: { id: 'doc-a', node_kind: 'document', revision: 4 } }))
  await page.clock.runFor(300)
  await expect(page.getByRole('button', { name: 'Save my draft over the latest version', exact: true })).toBeVisible()
  await expect(input).toHaveValue('{"local":true}')
  expect(state.writes).toEqual([])
  await page.getByRole('button', { name: 'Save my draft over the latest version', exact: true }).click()
  await page.clock.runFor(1000)
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.writes[0]).toMatchObject({ expected_revision: 4, payload: { text: '{"local":true}' } })
})

test('the Documents creation dialog selects Dataset and the library submits its type filter and sort', async ({ page }) => {
  const state = await fixture(page)
  const requests = [], creations = []
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [] })
  await jsonRoute(page, '**/api/memory/documents/doc-a', { item: state.current(), agent_id: 7 })
  await page.route('**/api/memory/documents/library', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { entries: creations.length ? [{ item: state.current(), agent_ids: [7], writable_agent_ids: [7] }] : [], total: creations.length, keywords: [], has_more: false } })
  })
  await page.route('**/api/memory/documents', route => {
    creations.push(route.request().postDataJSON())
    return route.fulfill({ status: 201, json: state.current() })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  await page.getByRole('button', { name: 'Create document', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Owner', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Alice' }).click()
  await dialog.getByRole('textbox', { name: 'Title', exact: true }).fill('Scenarios')
  await dialog.getByRole('combobox', { name: 'Document type', exact: true }).click()
  await page.getByRole('option', { name: 'Dataset', exact: true }).click()
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect.poll(() => creations).toHaveLength(1)
  expect(creations[0]).toMatchObject({ document_type: 'dataset', title: 'Scenarios' })
  await expect(page.getByRole('textbox', { name: 'Content', exact: true })).toHaveValue(state.current().payload.text)
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('combobox', { name: 'Document type', exact: true }).click()
  await page.getByRole('option', { name: 'Dataset', exact: true }).click()
  await page.getByRole('combobox', { name: 'Sort by', exact: true }).click()
  await page.getByRole('option', { name: 'Document type', exact: true }).click()
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ document_type: 'dataset', sort_by: 'document_type', offset: 0 })
})
