import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

async function openFolderIcon(button) {
  const row = button.locator('..')
  if (!await row.getByRole('textbox').count()) {
    await button.hover()
    await row.getByRole('button', { name: /^(Edit folder|Modifier le dossier) / }).click()
  }
  await button.click()
}

async function folderAction(page, folder, action) {
  await page.getByRole('button', { name: `Icon for folder ${folder}`, exact: true }).hover()
  await page.getByRole('button', { name: action, exact: true }).click()
}

async function editFolder(page, folder) {
  await folderAction(page, folder, `Edit folder ${folder}`)
}

async function toggleUnclassified(page) {
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('switch', { name: 'Unclassified', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('switch', { name: 'Unclassified', exact: true })).toHaveCount(0)
}

async function expectUnclassified(page, checked = true) {
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await expect(page.getByRole('switch', { name: 'Unclassified', exact: true })).toBeChecked({ checked })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('switch', { name: 'Unclassified', exact: true })).toHaveCount(0)
}

test('document icon changes synchronize across the list and tree, persist, reset and recover from errors', async ({ page }, testInfo) => {
  const icons = {}, writes = []
  let fail = false
  await page.route('**/api/memory/documents/icons/resolve', route => route.fulfill({ json: icons }))
  await page.route('**/api/memory/documents/doc-a/icon', route => {
    const data = route.request().postDataJSON(); writes.push(data)
    if (fail) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
    icons['doc-a'] = data.icon
    return route.fulfill({ json: data })
  })
  await fixture(page)
  const button = page.getByRole('button', { name: 'Icon for document Test document', exact: true })
  await expect(button.locator('.q-icon').first()).toHaveText('description')
  await button.click()
  await expect(page.getByLabel('Search icons', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'select'))).toEqual([])
  await expect(page.getByRole('combobox', { name: 'Icon library', exact: true })).toHaveValue('Unicode emoji')
  await page.getByRole('combobox', { name: 'Icon library', exact: true }).click()
  await expect(page.getByRole('option', { name: 'Folders', exact: true })).toHaveCount(0)
  await page.getByRole('option', { name: 'Unicode emoji', exact: true }).click()
  await page.getByLabel('Search icons', { exact: true }).fill('rocket')
  await page.getByRole('button', { name: 'Rocket', exact: true }).click()
  await expect(button).toContainText('🚀')
  await page.getByText('Test document', { exact: true }).dragTo(page.getByText('Work', { exact: true }))
  await toggleUnclassified(page)
  const treeIcon = page.getByRole('img', { name: 'Icon for document Test document', exact: true })
  await expect(button).toHaveCount(1)
  await expect(button).toContainText('🚀')
  await expect(treeIcon).toContainText('🚀')
  await treeIcon.click()
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').map(event => event.args[0].item.id))).toEqual(['doc-a'])
  fail = true
  await button.first().click()
  await page.getByRole('button', { name: 'Default icon', exact: true }).click()
  await expect(page.getByText('Unable to update the document icon.', { exact: true })).toBeVisible()
  await expect(button.first()).toContainText('🚀')
  await expect(treeIcon).toContainText('🚀')
  fail = false
  await page.getByRole('button', { name: 'Default icon', exact: true }).click()
  await expect(button.first().locator('.q-icon').first()).toHaveText('description')
  await expect(treeIcon.locator('.q-icon').first()).toHaveText('description')
  icons['doc-a'] = 'emoji:1F680'
  await mount(page, 'app/memory/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, containerStyle: { height: '760px', width: '400px' } })
  await page.getByText('Work', { exact: true }).click()
  await expect(treeIcon).toContainText('🚀')
  expect(writes).toEqual([{ icon: 'emoji:1F680' }, { icon: null }, { icon: null }])
  await page.screenshot({ path: testInfo.outputPath('personal-document-icons.png'), animations: 'disabled' })
})

test('late icon reads cannot undo a saved choice and session changes discard personal icons and pending writes', async ({ page }) => {
  let releaseRead, releaseWrite
  let firstRead = true
  await page.route('**/api/memory/documents/icons/resolve', async route => {
    if (firstRead) { firstRead = false; await new Promise(resolve => { releaseRead = resolve }); return route.fulfill({ json: { 'doc-a': 'emoji:1F600' } }) }
    return route.fulfill({ json: { 'doc-a': 'emoji:1F600' } })
  })
  await jsonRoute(page, '**/api/memory/documents/tag-icons', [])
  await page.route('**/api/memory/documents/doc-a/icon', async route => {
    const data = route.request().postDataJSON()
    if (data.icon === null) await new Promise(resolve => { releaseWrite = resolve })
    return route.fulfill({ json: data })
  })
  await mount(page, 'app/memory/components/DocumentIcon.vue', { props: { documentId: 'doc-a', title: 'Report' } })
  const button = page.getByRole('button', { name: 'Icon for document Report', exact: true })
  await expect.poll(() => Boolean(releaseRead)).toBe(true)
  await button.click()
  await page.getByRole('combobox', { name: 'Icon library', exact: true }).click()
  await page.getByRole('option', { name: 'Unicode emoji', exact: true }).click()
  await page.getByLabel('Search icons', { exact: true }).fill('rocket')
  await page.getByRole('button', { name: 'Rocket', exact: true }).click()
  await expect(button).toContainText('🚀')
  const readResponse = page.waitForResponse(response => response.url().endsWith('/documents/icons/resolve'))
  releaseRead()
  await (await readResponse).finished()
  await expect(button).toContainText('🚀')
  await button.click()
  await page.getByRole('button', { name: 'Default icon', exact: true }).click()
  await expect.poll(() => Boolean(releaseWrite)).toBe(true)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'other-user' })))
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await expect(button).toContainText('😀')
  const writeResponse = page.waitForResponse(response => response.url().endsWith('/documents/doc-a/icon'))
  releaseWrite()
  await (await writeResponse).finished()
  await expect(button).toBeEnabled()
  await expect(button).toContainText('😀')
})

