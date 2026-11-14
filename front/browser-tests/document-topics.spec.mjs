import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

async function fixture(page) {
  const entry = (id, title, topic, keywords) => ({ item: { ...document, id, title, topic_id: topic,
    keywords, lock_version: 1, access: { can_read: true, can_write: true } },
    agent_ids: [7], writable_agent_ids: [7], user_access: { can_read: true, can_write: true }, tags: [] })
  const values = [entry('plan', 'Synthetic plan', 'alpha', ['shared', 'source', 'retained']),
    entry('figures', 'Synthetic figures', 'beta', ['shared', 'target']),
    entry('plain', 'Synthetic plain', 'alpha', []), entry('inbox', 'Synthetic inbox', null, ['retained'])]
  const writes = [], reads = [], catalogs = [], ownerWrites = [], keywordWrites = []
  const profile = { id: 1, email: 'synthetic-reader@example.test', document_library_mode: 'folders' }
  const topicDefinitions = ['alpha', 'beta'].map(id => ({ id, title: id === 'alpha' ? 'Synthetic Alpha' : 'Synthetic Beta', revision: 1, description: '', keywords: [] }))
  const preferences = []
  let reject = false, failCatalog = false, rejectPreference = false, rejectKeywords = false
  values[1].item.owner_agent_id = 8
  values[3].item.owner_agent_id = null; values[3].item.owner_user_id = 1
  await jsonRoute(page, '**/api/topics/keywords', [])
  await page.route('**/api/topics?*', route => route.fulfill({ json: { items: topicDefinitions, total: topicDefinitions.length } }))
  for (const id of ['alpha', 'beta']) await page.route(`**/api/topics/${id}`, route => {
    const topic = topicDefinitions.find(topic => topic.id === id)
    if (route.request().method() === 'PUT') { Object.assign(topic, route.request().postDataJSON()); topic.revision++ }
    if (route.request().method() === 'DELETE') {
      for (const { item } of values) if (item.topic_id === id) { item.topic_id = null; item.lock_version++ }
      topicDefinitions.splice(topicDefinitions.indexOf(topic), 1)
      return route.fulfill({ status: 204 })
    }
    return route.fulfill({ json: topic })
  })
  await page.route('**/api/topics/*/merge', route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2), target = route.request().postDataJSON().target_topic_id
    for (const { item } of values) if (item.topic_id === id) { item.topic_id = target; item.lock_version++ }
    topicDefinitions.splice(topicDefinitions.findIndex(topic => topic.id === id), 1)
    return route.fulfill({ json: { moved_memory_links: 0 } })
  })
  await page.route('**/api/auth/me', route => {
    const values = route.request().postDataJSON(); preferences.push(values)
    if (rejectPreference) return route.fulfill({ status: 503, json: { detail: 'Synthetic preference failure' } })
    Object.assign(profile, values)
    return route.fulfill({ json: profile })
  })
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [{ id: 'folder', name: 'Synthetic manual folder', parent_id: null }] })
  await page.route(/\/api\/agents\/7\/avatar(?:\?.*)?$/, route => route.fulfill({ contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 26 26"><rect width="26" height="26" fill="#087FF5"/><circle cx="13" cy="9" r="5" fill="white"/><path d="M3 26v-3a10 10 0 0 1 20 0v3" fill="white"/></svg>' }))
  for (const entry of values) await jsonRoute(page, `**/api/documents/${entry.item.id}`, { item: entry.item, agent_id: 7 })
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Synthetic owner Alpha' }, { id: 8, kind: 'agent', label: 'Synthetic owner Beta' }], users: [{ id: 1, kind: 'user', label: 'Synthetic reader' }] })
  await page.route('**/api/documents/*/owner', route => {
    const body = route.request().postDataJSON(); ownerWrites.push(body)
    const id = new URL(route.request().url()).pathname.split('/').at(-2)
    const item = values.find(entry => entry.item.id === id).item
    if (body.expected_lock_version !== item.lock_version) return route.fulfill({ status: 409, json: { detail: 'Synthetic version conflict' } })
    item.owner_agent_id = body.kind === 'agent' ? body.id : null; item.owner_user_id = body.kind === 'user' ? body.id : null
    item.keywords = body.keywords ?? item.keywords; item.lock_version++
    return route.fulfill({ json: item })
  })
  await page.route('**/api/documents/library/keywords', route => {
    const body = route.request().postDataJSON(); keywordWrites.push(body)
    if (rejectKeywords) return route.fulfill({ status: 409, json: { detail: 'Synthetic keyword conflict' } })
    for (const ref of body.documents) {
      const item = values.find(entry => entry.item.id === ref.id).item
      item.keywords = [...new Set([...item.keywords.filter(keyword => !body.source_keywords.includes(keyword)), ...(body.keyword ? [body.keyword] : [])])]
      item.lock_version++
    }
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/topics/document-library', route => {
    catalogs.push('topics')
    if (failCatalog) { failCatalog = false; return route.fulfill({ status: 503, json: { detail: 'Synthetic failure' } }) }
    return route.fulfill({ json: topicDefinitions.map(({ id, title }) => {
      const documents = values.filter(entry => entry.item.topic_id === id)
      return { id, title,
        keywords: [...new Set(documents.flatMap(entry => entry.item.keywords))].sort(),
        document_count: documents.length, without_keywords_count: documents.filter(entry => !entry.item.keywords.length).length }
    }).filter(branch => branch.document_count) })
  })
  await page.route('**/api/documents/library/agents', route => {
    catalogs.push('agents')
    if (failCatalog) { failCatalog = false; return route.fulfill({ status: 503, json: { detail: 'Synthetic failure' } }) }
    return route.fulfill({ json: [7, 8].map(id => {
    const documents = values.filter(entry => entry.item.owner_agent_id === id)
    return { id, title: id === 7 ? 'Synthetic owner Alpha' : 'Synthetic owner Beta', has_avatar: id === 7,
      keywords: [...new Set(documents.flatMap(entry => entry.item.keywords))].sort(), document_count: documents.length,
      without_keywords_count: documents.filter(entry => !entry.item.keywords.length).length }
  }) }) })
  await page.route('**/api/documents/library', route => {
    const request = route.request().postDataJSON(); reads.push(request)
    const matching = values.filter(({ item }) => {
      if (request.document_ids && !request.document_ids.includes(item.id)) return false
      if (request.classification === 'root' || request.tag_id) return false
      if (request.topic_id && item.topic_id !== request.topic_id) return false
      if (request.topic_classification === 'unclassified' && item.topic_id !== null) return false
      if (request.agent_classification === 'unclassified' && item.owner_agent_id !== null) return false
      if (request.owner_kind === 'agent' && item.owner_agent_id !== request.owner) return false
      if (request.without_keywords && item.keywords.length) return false
      return (!request.keyword || item.keywords.includes(request.keyword)) && (!request.query || item.title.includes(request.query))
    })
    return route.fulfill({ json: { entries: matching.slice(request.offset, request.offset + request.limit),
      total: matching.length, has_more: matching.length > request.offset + request.limit, keywords: [] } })
  })
  await page.route('**/api/topics/documents/*/classification', route => {
    const request = route.request().postDataJSON(); writes.push(request)
    if (reject) return route.fulfill({ status: 409, json: { detail: 'Synthetic conflict' } })
    const id = new URL(route.request().url()).pathname.split('/').at(-2)
    const item = values.find(entry => entry.item.id === id).item
    item.topic_id = request.topic_id; item.lock_version += 1
    item.keywords = [...new Set([...(request.clear_keywords ? [] : item.keywords.filter(keyword => keyword !== request.source_keyword)), ...(request.keyword ? [request.keyword] : [])])]
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/topics/documents/classification-batch', route => {
    const { documents } = route.request().postDataJSON()
    if (reject) return route.fulfill({ status: 409, json: { detail: 'Synthetic conflict' } })
    for (const request of documents) {
      writes.push(request)
      const item = values.find(entry => entry.item.id === request.id).item
      item.topic_id = request.topic_id; item.lock_version++
      item.keywords = [...new Set([...(request.clear_keywords ? [] : item.keywords.filter(keyword => keyword !== request.source_keyword)), ...(request.keyword ? [request.keyword] : [])])]
    }
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/documents/library/owners', route => {
    const { documents } = route.request().postDataJSON()
    for (const request of documents) {
      ownerWrites.push(request)
      const item = values.find(entry => entry.item.id === request.document_id).item
      item.owner_agent_id = request.kind === 'agent' ? request.id : null; item.owner_user_id = request.kind === 'user' ? request.id : null
      item.keywords = request.keywords ?? item.keywords; item.lock_version++
    }
    return route.fulfill({ status: 204 })
  })
  return { values, writes, reads, catalogs, ownerWrites, keywordWrites, profile, preferences, reject(value) { reject = value }, rejectKeywords(value) { rejectKeywords = value }, rejectPreference(value) { rejectPreference = value }, failCatalog() { failCatalog = true } }
}

for (const mode of ['topics', 'agents']) test(`${mode} tag changes preserve loaded rows and never reload unrelated branches`, async ({ page }) => {
  const data = await fixture(page)
  data.profile.document_library_mode = mode
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, user: data.profile,
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '500px' } })
  const tree = page.getByRole('tree', { name: mode === 'topics' ? 'Topics' : 'Agents', exact: true })
  await tree.getByText(mode === 'topics' ? 'Synthetic Alpha' : 'Synthetic owner Alpha', { exact: true }).click()
  await tree.getByText(mode === 'topics' ? 'Synthetic Beta' : 'Synthetic owner Beta', { exact: true }).click()
  await tree.getByText('All documents', { exact: true }).first().click()
  await tree.getByText('target', { exact: true }).click()
  const plan = tree.getByText('Synthetic plan', { exact: true })
  const figures = tree.getByText('Synthetic figures', { exact: true })
  await expect(figures).toBeVisible()
  const retainedRows = [await plan.elementHandle(), await figures.elementHandle()]
  await tree.evaluate(element => {
    window.removedTreeDocuments = []
    window.treeObserver = new MutationObserver(records => {
      for (const record of records) for (const removed of record.removedNodes) {
        if (removed instanceof Element && (removed.matches('.topic-document-row') || removed.querySelector('.topic-document-row'))) window.removedTreeDocuments.push(removed.textContent)
      }
    })
    window.treeObserver.observe(element, { childList: true, subtree: true })
  })
  data.reads.length = 0
  data.values[0].item.keywords = ['shared', 'retained', 'new-label']; data.values[0].item.lock_version++
  await page.evaluate(() => window.testApp.emitSocket('document.classification', { data: { user_id: 1, document_ids: ['plan'], list_changed: true } }))
  await expect(tree.getByText('new-label', { exact: true })).toBeVisible()
  await expect(tree.getByText('source', { exact: true })).toHaveCount(0)
  await expect(plan).toBeVisible()
  expect(data.reads.filter(request => request.topic_id || request.owner_kind === 'agent')).toEqual([])
  for (const row of retainedRows) expect(await row.evaluate(element => element.isConnected)).toBe(true)
  expect(await page.evaluate(() => window.removedTreeDocuments)).toEqual([])
  await tree.getByText('new-label', { exact: true }).click()
  await expect(plan).toHaveCount(2)
  const reads = data.reads.length, catalogs = data.catalogs.length
  await page.getByRole('tab', { name: 'Folders', exact: true }).click()
  await page.getByRole('tab', { name: mode === 'topics' ? 'Topics' : 'Agents', exact: true }).click()
  await expect(plan).toHaveCount(2)
  expect(data.catalogs).toHaveLength(catalogs)
  expect(data.reads.slice(reads).filter(request => request.topic_id || request.owner_kind === 'agent')).toEqual([])
  for (const row of retainedRows) expect(await row.evaluate(element => element.isConnected)).toBe(true)
  data.failCatalog(); data.reads.length = 0
  data.values[0].item.keywords = ['shared', 'retained', 'renamed']; data.values[0].item.lock_version++
  await page.evaluate(() => window.testApp.emitSocket('document.classification', { data: { user_id: 1, document_ids: ['plan'], list_changed: true } }))
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  for (const row of retainedRows) expect(await row.evaluate(element => element.isConnected)).toBe(true)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(tree.getByText('renamed', { exact: true })).toBeVisible()
  expect(data.reads.filter(request => request.topic_id || request.owner_kind === 'agent')).toEqual([])
  for (const row of retainedRows) expect(await row.evaluate(element => element.isConnected)).toBe(true)
})

