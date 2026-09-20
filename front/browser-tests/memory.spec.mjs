import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

async function memoryItemFixtures(page) {
  const item = { ...document, title: 'Current memory', node_kind: 'memory', memory_type: 'semantic',
    media_type: 'text/html', content_profile_version: 1, keywords: ['current'], payload: { text: '<p>Current body</p>' },
    source_refs: ['task:11111111-1111-1111-1111-111111111111'] }
  const versions = [1, 2, 3].map(revision => ({ revision, title: `Saved version ${revision}`, keywords: [],
    created_at: '2026-09-01T12:00:00Z', author_agent_id: 7, task_id: null, content_hash: String(revision) }))
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/filter-options?*', { topics: [], contacts: [] })
  await jsonRoute(page, '**/api/memory/findings?*', [])
  await jsonRoute(page, '**/api/memory/items/doc-a/links?*', [])
  await jsonRoute(page, '**/api/memory/items/doc-a/revisions?*', versions)
  await jsonRoute(page, '**/api/memory/items/doc-a/sharing', { lock_version: 3, can_manage: true, grants: [], options: [],
    level: 'private', can_write: false, owner: { kind: 'agent', id: 7, label: 'Alice', can_write: true }, owner_groups: [] })
  await page.route('**/api/memory/browse', route => route.fulfill({ json: { hits: [{ item, score: 1 }], total: 1, has_more: false } }))
  return { item, versions }
}