async function fixture(page, locale = 'en') {
  const readOnlyDocument = { ...document, access: { can_read: true, can_write: false } }
  await jsonRoute(page, '**/api/memory/documents/doc-a', { item: readOnlyDocument, agent_id: 7 })
  let tags = [{ id: 'work', name: 'Work', parent_id: null, position: 1 }, { id: 'project', name: 'Project', parent_id: 'work', position: 1 }]
  const assignments = new Set()
  const requests = [], mutations = [], deletions = [], orders = []
  const icons = []
  await page.route('**/api/memory/documents/tag-icons', route => {
    if (route.request().method() === 'POST') {
      const icon = { id: 'custom-icon', ...route.request().postDataJSON() }
      icons.push(icon)
      return route.fulfill({ json: icon })
    }
    return route.fulfill({ json: icons })
  })
  await page.route('**/api/memory/documents/tags', route => {
    if (route.request().method() === 'POST') {
      const data = route.request().postDataJSON()
      const tag = { ...data, id: 'new-tag', position: Math.max(0, ...tags.filter(tag => tag.parent_id === data.parent_id).map(tag => tag.position)) + 1 }
      tags.push(tag); mutations.push(tag)
      return route.fulfill({ json: tag })
    }
    return route.fulfill({ json: { user_id: 1, tags } })
  })
  await page.route('**/api/memory/documents/tags/*', route => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').at(-1)
    if (route.request().method() === 'DELETE') {
      const branch = new Set([id])
      while (tags.some(tag => branch.has(tag.parent_id) && !branch.has(tag.id))) {
        tags.filter(tag => branch.has(tag.parent_id)).forEach(tag => branch.add(tag.id))
      }
      const documentCount = [...assignments].some(tag => branch.has(tag)) ? 1 : 0
      const deleted = url.searchParams.get('confirmed') === 'true' || (branch.size === 1 && !documentCount)
      deletions.push({ id, deleted })
      if (deleted) { tags = tags.filter(tag => !branch.has(tag.id)); if (documentCount) assignments.clear() }
      return route.fulfill({ json: { deleted, tag_count: branch.size, document_count: documentCount } })
    }
    const data = route.request().postDataJSON()
    mutations.push({ id, ...data }); tags = tags.map(tag => tag.id === id ? { ...tag, ...data } : tag)
    return route.fulfill({ json: tags.find(tag => tag.id === id) })
  })
  await page.route('**/api/memory/documents/doc-a/tags/*', route => {
    const id = route.request().url().split('/').at(-1)
    if (route.request().method() === 'DELETE') assignments.delete(id)
    else assignments.add(id)
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/memory/documents/order', route => {
    const data = route.request().postDataJSON(); orders.push(data)
    const moving = tags.find(tag => tag.id === data.node.id)
    const siblings = tags.filter(tag => tag.parent_id === data.parent_id && tag !== moving).sort((a, b) => a.position - b.position)
    siblings.splice(siblings.findIndex(tag => tag.id === data.anchor.id) + Number(data.after), 0, moving)
    siblings.forEach((tag, index) => { tag.position = index + 1 })
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/memory/documents/doc-a/tags', route => {
    assignments.clear()
    const { tag_id } = route.request().postDataJSON()
    if (tag_id) assignments.add(tag_id)
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/memory/documents/library', route => {
    const body = route.request().postDataJSON(); requests.push(body)
    const entry = { item: readOnlyDocument, agent_ids: [7, 8], writable_agent_ids: [], owner_label: 'Alice', tags: tags.filter(tag => assignments.has(tag.id)) }
    const match = (body.classification !== 'unclassified' || !assignments.size)
      && (body.classification !== 'classified' || assignments.size > 0)
      && (!body.tag_id || assignments.has(body.tag_id))
    return route.fulfill({ json: { entries: match ? [entry] : [], total: match ? 1 : 0, keywords: [], has_more: false,
      owners: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '' }] } })
  })
  await mount(page, 'app/memory/components/DocumentLibraryNavigation.vue', { locale, props: { selectedDocumentId: null }, containerStyle: { height: '760px', width: '400px', maxWidth: '100vw' } })
  await expect(page.getByText('Test document', { exact: true })).toHaveCount(1)
  return { requests, assignments, mutations, deletions, orders }
}