test('topic menus edit, merge a selection and delete topics while preserving documents', async ({ page }) => {
  const data = await fixture(page)
  data.profile.document_library_mode = 'topics'
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, user: data.profile,
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '500px' } })
  const tree = page.getByRole('tree', { name: 'Topics', exact: true })
  await tree.getByText('Synthetic Beta', { exact: true }).click()
  await tree.getByText('target', { exact: true }).click()
  const retained = await tree.getByText('Synthetic figures', { exact: true }).elementHandle()
  await tree.getByText('Synthetic Alpha', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Edit', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Dossier', { exact: true }).fill('Renamed subject')
  await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
  await expect(tree.getByText('Renamed subject', { exact: true })).toBeVisible()
  expect(await retained.evaluate(element => element.isConnected)).toBe(true)
  await tree.getByText('Renamed subject', { exact: true }).click({ modifiers: ['Control'] })
  await tree.getByText('Synthetic Beta', { exact: true }).click({ modifiers: ['Shift'] })
  await tree.getByText('Renamed subject', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Merge topics', exact: true }).click()
  await page.getByRole('dialog').getByRole('combobox', { name: 'Destination', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic Beta', exact: true }).click()
  data.reads.length = 0
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(tree.getByText('Renamed subject', { exact: true })).toHaveCount(0)
  expect(data.values[0].item.topic_id).toBe('beta')
  expect(data.reads.filter(request => request.topic_id === 'beta')).toEqual([])
  expect(await retained.evaluate(element => element.isConnected)).toBe(true)
  await tree.getByText('Synthetic Beta', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(data.values[0].item.topic_id).toBe('beta')
  await tree.getByText('Synthetic Beta', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(tree.getByText('Synthetic Beta', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('list', { name: 'Unclassified documents', exact: true }).getByText('Synthetic plan', { exact: true })).toBeVisible()
  expect(data.values[0].item.keywords).toEqual(['shared', 'source', 'retained'])
})

test('dragging selected tag branches prepares a confirmed merge and keyboard menus remain usable', async ({ page }) => {
  const data = await fixture(page)
  data.profile.document_library_mode = 'topics'
  await page.goto('/test-support/browser/index.html')
  await page.evaluate(() => localStorage.setItem('galaris:document-library-split:1', '75'))
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, user: data.profile,
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '500px' } })
  const tree = page.getByRole('tree', { name: 'Topics', exact: true })
  await tree.getByText('Synthetic Alpha', { exact: true }).click()
  await tree.getByText('Synthetic Beta', { exact: true }).click()
  await tree.getByText('source', { exact: true }).click({ modifiers: ['Control'] })
  await tree.getByText('retained', { exact: true }).click({ modifiers: ['Control'] })
  await tree.getByText('source', { exact: true }).dragTo(tree.getByText('target', { exact: true }))
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('combobox', { name: 'Destination', exact: true })).toHaveValue('target')
  expect(data.keywordWrites).toHaveLength(0)
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(tree.getByText('source', { exact: true })).toHaveCount(0)
  expect(data.values[0].item.keywords).toEqual(['shared', 'target'])
  expect(data.values[0].item.topic_id).toBe('alpha')
  const target = tree.getByLabel('target', { exact: true }).first()
  await target.focus(); await target.press('Shift+F10')
  await expect(page.getByRole('menuitem', { name: 'Rename', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
})

for (const mode of ['topics', 'agents']) test(`${mode} supports moving a document selection and preserves unrelated tree rows`, async ({ page }) => {
  await page.setViewportSize({ width: mode === 'agents' ? 390 : 1280, height: 1000 })
  const data = await fixture(page)
  data.profile.document_library_mode = mode
  // Keep both expanded source and destination branches in the drag viewport.
  await page.goto('/test-support/browser/index.html')
  await page.evaluate(() => localStorage.setItem('galaris:document-library-split:1', '75'))
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, user: data.profile,
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '100%' } })
  const tree = page.getByRole('tree', { name: mode === 'topics' ? 'Topics' : 'Agents', exact: true })
  await tree.getByText(mode === 'topics' ? 'Synthetic Alpha' : 'Synthetic owner Alpha', { exact: true }).click()
  await tree.getByText(mode === 'topics' ? 'Synthetic Beta' : 'Synthetic owner Beta', { exact: true }).click()
  await tree.getByText('All documents', { exact: true }).first().click()
  await tree.getByText('target', { exact: true }).click()
  const plan = tree.getByText('Synthetic plan', { exact: true }), plain = tree.getByText('Synthetic plain', { exact: true })
  const retained = await tree.getByText('Synthetic figures', { exact: true }).elementHandle()
  await plan.click(); await plain.click({ modifiers: ['Shift'] })
  await expect(tree.locator('.document-row[aria-selected="true"]')).toHaveCount(2)
  await plan.dragTo(tree.getByText('target', { exact: true }))
  await expect.poll(() => mode === 'topics' ? data.writes.length : data.ownerWrites.length).toBe(2)
  for (const item of [data.values[0].item, data.values[2].item]) {
    expect(mode === 'topics' ? item.topic_id : item.owner_agent_id).toBe(mode === 'topics' ? 'beta' : 8)
    expect(item.keywords).toContain('target')
  }
  await expect(plan).toBeVisible(); await expect(plain).toBeVisible()
  expect(await retained.evaluate(element => element.isConnected)).toBe(true)
  await expect(tree).toHaveAttribute('aria-busy', 'false')
  await plan.click(); await plain.click({ modifiers: ['Control'] })
  // Adjacent targets need a second pointer move after native dragstart in Chromium.
  await plan.hover(); await page.mouse.down()
  await tree.getByText('Without a tag', { exact: true }).last().hover()
  await tree.getByText('Without a tag', { exact: true }).last().hover()
  await page.mouse.up()
  await expect.poll(() => data.values[0].item.keywords).toEqual([])
  await expect.poll(() => data.values[2].item.keywords).toEqual([])
})