for (const locale of ['fr', 'en']) {
  test(`memory list stays readable without horizontal scrolling in ${locale}`, async ({ page }, testInfo) => {
    const { item } = await memoryItemFixtures(page)
    item.title = `Long memory ${'unbroken-title-'.repeat(18)}`
    item.last_accessed_at = '2026-09-01T12:00:00Z'
    item.access_count = 123456789
    item.deletion_protected = true
    await jsonRoute(page, '**/api/agents?*', [{ ...agent, last_name: 'LongOwnerName'.repeat(10) }])
    await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
    await page.route('**/api/memory/browse', route => route.fulfill({ json: {
      hits: [{ item, score: 1, excerpt: 'LongExcerptWithoutSpaces'.repeat(20) }], total: 1, has_more: false,
    } }))
    await mount(page, 'app/memory/pages/index.vue', { locale, privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
    await expect(page.getByText(item.title, { exact: true })).toBeVisible()
    for (const width of [1920, 1280, 1024, 768, 390, 320, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      // Leave the same space as an open navigation drawer on desktop.
      await page.locator('.q-page-container').evaluate((element, viewport) => {
        element.style.paddingLeft = viewport >= 1024 ? '260px' : '0'
      }, width)
      await expect.poll(() => page.locator('.memory-list-table').evaluate(element => {
        const elements = [document.documentElement, element, ...element.querySelectorAll('*')]
        return elements.filter(node => {
          const style = getComputedStyle(node)
          return node.clientWidth > 0 && ['auto', 'scroll'].includes(style.overflowX)
            && node.scrollWidth > node.clientWidth + 1
        }).map(node => node.className)
      }), { message: `No horizontal scroll areas at ${width}px` }).toEqual([])
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
      await expect(page.getByText(item.title, { exact: true })).toBeVisible()
      if (width === 1024 || width === 320) {
        await page.screenshot({ path: testInfo.outputPath(`memory-list-${width}.png`), fullPage: true })
      }
    }
    await page.getByText(item.title, { exact: true }).click()
    await expect(page.getByRole('dialog').getByLabel(locale === 'fr' ? 'Titre' : 'Title', { exact: true })).toHaveValue(item.title)
  })
}

for (const width of [1440, 390]) {
  test(`attachment memory keeps its description and opens the original file at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const { item } = await memoryItemFixtures(page)
    Object.assign(item, { node_kind: 'attachment', metadata: {
      resource_uri: 'document://11111111-1111-1111-1111-111111111111/attachments/22222222-2222-2222-2222-222222222222',
      resource_media_type: 'text/markdown',
    } })
    await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
    await jsonRoute(page, '**/api/memory/documents/*/attachments/*/info?*', {
      id: '22222222-2222-2222-2222-222222222222', name: 'Original.md', media_type: 'text/markdown', size_bytes: 30,
    })
    await page.route('**/api/memory/documents/*/attachments/22222222-2222-2222-2222-222222222222?*', route => {
      expect(new URL(route.request().url()).searchParams.get('agent_id')).toBe('7')
      return route.fulfill({ contentType: 'text/markdown', body: '# Original attachment\n\nFull file content.' })
    })
    await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
    const preview = page.getByRole('button', { name: 'Preview', exact: true })
    await preview.click()
    const viewer = page.getByRole('dialog', { name: 'Open preview of Original.md', exact: true })
    await expect(viewer.getByRole('heading', { name: 'Original attachment' })).toBeVisible()
    await viewer.getByRole('button', { name: 'Enter fullscreen', exact: true }).click()
    await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(true)
    await viewer.getByRole('button', { name: 'Exit fullscreen', exact: true }).click()
    await viewer.getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByText('Current memory', { exact: true }).click()
    const detail = page.getByRole('dialog').filter({ has: page.getByLabel('Title', { exact: true }) })
    await expect(detail.getByText('Current body', { exact: true })).toBeVisible()
    await detail.getByRole('button', { name: 'Preview', exact: true }).click()
    await expect(viewer.getByText('Full file content.', { exact: true })).toBeVisible()
    await viewer.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(detail.getByText('Current body', { exact: true })).toBeVisible()
  })
}

for (const width of [1440, 390]) {
  test(`memory folders remain collections without opening an item at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const { item } = await memoryItemFixtures(page)
    Object.assign(item, { node_kind: 'folder', title: 'Reports collection' })
    await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
    await page.getByText('Reports collection', { exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'View', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Preview', exact: true })).toHaveCount(0)
  })
}

test('a folder graph inspector keeps navigation to its contents without a view action', async ({ page }) => {
  await mount(page, 'app/memory/components/MemoryGraphNodeDetail.vue', { props: {
    agentId: 7, node: { ...document, node_kind: 'folder', title: 'Reports collection' },
    relations: [{ edge: { id: 'link-1', relation_type: 'parent_of' }, other: { ...document, id: 'child-1', node_kind: 'memory', title: 'Child memory' } }],
    color: '#087FF5', icon: 'folder', roleLabel: 'Folder',
  } })
  await expect(page.getByRole('button', { name: 'View', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Preview', exact: true })).toHaveCount(0)
  await page.getByText('Child memory', { exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').at(-1)?.value)).toBe('child-1')
})

for (const delayedStage of ['memory', 'info', 'content']) {
  test(`attachment preview retries a denied ${delayedStage} read and discards it after an agent change`, async ({ page }) => {
    const attachmentId = '22222222-2222-2222-2222-222222222222'
    const documentId = '11111111-1111-1111-1111-111111111111'
    let reads = 0, waiting = false, release
    const sources = [
      ['memory', '**/api/memory/items/doc-a?*', { json: { ...document, node_kind: 'attachment', metadata: {
        resource_uri: `document://${documentId}/attachments/${attachmentId}`,
      } } }],
      ['info', '**/api/memory/documents/*/attachments/*/info?*', { json: {
        id: attachmentId, name: 'Original.md', media_type: 'text/markdown', size_bytes: 30,
      } }],
      ['content', `**/api/memory/documents/*/attachments/${attachmentId}?*`, {
        contentType: 'text/markdown', body: '# Original attachment',
      }],
    ]
    for (const [stage, pattern, response] of sources) {
      await page.route(pattern, async route => {
        if (stage === delayedStage) {
          reads++
          if (reads === 1) return route.fulfill({ status: 403 })
          if (reads === 2) {
            waiting = true
            await new Promise(resolve => { release = resolve })
          }
        }
        return route.fulfill(response)
      })
    }
    await mount(page, 'app/memory/components/MemoryAttachmentButton.vue', { props: { itemId: 'doc-a', agentId: 7 } })
    const button = page.getByRole('button', { name: 'Preview', exact: true })
    await button.click()
    await expect(page.getByText('The attachment operation failed.', { exact: true })).toBeVisible()
    await button.click()
    await expect.poll(() => waiting).toBe(true)
    await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
    const lateResponse = page.waitForResponse(response => new URL(response.url()).searchParams.get('agent_id') === '7')
    release()
    await lateResponse
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await button.click()
    await expect(page.getByRole('heading', { name: 'Original attachment' })).toBeVisible()
    await page.evaluate(() => window.testApp.setProps({ agentId: null }))
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(button).toBeDisabled()
  })
}

test('revocation clears an open memory and ignores a late browse response', async ({ page }) => {
  const { item } = await memoryItemFixtures(page)
  await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
  await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
  await page.getByText('Current memory', { exact: true }).click()
  await expect(page.getByText('Current body', { exact: true })).toBeVisible()
  let release
  const pending = new Promise(resolve => { release = resolve })
  let started = false
  await page.route('**/api/memory/browse', async route => {
    if (!started) {
      started = true
      await pending
      await route.fulfill({ json: { hits: [{ item, score: 1 }], total: 1, has_more: false } })
    } else await route.fulfill({ json: { hits: [], total: 0, has_more: false } })
  })
  await page.evaluate(() => window.testApp.emitSocket('memory.invalidate', { data: {} }))
  await expect.poll(() => started).toBe(true)
  await page.evaluate(() => window.testApp.emitSocket('memory.invalidate', { data: {} }))
  await expect(page.getByText('Current body', { exact: true })).toHaveCount(0)
  release()
  await expect(page.getByText('Current memory', { exact: true })).toHaveCount(0)
});

for (const width of [1440, 390]) {
  test(`memory history shows saved content and preserves the current version and edit draft at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const { item } = await memoryItemFixtures(page)
    const writes = [], reads = []
    await page.route('**/api/memory/items/doc-a?*', route => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON()
        writes.push(body)
        Object.assign(item, body, { revision: 4 })
      }
      const revision = new URL(route.request().url()).searchParams.get('revision')
      if (revision) reads.push(revision)
      const historical = revision && revision !== '3'
        ? { ...item, revision: Number(revision), title: `Saved version ${revision}`, keywords: ['historical'],
          media_type: revision === '1' ? 'text/markdown' : 'text/html',
          payload: { text: revision === '1' ? '**Original body**' : '<p>Revised body</p>' } }
        : item
      return route.fulfill({ json: historical })
    })
    await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
    await page.getByText('Current memory', { exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Current body', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Owner agent', { exact: true })).toHaveValue('Alice Example')
    await expect(dialog.getByLabel('Owner agent', { exact: true })).not.toBeEditable()
    expect(reads).toEqual([])
    await dialog.screenshot({ path: testInfo.outputPath('memory-view.png'), animations: 'disabled' })
    await dialog.getByRole('tab', { name: 'History', exact: true }).click()
    await expect(dialog.getByText('Original body', { exact: true })).toBeVisible()
    await expect(dialog.getByText('Saved version 1', { exact: true })).toBeVisible()
    await dialog.getByText('Version 2', { exact: true }).first().click()
    await expect(dialog.getByText('Revised body', { exact: true })).toBeVisible()
    await dialog.screenshot({ path: testInfo.outputPath('memory-history.png'), animations: 'disabled' })
    await dialog.getByRole('tab', { name: 'Memory', exact: true }).click()
    await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Current memory')
    await dialog.getByLabel('Title', { exact: true }).fill('My current draft')
    const keywordField = dialog.locator('.memory-form-keywords')
    await expect(keywordField.locator('.q-chip')).toContainText('current')
    await dialog.getByRole('combobox', { name: 'Keywords', exact: true }).fill(' release, notes ')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Escape')
    await expect(keywordField.locator('.q-chip')).toContainText(['current', 'release, notes'])
    await dialog.getByRole('tab', { name: 'History', exact: true }).click()
    await expect(dialog.getByText('Original body', { exact: true })).toBeVisible()
    await dialog.getByRole('tab', { name: 'Memory', exact: true }).click()
    await expect(dialog.getByText('Current body', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('My current draft')
    await expect(keywordField.locator('.q-chip').last()).toContainText('release, notes')
    expect(writes).toEqual([])
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]).toMatchObject({ title: 'My current draft', expected_revision: 3, keywords: ['current', 'release, notes'], payload: { text: '<p>Current body</p>' } })
    expect(writes[0]).not.toHaveProperty('summary')
    expect(writes[0]).not.toHaveProperty('reason')
    await expect(dialog.getByRole('tab', { name: 'Memory', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(dialog.getByText('Current body', { exact: true })).toBeVisible()
    await dialog.getByLabel('Title', { exact: true }).fill('Second saved title')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(2)
    expect(writes[1]).toMatchObject({ title: 'Second saved title', expected_revision: 4 })
  })
}

test('memory history can be read without edit privileges and recovers a failed version load', async ({ page }) => {
  const { item } = await memoryItemFixtures(page)
  let fail = true
  await page.route('**/api/memory/items/doc-a?*', route => {
    expect(route.request().method()).toBe('GET')
    if (new URL(route.request().url()).searchParams.has('revision')) {
      if (fail) return route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } })
      return route.fulfill({ json: { ...item, revision: 1, payload: { text: '<p>Recovered version</p>' } } })
    }
    return route.fulfill({ json: item })
  })
  await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
  await page.getByText('Current memory', { exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Current memory')
  await expect(dialog.getByLabel('Title', { exact: true })).not.toBeEditable()
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await dialog.getByRole('tab', { name: 'History', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('The content history could not be loaded.')
  fail = false
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByText('Recovered version', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
})

test('memory history ignores a late version response after another selection', async ({ page }) => {
  const { item, versions } = await memoryItemFixtures(page)
  let release, started = false
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/items/doc-a?*', async route => {
    const revision = Number(new URL(route.request().url()).searchParams.get('revision'))
    if (revision === 1) { started = true; await pending }
    return route.fulfill({ json: { ...item, revision, payload: { text: `<p>Body of version ${revision}</p>` } } })
  })
  await mount(page, 'app/memory/components/MemoryItemHistory.vue', { props: {
    itemId: 'doc-a', agentId: 7, currentRevision: 3, revisions: versions, loading: false, hasMore: false,
    pageSize: 50, pageSizeOptions: [10, 20, 50, 100, 500],
  } })
  await expect.poll(() => started).toBe(true)
  await page.getByText('Version 2', { exact: true }).click()
  await expect(page.getByText('Body of version 2', { exact: true })).toBeVisible()
  const lateResponse = page.waitForResponse(response => new URL(response.url()).searchParams.get('revision') === '1')
  release()
  await lateResponse
  await expect(page.getByText('Body of version 2', { exact: true })).toBeVisible()
  await expect(page.getByText('Body of version 1', { exact: true })).toHaveCount(0)
})

for (const locale of ['fr', 'en']) {
  test(`memory relation labels are readable in ${locale}`, async ({ page }) => {
    const { item } = await memoryItemFixtures(page)
    const relations = [
      ['topic_contains', 'Contenu du sujet', 'Topic content'],
      ['contact_contains', 'Mémoire du contact', 'Contact memory'],
      ['topic_involves_contact', 'Contact du sujet', 'Topic contact'],
      ['cycle_of', 'Cycle de', 'Cycle of'],
      ['result_of', 'Résultat de', 'Result of'],
      ['related', 'Lié à', 'Related to'],
      ['topic_membership_candidate', 'Rattachement au sujet suggéré', 'Suggested topic membership'],
      ['topic_membership_anomaly', 'Rattachement au sujet à vérifier', 'Topic membership to review'],
      ['topic_merge_candidate', 'Fusion de sujets suggérée', 'Suggested topic merge'],
      ['topic_split_candidate', 'Scission du sujet suggérée', 'Suggested topic split'],
      ['future_relation', 'Autre relation', 'Other relation'],
    ]
    await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
    await jsonRoute(page, '**/api/memory/items/doc-a/links?*', relations.map(([relation_type], index) => ({
      id: `link-${index}`, source_item_id: item.id, target_item_id: `related-${index}`, relation_type,
      confidence: 1, suggested: false, created_by_agent_id: null, created_at: item.created_at,
    })))
    await mount(page, 'app/memory/pages/index.vue', { locale, route: '/memory?agent=7' })
    await page.getByText('Current memory', { exact: true }).click()
    const dialog = page.getByRole('dialog')
    for (const [, fr, en] of relations) {
      await expect(dialog.getByText(locale === 'fr' ? fr : en, { exact: true })).toBeVisible()
    }
  })
}

export async function documentFixtures(page) {
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/items/doc-a?*', document)
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [{ path: 'Reports', kind: 'custom', shared: false }])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
}

test('memory search submits selected types and trimmed query, then opens a returned memory', async ({ page }) => {
  const requests = []
  await page.route('**/api/memory/search', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: [{ ...document, title: 'Matching memory', score: 0.9 }] })
  })
  await mount(page, 'app/memory/components/MemorySearchTester.vue', { props: { agentId: 7 } })
  await expect(page.locator('button[type=submit]')).toBeDisabled()
  await page.getByLabel('Question or search', { exact: true }).fill('  project evidence  ')
  await page.getByRole('combobox').click()
  await page.getByRole('option', { name: 'Knowledge', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.locator('button[type=submit]').click()
  await expect.poll(() => requests).toEqual([{ agent_id: 7, query: 'project evidence', memory_types: ['semantic'] }])
  await page.getByText('Matching memory', { exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'open').at(-1)?.value)).toBe('doc-a')
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  await expect(page.getByText('Matching memory')).toHaveCount(0)
})

test('document editor autosaves with its revision and preserves read-only content', async ({ page }) => {
  await documentFixtures(page)
  const updates = []
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: document })
    expect(route.request().method()).toBe('PUT')
    updates.push(route.request().postDataJSON())
    return route.fulfill({ json: { ...document, ...updates.at(-1), revision: 4, lock_version: 4 } })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['MEMORY_EDIT'] })
  const title = page.getByLabel('Title', { exact: true })
  await expect(title).toHaveValue('Test document')
  await title.fill('Edited title')
  await expect.poll(() => updates).toHaveLength(1)
  expect(updates[0]).toMatchObject({ title: 'Edited title', expected_revision: 3 })
  expect(updates[0]).not.toHaveProperty('payload')
  await expect(page.locator('.document-editor-uri-badge')).toContainText('document://doc-a')
  await page.evaluate(() => window.testApp.setProps({ editable: false }))
  await expect(title).not.toBeEditable()
})

test('document library paginates on demand and opens a selected document on mobile', async ({ page }) => {
  const secondPageDocument = { ...document, id: 'doc-b', title: 'Second page document' }
  await page.setViewportSize({ width: 390, height: 844 })
  await documentFixtures(page)
  await jsonRoute(page, '**/api/memory/documents/doc-a', { item: document, agent_id: 7 })
  await jsonRoute(page, '**/api/memory/documents/doc-b', { item: secondPageDocument, agent_id: 7 })
  await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [] })
  const offsets = []
  await page.route('**/api/memory/documents/library', route => {
    const { offset, limit } = route.request().postDataJSON()
    offsets.push(offset)
    expect(limit).toBe(50)
    return route.fulfill({ json: { entries: [{ item: offset === 0 ? document : secondPageDocument, agent_ids: [7], writable_agent_ids: [7] }], total: 51, keywords: [], has_more: offset === 0 } })
  })
  await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
  await expect.poll(() => offsets).toEqual([0])
  await page.getByRole('button', { name: '2', exact: true }).click()
  await expect(page.getByText('Second page document', { exact: true })).toBeVisible()
  expect(offsets).toEqual([0, 50])
  await page.getByRole('button', { name: '1', exact: true }).click()
  await page.getByText('Test document', { exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Test document')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('a remote document revision merges untouched fields without losing the local draft', async ({ page }) => {
  await documentFixtures(page)
  let current = { ...document }
  const updates = []
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: current })
    const body = route.request().postDataJSON()
    updates.push(body)
    current = { ...current, ...body, revision: current.revision + 1 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7, editable: true }, privileges: ['MEMORY_EDIT'] })
  const title = page.getByLabel('Title', { exact: true })
  await expect(title).toHaveValue(document.title)
  await page.clock.install()
  await title.fill('Local draft')
  current = { ...document, revision: 4, payload: { text: '# Remote content' } }
  await page.evaluate(() => window.testApp.emitSocket('memory.update', { data: { id: 'doc-a', node_kind: 'document', revision: 4 } }))
  await page.clock.runFor(250)
  await expect(page.locator('.document-editor-revision-button')).toContainText('4')
  await expect(title).toHaveValue('Local draft')
  await page.clock.runFor(1000)
  await expect.poll(() => updates.length).toBe(1)
  expect(updates[0]).toMatchObject({ title: 'Local draft', expected_revision: 4 })
  expect(updates[0]).not.toHaveProperty('payload')
  await expect(title).toHaveValue('Local draft')
  await expect(page.locator('.document-editor-revision-button')).toContainText('5')
})

test('editing a Markdown table preserves its other cells and emits the changed content', async ({ page }) => {
  await mount(page, 'core/util/components/MarkdownWysiwygEditor.vue', { props: { modelValue: '| A | B |\n|---|---|\n| one | two |' } })
  const cell = page.locator('.q-editor__content td').first()
  await expect(cell).toBeVisible()
  await cell.click()
  await page.keyboard.press('Home')
  await page.keyboard.insertText('Updated ')
  await expect(cell).toHaveText('Updated one')
  await page.evaluate(() => window.testApp.dark(true))
  await expect(page.getByRole('cell', { name: 'two', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toMatch(/Updated one[\s\S]*two/)
})

test('overlapping edits keep a durable draft and require an explicit conflict choice', async ({ page }) => {
  await documentFixtures(page)
  let current = { ...document, media_type: 'text/html', content_profile: 'document', content_profile_version: 1, payload: { text: '<p>Original</p>' } }
  const updates = []
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: current })
    const body = route.request().postDataJSON()
    if (body.expected_revision !== current.revision) return route.fulfill({ status: 409, json: { detail: 'Revision conflict' } })
    updates.push(body)
    current = { ...current, ...body, revision: current.revision + 1 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7, editable: true }, privileges: ['MEMORY_EDIT'] })
  const title = page.getByLabel('Title', { exact: true })
  await expect(title).toHaveValue(document.title)
  await page.clock.install()
  await title.fill('My unsaved title')
  current = { ...current, title: 'Concurrent title', revision: 4 }
  await page.evaluate(() => window.testApp.emitSocket('memory.update', { data: { id: 'doc-a', node_kind: 'document', revision: 4 } }))
  await page.clock.runFor(1500)
  await expect(page.getByText('This document changed elsewhere.', { exact: false })).toBeVisible()
  expect(updates).toEqual([])
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('galaris:document-draft:7:doc-a')).draft.title)).toBe('My unsaved title')
  await page.getByRole('button', { name: 'Save my draft over the latest version' }).click()
  await page.clock.runFor(1000)
  await expect.poll(() => updates.length).toBe(1)
  expect(updates[0]).toMatchObject({ title: 'My unsaved title', expected_revision: 4 })
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('galaris:document-draft:7:doc-a'))).toBeNull()
})