test('personal classification works for a read-only document by drag and survives reopening', async ({ page }, testInfo) => {
  const state = await fixture(page)
  await expectUnclassified(page)
  await expect(page.getByText('Alice', { exact: false })).toBeVisible()
  const row = page.getByText('Test document', { exact: true }).locator('xpath=ancestor::div[contains(@class,"q-item")][1]')
  await row.dragTo(page.getByText('Work', { exact: true }))
  await expect.poll(() => [...state.assignments]).toEqual(['work'])
  const orphans = page.getByLabel('Unclassified documents', { exact: true })
  await expect(orphans.getByText('Test document', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Documents in folder Work', { exact: true }).getByText('Test document', { exact: true })).toBeVisible()
  await toggleUnclassified(page)
  const allDocuments = page.getByLabel('All documents', { exact: true })
  await expect(allDocuments.getByText('Test document', { exact: true })).toBeVisible()
  await expect.poll(() => state.requests.filter(request => request.tag_id === null).at(-1)).toMatchObject({ classification: 'all', offset: 0 })
  await toggleUnclassified(page)
  await expect(orphans.getByText('Test document', { exact: true })).toHaveCount(0)
  await row.dragTo(page.getByText('Project', { exact: true }))
  await expect.poll(() => [...state.assignments]).toEqual(['project'])
  await expect(page.getByLabel('Documents in folder Project', { exact: true }).getByText('Test document', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('documents-in-folders.png'), animations: 'disabled' })
  await row.dragTo(orphans)
  await expect.poll(() => state.assignments.size).toBe(0)
  await expect(orphans.getByText('Test document', { exact: true })).toBeVisible()
  await page.getByText('Work', { exact: true }).click()
  await page.getByText('Work', { exact: true }).click()
  await expect(orphans.getByText('Test document', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('personal-documents.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(orphans.getByText('Test document', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('personal-documents-mobile-dark.png'), animations: 'disabled' })
})

test('classification refreshes only affected folders and keeps other documents usable', async ({ page }) => {
  const state = await fixture(page)
  state.assignments.add('work')
  const tags = [{ id: 'work', name: 'Work', parent_id: null }, { id: 'project', name: 'Project', parent_id: 'work' }, { id: 'other', name: 'Other', parent_id: null }]
  const requests = []
  let tagReads = 0, release, delayProject = false
  await jsonRoute(page, '**/api/memory/documents/root-doc', { item: { ...document, id: 'root-doc', title: 'Root report' }, agent_id: 7 })
  await page.route('**/api/memory/documents/tags', route => {
    tagReads++
    return route.fulfill({ json: { user_id: 1, tags } })
  })
  await page.route('**/api/memory/documents/library', async route => {
    const body = route.request().postDataJSON(); requests.push(body.tag_id)
    if (body.tag_id === 'project' && delayProject) await new Promise(resolve => { release = resolve })
    const entry = (id, title, tagIds = []) => ({ item: { ...document, id, title }, tags: tags.filter(tag => tagIds.includes(tag.id)), agent_ids: [7], writable_agent_ids: [] })
    const entries = body.tag_id === 'other' ? [entry('other-doc', 'Other report', ['other'])]
      : !body.tag_id ? [entry('root-doc', 'Root report')]
      : state.assignments.has(body.tag_id) ? [entry('doc-a', 'Test document', [...state.assignments])] : []
    if (body.tag_id === 'project') entries.push(entry('project-notes', 'Project notes', ['project']))
    return route.fulfill({ json: { entries, total: entries.length, keywords: [], has_more: false } })
  })
  await page.route('**/api/memory/documents/doc-a/tags', async route => {
    state.assignments.clear(); state.assignments.add(route.request().postDataJSON().tag_id)
    // The server notifies other tabs before the mutation's HTTP response arrives.
    await page.evaluate(() => window.testApp.emitSocket('memory.classification', { data: {
      user_id: 1, tag_ids: ['work', 'project'], document_ids: ['doc-a'], list_changed: false, tags_changed: false,
    } }))
    return route.fulfill({ status: 204 })
  })
  await mount(page, 'app/memory/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, containerStyle: { height: '760px', width: '400px' } })
  await page.getByText('Work', { exact: true }).click()
  await page.getByText('Project', { exact: true }).click()
  await expect(page.getByText('Project notes', { exact: true })).toBeVisible()
  await page.getByText('Other', { exact: true }).click()
  await expect(page.getByText('Other report', { exact: true })).toBeVisible()
  await expect(page.getByText('Test document', { exact: true })).toBeVisible()
  const other = await page.getByText('Other report', { exact: true }).elementHandle()
  requests.length = 0; tagReads = 0; delayProject = true
  await page.getByText('Test document', { exact: true }).dragTo(page.getByText('Project', { exact: true }))
  await expect.poll(() => Boolean(release)).toBe(true)
  await expect(page.getByText('Other report', { exact: true })).toBeVisible()
  expect(await other.evaluate(element => element.isConnected)).toBe(true)
  await page.getByText('Other report', { exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').at(-1)?.args[0].item.id)).toBe('other-doc')
  await page.getByText('Root report', { exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').at(-1)?.args[0].item.id)).toBe('root-doc')
  expect(requests.sort()).toEqual(['project', 'work'])
  expect(tagReads).toBe(0)
  delayProject = false; release()
  await expect(page.getByLabel('Documents in folder Project', { exact: true }).getByText('Test document', { exact: true })).toBeVisible()
  expect(await other.evaluate(element => element.isConnected)).toBe(true)
  requests.length = 0
  await page.evaluate(() => window.testApp.emitSocket('memory.classification', { data: {
    user_id: 1, tag_ids: [], document_ids: [], list_changed: true, tags_changed: false,
  } }))
  await expect.poll(() => requests).toEqual([null])
  expect(await other.evaluate(element => element.isConnected)).toBe(true)
  requests.length = 0; tagReads = 0
  await page.route('**/api/memory/documents/tags/work', route => {
    Object.assign(tags[0], route.request().postDataJSON())
    return route.fulfill({ json: tags[0] })
  })
  await editFolder(page, 'Work')
  await page.getByLabel('Name', { exact: true }).fill('Renamed work')
  await page.getByLabel('Name', { exact: true }).press('Enter')
  await expect(page.getByText('Renamed work', { exact: true })).toBeVisible()
  expect(tagReads).toBe(1)
  expect(requests).toEqual([])
  expect(await other.evaluate(element => element.isConnected)).toBe(true)
  // Rights changes must still discard visible snapshots, even when rereading is slow.
  let releaseAccess
  const gate = new Promise(resolve => { releaseAccess = resolve })
  await page.route('**/api/memory/documents/library', async route => {
    await gate
    await route.fulfill({ json: { entries: [], total: 0, keywords: [], has_more: false } })
  })
  await page.evaluate(() => window.testApp.emitSocket('memory.invalidate', { data: {} }))
  await expect(page.getByText('Other report', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Root report', { exact: true })).toHaveCount(0)
  releaseAccess()
})

test('compact filters keep the orphan list unclassified while filtering owner, dates and sorting', async ({ page }) => {
  const { requests } = await fixture(page)
  // Filters describe local calendar days, regardless of the browser/container timezone.
  const dates = await page.evaluate(() => ({
    created_from: new Date(2026, 8, 1).toISOString(), created_until: new Date(2026, 8, 15).toISOString(),
    updated_from: new Date(2026, 8, 2).toISOString(), updated_until: new Date(2026, 8, 15).toISOString(),
  }))
  await expect(page.getByLabel('Created from', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('combobox', { name: 'Owner type', exact: true }).click()
  await page.getByRole('option', { name: 'Agent', exact: true }).click()
  await page.getByRole('combobox', { name: 'Owner', exact: true }).click()
  await page.getByRole('option', { name: 'Alice', exact: true }).click()
  await page.getByLabel('Created from', { exact: true }).fill('2026-09-01')
  await page.getByLabel('Created through', { exact: true }).fill('2026-09-14')
  await page.getByLabel('Modified from', { exact: true }).fill('2026-09-02')
  await page.getByLabel('Modified through', { exact: true }).fill('2026-09-14')
  await page.getByRole('checkbox', { name: 'Descending', exact: true }).click()
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ classification: 'unclassified', owner_kind: 'agent', owner: 7, ...dates, sort_desc: true, limit: 50, offset: 0 })
  await expect(page.getByLabel('Created from', { exact: true })).toHaveCount(0)
  await toggleUnclassified(page)
  await expect.poll(() => requests.at(-1).classification).toBe('all')
  await page.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect.poll(() => requests.at(-1).classification).toBe('unclassified')
  await expectUnclassified(page)
})

test('tag creation, inline rename, reparenting and confirmed recursive deletion preserve documents', async ({ page }) => {
  const { mutations, assignments, deletions } = await fixture(page)
  await page.getByRole('button', { name: 'Create a folder', exact: true }).click()
  await expect.poll(() => mutations.at(-1)).toMatchObject({ name: 'New folder', parent_id: null })
  await expect(page.getByLabel('Name', { exact: true })).toBeFocused()
  await page.keyboard.type('Reading')
  await page.getByLabel('Name', { exact: true }).press('Enter')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByLabel('Name', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Reading', { exact: true })).toBeVisible()
  await editFolder(page, 'Reading')
  await page.getByLabel('Name', { exact: true }).fill('Books')
  await page.getByLabel('Name', { exact: true }).press('Escape')
  await expect(page.getByText('Reading', { exact: true })).toBeVisible()
  await editFolder(page, 'Reading')
  await page.getByLabel('Name', { exact: true }).fill('Books')
  await page.getByLabel('Name', { exact: true }).press('Enter')
  await expect(page.getByText('Books', { exact: true })).toBeVisible()
  await page.getByText('Books', { exact: true }).dragTo(page.getByText('Work', { exact: true }))
  await expect.poll(() => mutations.at(-1)).toMatchObject({ id: 'new-tag', parent_id: 'work' })
  await page.getByText('Books', { exact: true }).dragTo(page.getByRole('button', { name: 'Create a folder', exact: true }).locator('..'))
  await expect.poll(() => mutations.at(-1)).toMatchObject({ id: 'new-tag', parent_id: null })
  await mount(page, 'app/memory/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, containerStyle: { height: '760px', width: '400px' } })
  // The moved folder remains accessible while its former parent is collapsed.
  await expect(page.getByText('Project', { exact: true })).not.toBeVisible()
  await expect(page.getByText('Books', { exact: true })).toBeVisible()
  await page.getByText('Books', { exact: true }).dragTo(page.getByText('Work', { exact: true }))
  await expect.poll(() => mutations.at(-1)).toMatchObject({ id: 'new-tag', parent_id: 'work' })
  const splitter = page.getByRole('separator', { name: 'Resize folders and documents' })
  await splitter.focus(); await page.keyboard.press('ArrowDown')
  await expect.poll(() => page.evaluate(() => Number(localStorage.getItem('galaris:document-library-split:1')))).toBeGreaterThan(35)
  await page.getByText('Test document', { exact: true }).dragTo(page.getByText('Work', { exact: true }))
  await expect.poll(() => [...assignments]).toEqual(['work'])
  await folderAction(page, 'Work', 'Delete folder Work')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByText('Work', { exact: true })).toBeVisible()
  await expect.poll(() => [...assignments]).toEqual(['work'])
  await folderAction(page, 'Work', 'Delete folder Work')
  await page.route('**/api/memory/documents/tags/work?confirmed=true', route => route.fulfill({ status: 500, json: { detail: 'Unavailable' } }))
  await page.getByRole('dialog').getByRole('button', { name: 'Delete folder', exact: true }).click()
  await expect(page.getByText('Unable to update your classification.', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect([...assignments]).toEqual(['work'])
  await page.unroute('**/api/memory/documents/tags/work?confirmed=true')
  await page.getByRole('dialog').last().getByRole('button', { name: 'Delete folder', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('Project', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Books', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Unclassified documents', { exact: true }).getByText('Test document', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Create a folder', exact: true }).click()
  await page.getByLabel('Name', { exact: true }).fill('Empty')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await folderAction(page, 'Empty', 'Delete folder Empty')
  await expect(page.getByText('Empty', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(deletions.at(-1)).toMatchObject({ deleted: true })
})

test('tree loads all documents, retries, ignores list search and discards closed-branch responses', async ({ page }) => {
  const { requests } = await fixture(page)
  expect(requests.every(request => request.tag_id === null && request.classification === 'unclassified')).toBe(true)
  const branchRequests = []
  let fail = true
  let release
  let delayed = false
  let fresh = false
  await page.route('**/api/memory/documents/library', async route => {
    const body = route.request().postDataJSON()
    if (!body.tag_id) return route.fallback()
    branchRequests.push(body)
    if (fail) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
    const isFresh = fresh
    if (delayed) await new Promise(resolve => { release = resolve })
    const all = Array.from({ length: isFresh ? 1 : 502 }, (_, index) => ({
      item: { ...document, id: `tag-doc-${index}`, title: isFresh ? 'Fresh result' : `Tag report ${index + 1}` },
      tags: [{ id: 'work', name: 'Work', parent_id: null }], agent_ids: [7], writable_agent_ids: [], owner_label: 'Alice',
    }))
    await route.fulfill({ json: { entries: all.slice(body.offset, body.offset + body.limit), total: all.length, keywords: [], has_more: body.offset + body.limit < all.length } })
  })
  await page.getByText('Work', { exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  fail = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  const branch = page.locator('.q-tree')
  await expect(branch.getByText('Tag report 1', { exact: true })).toBeVisible()
  expect(branchRequests.at(-1)).toMatchObject({ tag_id: 'work', include_descendants: false, limit: 500, offset: 500 })
  await expect(branch.getByText('Tag report 502', { exact: true })).toHaveCount(1)
  await expect(branch.getByLabel('Documents per page')).toHaveCount(0)
  const requestCount = branchRequests.length
  await page.getByRole('textbox', { name: /search/i }).fill('list only')
  await expect.poll(() => requests.at(-1).query).toBe('list only')
  expect(branchRequests).toHaveLength(requestCount)
  await expect(branch.getByText('Tag report 1', { exact: true })).toBeVisible()
  await page.getByText('Work', { exact: true }).click()
  delayed = true
  await page.evaluate(() => window.testApp.emitSocket('memory.classification', { data: {
    user_id: 1, tag_ids: ['work'], document_ids: [], tags_changed: false, list_changed: false,
  } }))
  await page.getByText('Work', { exact: true }).click()
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.getByText('Work', { exact: true }).click()
  delayed = false; fresh = true
  await page.getByText('Work', { exact: true }).click()
  await expect(branch.getByText('Fresh result', { exact: true })).toBeVisible()
  release()
  await expect(branch.getByText('Tag report 1', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Unclassified documents', { exact: true }).getByText('Fresh result', { exact: true })).toHaveCount(0)
})

test('folder toolbar edits name and icon without toggling the branch or requiring a double click', async ({ page }) => {
  const { mutations } = await fixture(page)
  const icon = page.getByRole('button', { name: 'Icon for folder Work', exact: true })
  await icon.click()
  await expect(page.getByText('Project', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await icon.click()
  await expect(page.getByText('Project', { exact: true })).toHaveCount(0)
  await page.getByText('Work', { exact: true }).dblclick()
  await expect(page.getByLabel('Name', { exact: true })).toHaveCount(0)
  await editFolder(page, 'Work')
  await page.getByLabel('Name', { exact: true }).fill('Renamed folder')
  await icon.click()
  await page.getByRole('button', { name: 'Blue folder', exact: true }).click()
  await expect.poll(() => mutations.at(-1)).toMatchObject({ id: 'work', name: 'Renamed folder', icon: 'folder:blue' })
  await expect(page.getByLabel('Name', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Renamed folder', { exact: true })).toBeVisible()
  await editFolder(page, 'Renamed folder')
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Renamed folder')
  await page.getByLabel('Name', { exact: true }).press('Escape')
  expect(mutations).toHaveLength(1)
})

for (const [folder, parent] of [['Work', null], ['Project', 'work']]) {
  test(`folder toolbar creates a sibling immediately below ${folder} and preserves its position`, async ({ page }, testInfo) => {
    const { orders, mutations, requests } = await fixture(page)
    if (parent) await page.getByText('Work', { exact: true }).click()
    await folderAction(page, folder, `Create a folder below ${folder}`)
    await expect(page.getByLabel('Name', { exact: true })).toBeFocused()
    expect(orders).toEqual([{ node: { kind: 'tag', id: 'new-tag' }, parent_id: parent, anchor: { kind: 'tag', id: folder.toLowerCase() }, after: true }])
    await page.getByLabel('Name', { exact: true }).fill('Sibling')
    await page.getByLabel('Name', { exact: true }).press('Enter')
    await expect.poll(() => mutations.at(-1)).toMatchObject({ name: 'Sibling', parent_id: parent })
    const names = parent ? ['Work', 'Project', 'Sibling'] : ['Work', 'Sibling']
    await expect(page.locator('.document-tree .tag-name')).toHaveText(names)
    await mount(page, 'app/memory/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, containerStyle: { height: '760px', width: '400px' } })
    if (parent) await page.getByText('Work', { exact: true }).click()
    await expect(page.locator('.document-tree .tag-name')).toHaveText(names)
    const sibling = page.getByText('Sibling', { exact: true })
    await sibling.click()
    await expect(page.getByText('Empty folder', { exact: true })).toBeVisible()
    const requestCount = requests.length
    await sibling.click()
    await expect(page.getByText('Empty folder', { exact: true })).toBeHidden()
    await sibling.click()
    await expect(page.getByText('Empty folder', { exact: true })).toBeVisible()
    expect(requests).toHaveLength(requestCount)
    await page.getByRole('button', { name: `Icon for folder ${folder}`, exact: true }).hover()
    await page.locator('.library-navigation').screenshot({ path: testInfo.outputPath('folder-toolbar.png'), animations: 'disabled' })
    // Keyboard focus reveals the same actions without requiring pointer hover.
    await page.mouse.move(700, 700)
    const edit = page.getByRole('button', { name: `Edit folder ${folder}`, exact: true })
    await edit.focus(); await page.keyboard.press('Enter')
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue(folder)
    await page.getByLabel('Name', { exact: true }).press('Escape')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.testApp.dark(true))
    await page.locator('.library-navigation').screenshot({ path: testInfo.outputPath('folder-toolbar-mobile-dark.png'), animations: 'disabled' })
    await page.getByRole('button', { name: `Edit folder ${folder}`, exact: true }).click()
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue(folder)
  })
}

test('a folder created through the toolbar remains editable when positioning fails', async ({ page }) => {
  await fixture(page)
  await page.route('**/api/memory/documents/order', route => route.fulfill({ status: 409, json: { detail: 'Stale anchor' } }))
  await folderAction(page, 'Work', 'Create a folder below Work')
  await expect(page.getByText('The folder was created, but could not be positioned. You can move it.', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Name', { exact: true })).toBeFocused()
  await page.getByLabel('Name', { exact: true }).fill('Kept folder')
  await page.getByLabel('Name', { exact: true }).press('Enter')
  await expect(page.getByText('Kept folder', { exact: true })).toBeVisible()
})

test('each tag creates a child and its icon picker searches Unicode emojis and reuses uploads', async ({ page }, testInfo) => {
  const { mutations } = await fixture(page)
  await folderAction(page, 'Work', 'Create a subfolder of Work')
  await expect.poll(() => mutations.at(-1)).toMatchObject({ name: 'New folder', parent_id: 'work' })
  await expect(page.getByLabel('Name', { exact: true })).toBeFocused()
  await page.keyboard.type('Reading')
  await page.getByLabel('Name', { exact: true }).press('Enter')
  await expect.poll(() => mutations.at(-1)).toMatchObject({ name: 'Reading', parent_id: 'work' })
  await expect(page.getByLabel('Name', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Reading', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const icon = page.getByRole('button', { name: 'Icon for folder Reading', exact: true })
  await openFolderIcon(icon)
  await expect(page.getByRole('combobox', { name: 'Icon library', exact: true })).toHaveValue('Folders')
  await page.getByRole('combobox', { name: 'Icon library', exact: true }).click()
  await page.getByRole('option', { name: 'Unicode emoji', exact: true }).click()
  await page.getByLabel('Search icons', { exact: true }).fill('rocket')
  const rocket = page.getByRole('button', { name: 'Rocket', exact: true })
  await expect(rocket).toBeVisible()
  await expect(rocket.locator('.tag-unicode-icon')).toContainText('🚀')
  await rocket.click()
  await expect.poll(() => mutations.at(-1).icon).toBe('emoji:1F680')
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await openFolderIcon(icon)
  await page.getByRole('button', { name: 'Default icon', exact: true }).click()
  await expect.poll(() => mutations.at(-1).icon).toBeNull()
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await openFolderIcon(icon)
  await page.locator('input[type=file]').setInputFiles({ name: 'Triangle.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 10L5 0L10 10Z"/></svg>') })
  await expect.poll(() => mutations.at(-1).icon).toMatch(/^data:image\/svg\+xml;base64,/)
  const uploaded = mutations.at(-1).icon
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await openFolderIcon(page.getByRole('button', { name: 'Icon for folder Work', exact: true }))
  await page.getByRole('combobox', { name: 'Icon library', exact: true }).click()
  await page.getByRole('option', { name: 'My icons', exact: true }).click()
  await page.getByLabel('Search icons', { exact: true }).fill('Triangle')
  await page.getByRole('button', { name: 'Triangle', exact: true }).click()
  await expect.poll(() => mutations.at(-1)).toMatchObject({ id: 'work', icon: uploaded })
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await openFolderIcon(page.getByRole('button', { name: 'Icon for folder Work', exact: true }))
  await page.getByRole('combobox', { name: 'Icon library', exact: true }).click()
  await page.getByRole('option', { name: 'Unicode emoji', exact: true }).click()
  await page.getByLabel('Search icons', { exact: true }).fill('')
  await expect(page.getByRole('button', { name: 'Grinning face', exact: true })).toBeVisible()
  await expect(page.locator('.q-menu:has(.tag-icon-picker)')).toHaveCSS('opacity', '1')
  await page.locator('.tag-icon-picker').screenshot({ path: testInfo.outputPath('tag-icons.png') })
  await page.evaluate(() => window.testApp.dark(true))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await openFolderIcon(page.getByRole('button', { name: 'Icon for folder Work', exact: true }))
  await expect(page.locator('.q-menu:has(.tag-icon-picker)')).toHaveCSS('opacity', '1')
  await page.screenshot({ path: testInfo.outputPath('tag-icons-mobile-dark.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
})

test('icon palette recovers a loading error and rejects oversized uploads without changing the tag', async ({ page }) => {
  const { mutations } = await fixture(page)
  let fail = true
  await page.route('**/api/memory/documents/tag-icons', route => route.fulfill(fail
    ? { status: 500, json: { detail: 'Unavailable' } }
    : { json: [{ id: 'saved', name: 'Saved icon', data: '/tag-icons/openmoji/1F680.svg' }] }))
  const trigger = page.getByRole('button', { name: 'Icon for folder Work', exact: true })
  await trigger.focus()
  await trigger.press('F2')
  await trigger.focus()
  await trigger.press('Enter')
  await expect(page.getByRole('alert')).toContainText('Could not load your icons.')
  fail = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await page.getByRole('combobox', { name: 'Icon library', exact: true }).click()
  await page.getByRole('option', { name: 'My icons', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Saved icon', exact: true })).toBeVisible()
  await page.locator('input[type=file]').setInputFiles({ name: 'Too big.svg', mimeType: 'image/svg+xml', buffer: Buffer.alloc(65537) })
  await expect(page.getByRole('alert')).toContainText('0.064 MB')
  expect(mutations).toEqual([])
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
})

test('French icon search reaches Unicode, colored folders and both icon fonts and preserves the choice', async ({ page }, testInfo) => {
  const { mutations, requests } = await fixture(page, 'fr')
  const trigger = page.getByRole('button', { name: 'Icône du dossier Work', exact: true })
  const search = page.getByLabel('Rechercher une icône', { exact: true })
  const selectFamily = async name => {
    await page.getByRole('combobox', { name: 'Bibliothèque d’icônes', exact: true }).click()
    await page.getByRole('option', { name, exact: true }).click()
    await search.fill('')
  }
  await openFolderIcon(trigger)
  await expect(page.getByRole('combobox', { name: 'Bibliothèque d’icônes', exact: true })).toHaveValue('Dossiers')
  await expect(page.getByRole('button', { name: /^Dossier ouvert/ })).toHaveCount(0)
  await selectFamily('Émojis Unicode')
  await search.fill('loutre')
  await page.getByRole('button', { name: 'Loutre', exact: true }).click()
  await expect.poll(() => mutations.at(-1).icon).toBe('emoji:1F9A6')
  await expect(search).toHaveCount(0)
  await expect(trigger.locator('.tag-unicode-icon')).toContainText('🦦')

  await openFolderIcon(trigger)
  await selectFamily('Dossiers')
  await page.getByRole('button', { name: 'Dossier bleu', exact: true }).click()
  await expect.poll(() => mutations.at(-1).icon).toBe('folder:blue')
  await expect(search).toHaveCount(0)
  await expect(trigger.locator('svg')).toBeVisible()
  await expect(trigger.locator('svg')).toHaveAttribute('data-folder-expanded', 'false')
  await page.getByText('Work', { exact: true }).click()
  await expect.poll(() => requests.some(request => request.tag_id === 'work' && !request.include_descendants)).toBe(true)
  await expect(trigger.locator('svg')).toHaveAttribute('data-folder-expanded', 'true')
  await page.getByText('Work', { exact: true }).click()
  await expect(page.getByLabel('Documents du dossier Work', { exact: true })).toHaveCount(0)
  await expect(trigger.locator('svg')).toHaveAttribute('data-folder-expanded', 'false')

  await openFolderIcon(trigger)
  await selectFamily('Material Design')
  await search.fill('serveur')
  const server = page.getByRole('button', { name: 'Server', exact: true })
  await expect(server.locator('.mdi-server')).toBeVisible()
  await server.click()
  await expect.poll(() => mutations.at(-1).icon).toBe('font:mdi:server')
  await expect(search).toHaveCount(0)
  await expect(trigger.locator('.mdi-server')).toBeVisible()

  await openFolderIcon(trigger)
  await selectFamily('Font Awesome')
  await search.fill('base donnees')
  const database = page.getByRole('button', { name: 'Database', exact: true })
  await expect(database.locator('.fa-database')).toBeVisible()
  await database.click()
  await expect.poll(() => mutations.at(-1).icon).toBe('font:fas:database')
  await expect(search).toHaveCount(0)
  await expect(trigger.locator('.fa-database')).toBeVisible()
  await openFolderIcon(trigger)
  await search.fill('')
  await expect(page.locator('.q-menu:has(.tag-icon-picker)')).toHaveCSS('opacity', '1')
  await page.evaluate(() => document.fonts.ready)
  await page.locator('.tag-icon-picker').screenshot({ path: testInfo.outputPath('font-palette.png') })
})

test('failed moves keep existing classification and inline rename failures retain the edit', async ({ page }) => {
  const { assignments } = await fixture(page)
  assignments.add('work')
  await page.route('**/api/memory/documents/doc-a/tags', route => route.fulfill({ status: 500, json: { detail: 'Unavailable' } }))
  await page.getByText('Test document', { exact: true }).dragTo(page.getByText('Work', { exact: true }))
  await expect(page.getByText('Unable to update your classification.', { exact: true })).toBeVisible()
  expect([...assignments]).toEqual(['work'])
  await page.route('**/api/memory/documents/tags/work', route => route.fulfill({ status: 500, json: { detail: 'Unavailable' } }))
  await editFolder(page, 'Work')
  await page.getByLabel('Name', { exact: true }).fill('Changed')
  await page.getByLabel('Name', { exact: true }).press('Enter')
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Changed')
  await expect(page.getByLabel('Name', { exact: true })).toBeEnabled()
  await page.getByLabel('Name', { exact: true }).press('Escape')
  await expect(page.getByText('Work', { exact: true })).toBeVisible()
  let attempts = 0
  await page.route('**/api/memory/documents/tags', route => {
    if (route.request().method() !== 'POST') return route.fallback()
    attempts++
    return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
  })
  const create = page.getByRole('button', { name: 'Create a folder', exact: true })
  await create.click()
  await expect.poll(() => attempts).toBe(1)
  await expect(create).toBeEnabled()
  await expect(page.getByLabel('Name', { exact: true })).toHaveCount(0)
  await expect(page.getByText('New folder', { exact: true })).toHaveCount(0)
})

test('late search responses cannot replace current results and request errors can be retried', async ({ page }) => {
  await jsonRoute(page, '**/api/memory/documents/doc-a', { item: document, agent_id: 7 })
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [] })
  let release, slowRequested = false, fail = true
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/documents/library', async route => {
    const body = route.request().postDataJSON()
    if (body.query === 'slow') { slowRequested = true; await gate }
    if (body.query === 'error' && fail) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
    await route.fulfill({ json: { entries: [{ item: { ...document, title: body.query || 'Initial' }, agent_ids: [], writable_agent_ids: [], tags: [] }], total: 1, keywords: [], has_more: false } })
  })
  await mount(page, 'app/memory/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, containerStyle: { height: '760px', width: '400px' } })
  const search = page.getByRole('textbox', { name: /search/i })
  await search.fill('slow')
  await expect.poll(() => slowRequested).toBe(true)
  await search.fill('current')
  await expect(page.getByText('current', { exact: true })).toBeVisible()
  release()
  await expect(page.getByText('slow', { exact: true })).toHaveCount(0)
  await search.fill('error')
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  fail = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('error', { exact: true })).toBeVisible()
})

test('switching user clears private tags and restores that user’s panel preference', async ({ page }) => {
  await fixture(page)
  await toggleUnclassified(page)
  await expectUnclassified(page, false)
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 2, tags: [{ id: 'other', name: 'Other user tag', parent_id: null }] })
  await jsonRoute(page, '**/api/memory/documents/library', { entries: [], total: 0, keywords: [], has_more: false })
  await page.evaluate(() => {
    localStorage.setItem('galaris:document-library-split:2', '45')
    window.testApp.auth.$patch({ user: { id: 2, email: 'other@example.invalid' } })
    window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'other-session' }))
  })
  await expect(page.getByText('Work', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Test document', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Other user tag', { exact: true })).toBeVisible()
  await expectUnclassified(page)
  await expect(page.getByRole('separator', { name: 'Resize folders and documents' })).toHaveAttribute('aria-valuenow', '45')
})

test('folder-first ordering, alphabetical sorting and recursive expansion preserve personal order', async ({ page }, testInfo) => {
  const tags = [
    { id: 'work', name: 'Work', parent_id: null, position: 1 },
    { id: 'reading', name: 'Reading', parent_id: null, position: 2 },
    { id: 'child', name: 'Child', parent_id: 'work', position: 2 },
  ]
  const docs = [
    { id: 'alpha', title: 'Alpha', parent: 'work', position: 1, listPosition: 1 },
    { id: 'beta', title: 'Beta', parent: 'work', position: 3, listPosition: 2 },
    { id: 'gamma', title: 'Gamma', parent: null, position: 0, listPosition: 3 },
    { id: 'delta', title: 'Delta', parent: null, position: 0, listPosition: 4 },
    { id: 'child-notes', title: 'Child notes', parent: 'child', position: 1, listPosition: 5 },
  ]
  const moves = []
  const branchReads = []
  let sortFailure = false
  let fail = false
  for (const doc of docs) {
    await jsonRoute(page, `**/api/memory/documents/${doc.id}`, {
      item: { ...document, id: doc.id, title: doc.title }, agent_id: 7,
    })
  }
  await page.route('**/api/memory/documents/tags', route => route.fulfill({ json: { user_id: 1, tags } }))
  await page.route('**/api/memory/documents/library', route => {
    const body = route.request().postDataJSON()
    branchReads.push(body.tag_id)
    const selected = docs.filter(doc => body.tag_id ? doc.parent === body.tag_id : body.classification !== 'unclassified' || !doc.parent)
      .sort((a, b) => body.tag_id ? a.position - b.position : a.listPosition - b.listPosition)
    return route.fulfill({ json: { entries: selected.map(doc => ({ item: { ...document, id: doc.id, title: doc.title },
      position: body.tag_id ? doc.position : doc.listPosition, tags: tags.filter(tag => tag.id === doc.parent), agent_ids: [7], writable_agent_ids: [] })), total: selected.length, keywords: [], has_more: false } })
  })
  await page.route('**/api/memory/documents/order', route => {
    const data = route.request().postDataJSON(); moves.push(data)
    if (fail) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
    const field = data.list_only ? 'listPosition' : 'position'
    const moving = (data.node.kind === 'tag' ? tags : docs).find(row => row.id === data.node.id)
    if (!data.list_only) moving[data.node.kind === 'tag' ? 'parent_id' : 'parent'] = data.parent_id
    const siblings = (data.list_only ? docs : [...tags.filter(tag => tag.parent_id === data.parent_id), ...docs.filter(doc => data.parent_id && doc.parent === data.parent_id)])
      .filter(row => row !== moving).sort((a, b) => a[field] - b[field])
    const index = data.anchor ? siblings.findIndex(row => row.id === data.anchor.id) + Number(data.after) : siblings.length
    siblings.splice(index, 0, moving)
    if (!data.list_only) siblings.sort((a, b) => Number(!tags.includes(a)) - Number(!tags.includes(b)))
    siblings.forEach((row, position) => { row[field] = position + 1 })
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/memory/documents/order/sort', route => {
    if (sortFailure) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
    const { parent_id, descending } = route.request().postDataJSON()
    const compare = (a, b) => (a.name ?? a.title).localeCompare(b.name ?? b.title) * (descending ? -1 : 1)
    const sorted = [...tags.filter(tag => tag.parent_id === parent_id).sort(compare), ...docs.filter(doc => doc.parent === parent_id).sort(compare)]
    sorted.forEach((row, index) => { row.position = index + 1 })
    return route.fulfill({ status: 204 })
  })
  const open = () => mount(page, 'app/memory/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null }, containerStyle: { height: '760px', width: '400px', maxWidth: '100vw' } })
  await open()
  const work = page.getByText('Work', { exact: true })
  await page.getByText('Reading', { exact: true }).dragTo(work.locator('xpath=ancestor::div[contains(@class,"tag-row")][1]'), { targetPosition: { x: 60, y: 2 } })
  await expect.poll(() => tags.find(tag => tag.id === 'reading').position).toBe(1)
  await work.click()
  const tree = page.locator('.q-tree')
  const titles = tree.locator('.tag-name, .q-item__label > span.ellipsis')
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Alpha', 'Beta'])
  await tree.getByText('Beta', { exact: true }).dragTo(tree.getByText('Alpha', { exact: true }).locator('xpath=ancestor::div[contains(@class,"q-item")][1]'), { targetPosition: { x: 60, y: 2 } })
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Beta', 'Alpha'])
  const beta = tree.getByText('Beta', { exact: true }).locator('xpath=ancestor::div[contains(@class,"q-item")][1]')
  await tree.getByText('Child', { exact: true }).dragTo(beta, { targetPosition: { x: 60, y: 2 } })
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Beta', 'Alpha'])
  const childRow = tree.getByText('Child', { exact: true }).locator('xpath=ancestor::div[contains(@class,"tag-row")][1]')
  await tree.getByText('Alpha', { exact: true }).dragTo(childRow, { targetPosition: { x: 60, y: (await childRow.boundingBox()).height - 2 } })
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Alpha', 'Beta'])
  const list = page.getByLabel('Unclassified documents', { exact: true })
  await list.getByText('Delta', { exact: true }).dragTo(list.getByText('Gamma', { exact: true }).locator('xpath=ancestor::div[contains(@class,"q-item")][1]'), { targetPosition: { x: 60, y: 2 } })
  await expect(list.locator('.q-item__label > span.ellipsis')).toHaveText(['Delta', 'Gamma'])
  expect(moves.at(-1)).toMatchObject({ list_only: true, node: { kind: 'document', id: 'delta' }, anchor: { kind: 'document', id: 'gamma' }, after: false })
  fail = true
  await tree.getByText('Alpha', { exact: true }).dragTo(beta, { targetPosition: { x: 60, y: 2 } })
  await expect(page.getByText('Unable to update your classification.', { exact: true })).toBeVisible()
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Alpha', 'Beta'])
  await open()
  await page.getByText('Work', { exact: true }).click()
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Alpha', 'Beta'])
  await expect(list.locator('.q-item__label > span.ellipsis')).toHaveText(['Delta', 'Gamma'])
  await page.screenshot({ path: testInfo.outputPath('ordered-document-tree.png'), animations: 'disabled' })
  for (const [label, documents] of [['Sort by name (Z → A)', ['Beta', 'Alpha']], ['Sort by name (A → Z)', ['Alpha', 'Beta']]]) {
    await folderAction(page, 'Work', 'Actions for folder Work')
    await page.getByText(label, { exact: true }).click()
    await expect(titles).toHaveText(['Reading', 'Work', 'Child', ...documents])
  }
  sortFailure = true
  await folderAction(page, 'Work', 'Actions for folder Work')
  await page.getByText('Sort by name (Z → A)', { exact: true }).click()
  await expect(page.getByText('Unable to update your classification.', { exact: true })).toBeVisible()
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Alpha', 'Beta'])
  sortFailure = false
  await folderAction(page, 'Work', 'Actions for folder Work')
  await page.getByText('Sort by name (Z → A)', { exact: true }).click()
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Beta', 'Alpha'])
  await open()
  await page.getByText('Work', { exact: true }).click()
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Beta', 'Alpha'])
  branchReads.length = 0
  await folderAction(page, 'Work', 'Actions for folder Work')
  await page.getByText('Expand all in this folder', { exact: true }).click()
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Child notes', 'Beta', 'Alpha'])
  expect(branchReads).toEqual(['child'])
  await folderAction(page, 'Work', 'Actions for folder Work')
  await page.getByText('Collapse all in this folder', { exact: true }).click()
  await expect(titles).toHaveText(['Reading', 'Work'])
  await page.getByText('Work', { exact: true }).click()
  await expect(titles).toHaveText(['Reading', 'Work', 'Child', 'Beta', 'Alpha'])
  expect(branchReads).toEqual(['child'])
  await folderAction(page, 'Work', 'Actions for folder Work')
  await page.locator('.q-menu').screenshot({ path: testInfo.outputPath('folder-actions-menu.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await expect(page.getByLabel('Created from', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('document-filters.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('switch', { name: 'Unclassified', exact: true })).toHaveCount(0)
  await page.evaluate(() => window.testApp.dark(true))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await expect(page.getByLabel('Created from', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('document-filters-mobile-dark.png'), animations: 'disabled' })
})