for (const mode of ['topics', 'agents']) test(`${mode} context menus move the selected documents only after confirmation`, async ({ page }) => {
  const data = await fixture(page)
  data.profile.document_library_mode = mode
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, user: data.profile,
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '500px' } })
  const tree = page.getByRole('tree', { name: mode === 'topics' ? 'Topics' : 'Agents', exact: true })
  await tree.getByText(mode === 'topics' ? 'Synthetic Alpha' : 'Synthetic owner Alpha', { exact: true }).click()
  await tree.getByText('All documents', { exact: true }).click()
  const plan = tree.getByText('Synthetic plan', { exact: true }), plain = tree.getByText('Synthetic plain', { exact: true })
  await plan.click(); await plain.click({ modifiers: ['Control'] })
  await plan.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Move selected documents', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(mode === 'topics' ? 'Synthetic Alpha' : 'Synthetic owner Alpha', { exact: true })).toBeVisible()
  expect(data.writes).toHaveLength(0); expect(data.ownerWrites).toHaveLength(0)
  await dialog.getByRole('combobox', { name: 'Destination', exact: true }).click()
  await page.getByRole('option', { name: mode === 'topics' ? 'Synthetic Beta' : 'Synthetic owner Beta', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Keywords', exact: true }).click()
  await page.getByRole('option', { name: 'Without a tag', exact: true }).click()
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect.poll(() => mode === 'topics' ? data.writes.length : data.ownerWrites.length).toBe(2)
  for (const { item } of [data.values[0], data.values[2]]) {
    expect(mode === 'topics' ? item.topic_id : item.owner_agent_id).toBe(mode === 'topics' ? 'beta' : 8)
    expect(item.keywords).toEqual([])
  }
})

