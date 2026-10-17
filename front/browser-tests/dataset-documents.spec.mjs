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
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments*', [])
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { item: current, agent_id: 7 } })
    const body = route.request().postDataJSON()
    writes.push(body)
    current = { ...current, ...body, revision: current.revision + 1, lock_version: current.lock_version + 1 }
    return route.fulfill({ json: current })
  })
  return { writes, current: () => current, remote: value => { current = { ...current, ...value } } }
}

test('Documents creates editorial content and keeps Dataset creation out of its library', async ({ page }) => {
  const state = await fixture(page)
  state.remote({ document_type: 'html', media_type: 'text/html', content_profile_version: 1,
    payload: { text: '<p>Synthetic document</p>' } })
  // Creation must work even before the page's independent Agent catalogue arrives.
  let releaseAgents
  const agentsReady = new Promise(resolve => { releaseAgents = resolve })
  await page.route('**/api/agents?*', async route => { await agentsReady; return route.fallback() })
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', {
    agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }],
    users: [{ id: 1, kind: 'user', label: 'Synthetic owner', subtitle: '', avatar_url: null, is_current_user: true }],
  })
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
  await dialog.getByRole('textbox', { name: 'Title', exact: true }).fill('Scenarios')
  await expect(dialog.getByRole('combobox', { name: 'Document type', exact: true })).toHaveCount(0)
  try {
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()
    await expect.poll(() => creations).toHaveLength(1)
    expect(creations[0]).toMatchObject({ document_type: 'html', title: 'Scenarios', owner_kind: 'user', owner_id: 1, actor_agent_id: 7 })
  } finally { releaseAgents() }
  await expect(page.locator('.ck-editor__editable')).toContainText('Synthetic document')
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Document type', exact: true })).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Sort by', exact: true }).click()
  await expect(page.getByRole('option', { name: 'Document type', exact: true })).toHaveCount(0)
  await page.getByRole('option', { name: 'Title', exact: true }).click()
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ sort_by: 'title', offset: 0 })
  expect(requests.at(-1)).not.toHaveProperty('document_type')
})

for (const component of ['DocumentEditor', 'DocumentLibraryPage']) {
  test(`a historical Dataset opens its canonical editor from ${component}`, async ({ page }) => {
    const id = '00000000-0000-4000-8000-000000000001'
    await jsonRoute(page, '**/api/agents?*', [agent])
    await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [] })
    await jsonRoute(page, '**/api/memory/documents/library', { entries: [], total: 0, has_more: false, keywords: [] })
    await jsonRoute(page, `**/api/memory/documents/${id}*`, { resource_type: 'dataset', resource_uri: `data://${id}` })
    await mount(page, `app/memory/components/${component}.vue`, {
      props: component === 'DocumentEditor' ? { documentId: id, agentId: null } : {},
      route: `/documents?document_id=${id}`, privileges: ['MEMORY_EDIT', 'DATASET_READ'],
    })
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(`/dataset/${id}`)
    await expect(page.locator('.document-editor-fields')).toHaveCount(0)
  })
}

test('a cached Dataset seed cannot render inside the Document editor', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000002'
  await jsonRoute(page, '**/api/agents?*', [agent])
  await mount(page, 'app/memory/components/DocumentEditor.vue', {
    props: { documentId: id, agentId: null, initialDocument: { ...document, id, document_type: 'dataset' } },
  })
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(`/dataset/${id}`)
  await expect(page.locator('.document-editor-fields')).toHaveCount(0)
})

test('an unauthorized legacy reference stays denied without exposing a Dataset target', async ({ page }) => {
  await jsonRoute(page, '**/api/agents?*', [agent])
  await page.route('**/api/memory/documents/doc-a*', route => route.fulfill({ status: 403, json: { detail: 'Denied' } }))
  await mount(page, 'app/memory/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: null } })
  await expect(page.getByRole('alert')).toBeVisible()
  expect(await page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/')
})

test('a live Dataset attachment keeps its identity and recovers a concurrent Document update', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000003'
  let state = { items: [], lock_version: 3 }, fail = true
  const writes = []
  await jsonRoute(page, '**/api/datasets?*', { items: [{ id, uri: `data://${id}`, title: 'Synthetic budget' }], total: 1 })
  await page.route('**/api/memory/documents/doc-a/dataset-attachments**', route => {
    const method = route.request().method()
    if (method === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body)
      if (fail) { fail = false; state.lock_version = 4; return route.fulfill({ status: 409, json: { detail: 'Document changed' } }) }
      state = { items: [{ uri: `data://${id}`, title: 'Synthetic budget', available: true }], lock_version: 5 }
    } else if (method === 'DELETE') state = { items: [], lock_version: 6 }
    return route.fulfill({ json: state })
  })
  await mount(page, 'app/memory/components/DocumentDatasetAttachments.vue', { props: { documentId: 'doc-a', agentId: 7, editable: true } })
  await page.getByRole('button', { name: 'Attach a Dataset', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Dataset', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic budget', exact: true }).click()
  await dialog.getByRole('button', { name: 'Attach', exact: true }).click()
  await expect(dialog.getByRole('alert')).toBeVisible()
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await dialog.getByRole('button', { name: 'Attach', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toEqual([{ dataset_id: id, expected_lock_version: 3 }, { dataset_id: id, expected_lock_version: 4 }])
  await expect(page.getByRole('link', { name: 'Synthetic budget', exact: true })).toHaveAttribute('href', `/dataset/${id}`)
  await page.getByRole('button', { name: 'Detach Synthetic budget', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Synthetic budget', exact: true })).toHaveCount(0)
})

test('the native Dataset editor preserves invalid JSON drafts and writes valid source through Dataset API', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000004'
  let current = { id, uri: `data://${id}`, title: 'Synthetic values', content: '{"amount":0}', revision: 1,
    lock_version: 1, can_write: true, can_manage: true, can_delete: true, read_only: false, global_access: 0, group_access: 0, keywords: [] }
  const writes = []
  await jsonRoute(page, `**/api/datasets/${id}`, current)
  await jsonRoute(page, `**/api/datasets/${id}/sharing`, { lock_version: 1, can_manage: true, level: 'private', can_write: false,
    grants: [], options: [], owner: { kind: 'agent', id: 7, label: 'Synthetic owner', can_write: true }, owner_groups: [] })
  await page.route(`**/api/datasets/${id}/content`, route => {
    const data = route.request().postDataJSON(); writes.push(data)
    current = { ...current, content: data.content, revision: 2, lock_version: 2 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'app/dataset/components/DatasetEditor.vue', { props: { id }, privileges: ['DATASET_EDIT'] })
  const input = page.getByRole('textbox', { name: 'JSON content', exact: true })
  await input.fill('{')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(input).toHaveValue('{')
  expect(writes).toEqual([])
  const source = '{\n "amount": 1200, "literal": "<b>Data</b>"\n}\n'
  await input.fill(source)
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ content: source, expected_revision: 1 })
  await expect(input).toHaveValue(source)
})