for (const mode of ['topics', 'agents']) test(`${mode} merges selected tags, retries conflicts and keeps documents mounted`, async ({ page }, testInfo) => {
  const data = await fixture(page)
  data.profile.document_library_mode = mode
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, user: data.profile,
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '500px' } })
  const tree = page.getByRole('tree', { name: mode === 'topics' ? 'Topics' : 'Agents', exact: true })
  await tree.getByText(mode === 'topics' ? 'Synthetic Alpha' : 'Synthetic owner Alpha', { exact: true }).click()
  await tree.getByText('All documents', { exact: true }).click()
  const row = await tree.getByText('Synthetic plan', { exact: true }).elementHandle()
  await tree.getByText('source', { exact: true }).click({ modifiers: ['Control'] })
  await tree.getByText('retained', { exact: true }).click({ modifiers: ['Control'] })
  await tree.getByText('source', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Merge tags', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const destination = dialog.getByRole('combobox', { name: 'Destination', exact: true })
  await expect(destination).toHaveValue('retained')
  await destination.click()
  await expect(page.getByRole('option')).toHaveText(['retained', 'source'])
  await page.screenshot({ path: testInfo.outputPath('merge-selected-tags.png'), animations: 'disabled' })
  await page.getByRole('option', { name: 'source', exact: true }).click()
  data.rejectKeywords(true)
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Synthetic keyword conflict')
  expect(data.values[0].item.keywords).toEqual(['shared', 'source', 'retained'])
  expect(await row.evaluate(element => element.isConnected)).toBe(true)
  data.rejectKeywords(false); data.reads.length = 0
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(tree.getByText('source', { exact: true })).toBeVisible()
  expect(data.values[0].item.keywords).toEqual(['shared', 'source'])
  expect(data.values[3].item.keywords).toEqual(['source'])
  expect(data.reads.filter(request => request.topic_id || request.owner_kind === 'agent')).toEqual([])
  expect(await row.evaluate(element => element.isConnected)).toBe(true)
  await tree.getByText('source', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(tree.getByText('source', { exact: true })).toHaveCount(0)
  expect(data.values[0].item.keywords).toEqual(['shared'])
  expect(await row.evaluate(element => element.isConnected)).toBe(true)
})

for (const width of [390, 1280]) test(`topic/tag navigation preserves other tags and manual folders at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const data = await fixture(page)
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null },
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '100%' } })
  await expect(page.getByText('Synthetic manual folder', { exact: true })).toBeVisible()
  const mode = page.getByRole('tab', { name: 'Topics', exact: true })
  await mode.focus(); await mode.press('Enter')
  const tree = page.getByRole('tree', { name: 'Topics', exact: true })
  await tree.getByText('Synthetic Alpha', { exact: true }).click()
  await tree.getByText('Synthetic Beta', { exact: true }).click()
  // The same tag remains independently available under both topics.
  await expect(tree.getByText('shared', { exact: true })).toHaveCount(2)
  await tree.getByText('source', { exact: true }).click()
  await tree.getByText('target', { exact: true }).click()
  const plan = tree.getByText('Synthetic plan', { exact: true })
  await plan.dragTo(tree.getByText('target', { exact: true }))
  await expect.poll(() => data.values[0].item.topic_id).toBe('beta')
  expect(data.values[0].item.keywords).toEqual(['shared', 'retained', 'target'])
  expect(data.writes[0]).toMatchObject({ expected_topic_id: 'alpha', source_keyword: 'source', keyword: 'target' })
  await expect(plan).toBeVisible()
  await plan.click()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').at(-1).value.item.id)).toBe('plan')
  const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
  await expect(list.getByText('Synthetic inbox', { exact: true })).toBeVisible()
  await expect(list.getByText('Synthetic figures', { exact: true })).toHaveCount(0)
  await plan.dragTo(list)
  await expect.poll(() => data.values[0].item.topic_id).toBeNull()
  expect(data.values[0].item.keywords).toEqual(['shared', 'retained', 'target'])
  await expect(list.getByText('Synthetic plan', { exact: true })).toBeVisible()
  await list.getByText('Synthetic inbox', { exact: true }).dragTo(tree.getByText('Synthetic Beta', { exact: true }))
  await expect.poll(() => data.values[3].item.topic_id).toBe('beta')
  expect(data.values[3].item.keywords).toEqual(['retained'])
  await tree.getByText('Without a tag', { exact: true }).first().click()
  await expect(tree.getByText('Synthetic plain', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('topics-light.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('topics-dark.png'), animations: 'disabled' })
  await page.getByRole('tab', { name: 'Folders', exact: true }).click()
  await expect(page.getByText('Synthetic manual folder', { exact: true })).toBeVisible()
  await expect(mode).toHaveAttribute('aria-selected', 'false')
})

test('topic navigation retries failed reads and reconciles a rejected drop without losing the document', async ({ page }) => {
  const data = await fixture(page)
  data.failCatalog()
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null },
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '900px', width: '500px' } })
  await page.getByRole('tab', { name: 'Topics', exact: true }).click()
  const tree = page.getByRole('tree', { name: 'Topics', exact: true })
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await tree.getByText('Synthetic Alpha', { exact: true }).click()
  await tree.getByText('source', { exact: true }).click()
  data.reject(true)
  await tree.getByText('Synthetic plan', { exact: true }).dragTo(tree.getByText('Synthetic Beta', { exact: true }))
  await expect(page.getByText('Unable to update your classification.', { exact: true })).toBeVisible()
  await expect(tree.getByText('Synthetic plan', { exact: true })).toBeVisible()
  expect(data.values[0].item.topic_id).toBe('alpha')
  data.reject(false)
  await tree.getByText('Synthetic plan', { exact: true }).dragTo(tree.getByText('Synthetic Beta', { exact: true }))
  await expect.poll(() => data.values[0].item.topic_id).toBe('beta')
})

test('read-only users can browse topics but cannot change classification', async ({ page }) => {
  const data = await fixture(page)
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null },
    privileges: ['DOCUMENT_ACCESS'], containerStyle: { height: '900px', width: '500px' } })
  await page.getByRole('tab', { name: 'Topics', exact: true }).click()
  const tree = page.getByRole('tree', { name: 'Topics', exact: true })
  await tree.getByText('Synthetic Alpha', { exact: true }).click()
  await tree.getByText('source', { exact: true }).click()
  await tree.getByText('Synthetic plan', { exact: true }).dragTo(tree.getByText('Synthetic Beta', { exact: true }))
  expect(data.writes).toEqual([])
})

for (const total of [501, 1_000_000]) test(`virtual ranges open only the requested 100 documents out of ${total} and preserve deletion rollback`, async ({ page }, testInfo) => {
  await jsonRoute(page, '**/api/topics/document-library', [{ id: 'alpha', title: 'Synthetic large topic', keywords: ['shared'],
    document_count: total, without_keywords_count: 0 }])
  const offsets = []
  const rangeReads = []
  await page.route('**/api/documents/library', route => {
    const request = route.request().postDataJSON(); offsets.push(request.offset)
    if (request.include_tree_ranges) rangeReads.push(request)
    expect(request.limit).toBe(100)
    const entries = Array.from({ length: Math.min(request.limit, total - request.offset) }, (_, index) => {
      const position = request.offset + index
      return { item: { ...document, id: `synthetic-${position}`, title: `Synthetic document ${position}`,
        topic_id: 'alpha', keywords: ['shared'], access: { can_read: true, can_write: false } }, agent_ids: [7], writable_agent_ids: [] }
    })
    return route.fulfill({ json: { entries, total, has_more: request.offset + entries.length < total, keywords: [] } })
  })
  await mount(page, 'app/document/components/DocumentTopicNavigation.vue', { props: { selectedDocumentId: null, busy: false, canDrop: false },
    privileges: ['DOCUMENT_ACCESS'] })
  await page.getByText('Synthetic large topic', { exact: true }).click()
  await page.getByText('shared', { exact: true }).click()
  await expect(page.getByText(total > 10_000 ? '1–10000' : '1–100', { exact: true })).toBeVisible()
  expect(offsets).toEqual([0])
  if (total > 10_000) {
    await page.getByText('990001–1000000', { exact: true }).click()
    await expect.poll(() => offsets).toEqual([0, 990_000])
    expect(rangeReads.at(-1).tree_range_size).toBe(10_000)
    expect(await page.locator('.document-topic-tree .document-row').count()).toBe(0)
  }
  const offset = Math.floor((total - 1) / 100) * 100
  await page.getByText(`${offset + 1}–${total}`, { exact: true }).click()
  const last = page.getByText(`Synthetic document ${total - 1}`, { exact: true })
  await expect(last).toBeAttached()
  expect(offsets).toEqual(total > 10_000 ? [0, 990_000, offset] : [0, offset])
  expect(await page.locator('.document-topic-tree .document-row').count()).toBeLessThanOrEqual(100)
  await page.evaluate(async identity => {
    const { useDocumentMutations } = await import('/app/document/stores/documentMutations.ts')
    window.undoSyntheticDeletion = useDocumentMutations(window.testApp.pinia).beginDeletion(identity)
  }, `synthetic-${total - 1}`)
  await expect(last).toHaveCount(0)
  await page.evaluate(() => window.undoSyntheticDeletion())
  await expect(last).toBeAttached()
  await page.screenshot({ path: testInfo.outputPath('virtual-topic-ranges-light.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('virtual-topic-ranges-dark.png'), animations: 'disabled' })
})

test('closing a topic cancels its pending virtual range and reopening restores that range', async ({ page }) => {
  await jsonRoute(page, '**/api/topics/document-library', [{ id: 'alpha', title: 'Synthetic topic', keywords: ['shared'], document_count: 301, without_keywords_count: 0 }])
  const offsets = []
  let release
  await page.route('**/api/documents/library', async route => {
    const body = route.request().postDataJSON(); offsets.push(body.offset)
    if (body.offset === 300 && offsets.filter(offset => offset === 300).length === 1) await new Promise(resolve => { release = resolve })
    return route.fulfill({ json: { entries: [{ item: { ...document, id: `range-${body.offset}`, title: `Synthetic range ${body.offset}`, topic_id: 'alpha', keywords: ['shared'] }, agent_ids: [7], writable_agent_ids: [] }], total: 301, keywords: [], has_more: body.offset < 300 } })
  })
  await mount(page, 'app/document/components/DocumentTopicNavigation.vue', { props: { selectedDocumentId: null, busy: false, canDrop: false }, privileges: ['DOCUMENT_ACCESS'] })
  await page.getByText('Synthetic topic', { exact: true }).click()
  await page.getByText('shared', { exact: true }).click()
  await page.getByText('301–301', { exact: true }).click()
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.getByText('Synthetic topic', { exact: true }).click()
  await page.getByText('Synthetic topic', { exact: true }).click()
  await expect(page.getByText('Synthetic range 300', { exact: true })).toBeVisible()
  expect(offsets).toEqual([0, 300, 300])
  release()
})

for (const width of [390, 1280]) test(`the saved agent view groups by owner and tag and preserves unassigned documents at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const data = await fixture(page)
  data.profile.document_library_mode = 'agents'
  const options = { props: { selectedDocumentId: null }, user: data.profile,
    privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '100%' } }
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', options)
  await expect(page.getByRole('tab', { name: 'Agents', exact: true })).toHaveAttribute('aria-selected', 'true')
  const tree = page.getByRole('tree', { name: 'Agents', exact: true })
  await tree.getByText('Synthetic owner Alpha', { exact: true }).click()
  await tree.getByText('Synthetic owner Beta', { exact: true }).click()
  await expect(tree.getByText('shared', { exact: true })).toHaveCount(2)
  await tree.getByText('Without a tag', { exact: true }).first().click()
  await expect(tree.getByText('Synthetic plain', { exact: true })).toBeVisible()
  await tree.getByText('Without a tag', { exact: true }).first().click()
  await tree.getByText('All documents', { exact: true }).first().click()
  const plan = tree.getByText('Synthetic plan', { exact: true })
  await expect(plan).toBeVisible()
  await plan.click()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').at(-1).value.item.id)).toBe('plan')
  await plan.dragTo(tree.getByText('Synthetic owner Beta', { exact: true }))
  expect(data.writes).toEqual([])
  await expect.poll(() => data.values[0].item.owner_agent_id).toBe(8)
  const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
  await expect(list.getByText('Synthetic inbox', { exact: true })).toBeVisible()
  await expect(list.getByText('Synthetic plan', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('agents-light.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('agents-dark.png'), animations: 'disabled' })
  await page.getByRole('tab', { name: 'Topics', exact: true }).click()
  await expect.poll(() => data.profile.document_library_mode).toBe('topics')
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { ...options, user: data.profile })
  await expect(page.getByRole('tab', { name: 'Topics', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tree', { name: 'Topics', exact: true })).toBeVisible()
})

test('a rejected preferred tab save returns to the saved view and supports retry', async ({ page }) => {
  const data = await fixture(page)
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null },
    privileges: ['DOCUMENT_ACCESS'], containerStyle: { height: '900px', width: '500px' } })
  data.rejectPreference(true)
  await page.getByRole('tab', { name: 'Agents', exact: true }).click()
  await expect(page.getByText('Unable to save your preferred tab. Try again.', { exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Folders', exact: true })).toHaveAttribute('aria-selected', 'true')
  data.rejectPreference(false)
  await page.getByRole('tab', { name: 'Agents', exact: true }).click()
  await expect.poll(() => data.profile.document_library_mode).toBe('agents')
  await expect(page.getByRole('tree', { name: 'Agents', exact: true })).toBeVisible()
})
