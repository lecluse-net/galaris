import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

async function memoryItemFixtures(page) {
  const item = { ...document, title: 'Current memory', node_kind: 'memory',
    media_type: 'text/html', content_profile_version: 1, keywords: ['current'], payload: { text: '<p>Current body</p>' },
    source_refs: ['task:11111111-1111-1111-1111-111111111111'] }
  const versions = [1, 2, 3].map(revision => ({ revision, title: `Saved version ${revision}`, keywords: [],
    created_at: '2026-09-01T12:00:00Z', author_agent_id: 7, task_id: null, content_hash: String(revision) }))
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/temporal/defaults', { timezone: 'Europe/Paris', lookahead_hours: 24 })
  await jsonRoute(page, '**/api/memory/filter-options?*', { topics: [], contacts: [] })
  await jsonRoute(page, '**/api/memory/findings?*', [])
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes: [], edges: [], has_more: false })
  await jsonRoute(page, '**/api/memory/items/doc-a/links?*', [])
  await jsonRoute(page, '**/api/file-share/items/*/resources?*', [])
  await jsonRoute(page, '**/api/memory/items/doc-a/revisions?*', versions)
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?.*)?$/, route => route.fulfill({ json: { item, agent_id: 7 } }))
  await jsonRoute(page, '**/api/memory/items/doc-a/sharing', { lock_version: 3, can_manage: true, grants: [], options: [],
    level: 'private', can_write: false, owner: { kind: 'agent', id: 7, label: 'Alice', can_write: true }, owner_groups: [] })
  await page.route('**/api/memory/browse', route => route.fulfill({ json: { hits: [{ item, score: 1 }], total: 1, has_more: false } }))
  return { item, versions }
}

for (const width of [1440, 390]) test(`Dream actions refresh the node, preserve drafts and allow retry at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const { item } = await memoryItemFixtures(page)
  Object.assign(item, { node_kind: 'file', source_managed: true, managed_source_kind: 'file_catalogue',
    access: { can_read: true, can_write: true } })
  await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
  await jsonRoute(page, '**/api/dream/memory/doc-a/actions?*', { actions: ['describe', 'thumbnail'] })
  let calls = 0
  let release
  let releaseRefresh
  await page.route('**/api/dream/memory/doc-a/actions/describe?*', async route => {
    calls++
    expect(route.request().method()).toBe('POST')
    expect(new URL(route.request().url()).searchParams.get('agent_id')).toBe('7')
    if (calls === 1) return route.fulfill({ status: 502, json: { detail: 'Synthetic model failure' } })
    await new Promise(resolve => { release = resolve })
    item.payload.text = '<p>New synthetic description</p>'
    item.revision++
    let gateRefresh = true
    await page.route('**/api/memory/items/doc-a?*', async itemRoute => {
      if (gateRefresh) {
        gateRefresh = false
        await new Promise(resolve => { releaseRefresh = resolve })
      }
      await itemRoute.fulfill({ json: item })
    })
    await route.fulfill({ json: { receipt_id: 'synthetic-receipt', result_count: 1 } })
  })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
  await page.getByText('Current memory', { exact: true }).click()
  const dialog = page.getByRole('dialog')
  const generate = dialog.getByRole('button', { name: 'Generate description', exact: true })
  await expect(generate).toBeEnabled()
  await dialog.evaluate(async element => {
    await Promise.all(element.getAnimations({ subtree: true })
      .filter(animation => animation.effect?.getTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})))
  })
  await page.screenshot({ path: testInfo.outputPath('dream-node-actions.png'), animations: 'disabled' })
  await generate.click()
  await expect(page.locator('.q-notification').filter({ hasText: 'The Dream action failed' })).toBeVisible()
  await expect(dialog.getByText('The Dream action failed', { exact: false })).toHaveCount(0)
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('Current body')
  await generate.click()
  await expect.poll(() => calls).toBe(2)
  await expect(dialog.getByRole('button', { name: 'Regenerate thumbnail', exact: true })).toBeDisabled()
  await dialog.getByRole('tab', { name: 'Links and relations', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  await dialog.getByRole('tab', { name: 'Memory', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Regenerate thumbnail', exact: true })).toBeDisabled()
  release()
  await expect.poll(() => typeof releaseRefresh).toBe('function')
  await expect(dialog.locator('[data-editor-surface]')).toHaveAttribute('contenteditable', 'false')
  await expect(dialog.getByRole('button', { name: 'Regenerate thumbnail', exact: true })).toBeDisabled()
  releaseRefresh()
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('New synthetic description')
  await expect(page.locator('.q-notification').filter({ hasText: 'Action completed.' })).toBeVisible()
  await expect(dialog.getByText('Action completed.', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('dream-action-toast.png'), animations: 'disabled' })
  await dialog.locator('[data-editor-surface]').fill('Unsaved synthetic draft')
  await expect(generate).toBeDisabled()
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('Unsaved synthetic draft')
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await page.getByText('Current memory', { exact: true }).click()
  await expect(generate).toBeEnabled()
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('New synthetic description')
})

for (const width of [1440, 390]) for (const nodeKind of ['document', 'file']) {
  test(`Dream thumbnail regeneration updates an existing ${nodeKind} preview at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const { item } = await memoryItemFixtures(page)
    Object.assign(item, { node_kind: nodeKind, document_type: 'html', media_type: 'text/html',
      access: { can_read: true, can_write: true } })
    const images = await page.evaluate(() => [80, 120, 160].map(width => {
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = 60
      const context = canvas.getContext('2d')
      context.fillStyle = width === 80 ? 'blue' : width === 120 ? 'red' : 'green'
      context.fillRect(0, 0, width, 60)
      return canvas.toDataURL('image/webp', 1).split(',')[1]
    }))
    let calls = 0
    await jsonRoute(page, '**/api/memory/items/doc-a?*', nodeKind === 'document'
      ? { ...item, revision: 1, payload: { text: '' } } : item)
    await jsonRoute(page, '**/api/dream/memory/doc-a/actions?*', { actions: ['thumbnail'] })
    const resource = { id: 'image-a', name: 'Synthetic.png', media_type: 'image/png', size_bytes: 100, uri: 'file://synthetic/image.png' }
    await jsonRoute(page, '**/api/file-share/items/doc-a/resources?*', [resource])
    const thumbnailRoute = nodeKind === 'document' ? '**/api/memory/documents/doc-a/thumbnail?*'
      : '**/api/file-share/items/doc-a/resources/image-a/thumbnail?*'
    await page.route(thumbnailRoute, route => route.fulfill({ contentType: 'image/webp', body: Buffer.from(images[calls], 'base64') }))
    await page.route('**/api/dream/memory/doc-a/actions/thumbnail?*', route => {
      expect(route.request().method()).toBe('POST')
      if (nodeKind === 'document') {
        const snapshot = route.request().postDataJSON()
        expect(snapshot.html).toContain('Current body')
        expect(snapshot.revision).toBe(item.revision)
        expect(snapshot.lock_version).toBe(item.lock_version)
      }
      calls++
      return route.fulfill({ json: { receipt_id: `synthetic-thumbnail-${calls}`, result_count: 1 } })
    })
    await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
    const row = page.locator(width >= 1024 ? '.memory-list-table tbody tr' : '.memory-mobile-card').filter({ hasText: 'Current memory' })
    await expect(row.locator('img')).toHaveJSProperty('naturalWidth', 80)
    await row.locator('img').click()
    const dialog = page.getByRole('dialog')
    const regenerate = dialog.getByRole('button', { name: 'Regenerate thumbnail', exact: true })
    for (const expectedWidth of [120, 160]) {
      await regenerate.click()
      await expect(regenerate).toBeEnabled()
      await expect(row.locator('img')).toHaveJSProperty('naturalWidth', expectedWidth)
    }
    await expect(dialog.locator('[data-editor-surface]')).toHaveText(nodeKind === 'document' ? '' : 'Current body')
    await dialog.evaluate(async element => {
      await Promise.all(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getTiming().iterations !== Infinity)
        .map(animation => animation.finished.catch(() => {})))
    })
    await page.screenshot({ path: testInfo.outputPath('dream-regenerated-thumbnail.png'), animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await row.locator('img').click()
    await expect(regenerate).toBeEnabled()
    await expect(row.locator('img')).toHaveJSProperty('naturalWidth', 160)
    expect(calls).toBe(2)
  })
}

test('Dream action responses cannot affect another node or expose actions without edit rights', async ({ page }) => {
  let release
  await jsonRoute(page, '**/api/dream/memory/doc-a/actions?*', { actions: ['describe'] })
  await jsonRoute(page, '**/api/dream/memory/doc-b/actions?*', { actions: ['thumbnail'] })
  await page.route('**/api/dream/memory/doc-a/actions/describe?*', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { receipt_id: 'synthetic-receipt', result_count: 1 } })
  })
  await mount(page, 'app/memory/components/MemoryDreamActions.vue', {
    privileges: ['MEMORY_EDIT'], props: { itemId: 'doc-a', agentId: 7 },
  })
  await page.getByRole('button', { name: 'Generate description', exact: true }).click()
  await expect.poll(() => typeof release).toBe('function')
  await page.evaluate(() => window.testApp.setProps({ itemId: 'doc-b', agentId: 7 }))
  await expect(page.getByRole('button', { name: 'Regenerate thumbnail', exact: true })).toBeVisible()
  const lateResponse = page.waitForResponse('**/api/dream/memory/doc-a/actions/describe?*')
  release()
  await (await lateResponse).finished()
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)))
  await expect(page.locator('.q-notification')).toHaveCount(0)
  await mount(page, 'app/memory/components/MemoryDreamActions.vue', {
    privileges: ['MEMORY_ACCESS'], props: { itemId: 'doc-a', agentId: 7 },
  })
  await expect(page.getByRole('button', { name: 'Generate description', exact: true })).toHaveCount(0)
})

test('Dream actions report loading failures and unchanged results in toasts', async ({ page }) => {
  let loads = 0
  await page.route('**/api/dream/memory/doc-a/actions?*', route => {
    loads++
    return loads === 1
      ? route.fulfill({ status: 502, json: { detail: 'Synthetic loading failure' } })
      : route.fulfill({ json: { actions: ['describe'] } })
  })
  await jsonRoute(page, '**/api/dream/memory/doc-a/actions/describe?*', {
    receipt_id: 'synthetic-receipt', result_count: 0,
  })
  await mount(page, 'app/memory/components/MemoryDreamActions.vue', {
    privileges: ['MEMORY_EDIT'], props: { itemId: 'doc-a', agentId: 7 },
  })
  await expect(page.locator('.q-notification').filter({ hasText: 'Could not load Dream actions.' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Dream actions' })).not.toContainText('Could not load Dream actions.')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  const generate = page.getByRole('button', { name: 'Generate description', exact: true })
  await generate.click()
  await expect(page.locator('.q-notification').filter({ hasText: 'Action completed without changes.' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Dream actions' })).not.toContainText('Action completed without changes.')
  await expect(generate).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
})

for (const width of [1440, 390]) test(`memory list displays available thumbnails and keeps items openable at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const { item } = await memoryItemFixtures(page)
  const png = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 176
    canvas.height = 124
    const context = canvas.getContext('2d')
    context.fillStyle = '#e2f6ff'
    context.fillRect(0, 0, 176, 124)
    context.fillStyle = '#03a9f4'
    context.fillRect(16, 16, 144, 20)
    context.fillStyle = '#6baf32'
    context.fillRect(16, 48, 88, 60)
    return canvas.toDataURL('image/png').split(',')[1]
  }), 'base64')
  const items = [
    { ...item, id: 'doc-a', node_kind: 'file', title: 'Indexed illustration' },
    { ...item, id: 'attachment-a', node_kind: 'attachment', title: 'Attached illustration', primary_url: 'document://00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002' },
    { ...item, id: 'document-a', node_kind: 'document', title: 'Rendered document' },
    { ...item, id: 'unavailable-a', node_kind: 'file', title: 'Unavailable thumbnail' },
    { ...item, id: 'memory-a', node_kind: 'memory', title: 'Plain memory' },
  ]
  if (width < 1024) {
    items[1].metadata = { resource_uri: items[1].primary_url }
    delete items[1].primary_url
  }
  await jsonRoute(page, '**/api/memory/browse', { hits: items.map(item => ({ item, score: 1, excerpt: 'Preserved excerpt' })), total: items.length, has_more: false })
  for (const item of items) {
    await jsonRoute(page, `**/api/memory/items/${item.id}?*`, item)
    if (item.node_kind === 'document') await jsonRoute(page, `**/api/memory/documents/${item.id}?*`, { item, agent_id: 7 })
  }
  const resource = { id: 'image-a', name: 'Illustration.png', media_type: 'image/png', size_bytes: 100, uri: 'file://synthetic/illustration.png' }
  await jsonRoute(page, '**/api/file-share/items/doc-a/resources?*', [resource])
  await jsonRoute(page, '**/api/file-share/items/unavailable-a/resources?*', [resource])
  await page.route('**/api/file-share/items/doc-a/resources/image-a/thumbnail?*', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/file-share/items/unavailable-a/resources/image-a/thumbnail?*', route => route.fulfill({ status: 404 }))
  await page.route('**/api/memory/documents/00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002/thumbnail?*', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/memory/documents/document-a/thumbnail?*', route => route.fulfill({ contentType: 'image/webp', body: png }))
  await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
  const rows = page.locator(width >= 1024 ? '.memory-list-table tbody tr' : '.memory-mobile-card')
  for (const item of items) {
    const row = rows.filter({ hasText: item.title })
    await row.scrollIntoViewIfNeeded()
    if (['doc-a', 'attachment-a', 'document-a'].includes(item.id)) {
      await expect(row.locator('img')).toHaveJSProperty('naturalWidth', 176)
    } else {
      await expect(row.locator('img')).toHaveCount(0)
    }
    await expect(row.getByText('Preserved excerpt', { exact: true })).toBeVisible()
  }
  await page.screenshot({ path: testInfo.outputPath('memory-list-thumbnails.png'), fullPage: true })
  await rows.filter({ has: page.getByText('Indexed illustration', { exact: true }) }).locator('img').click()
  await expect(page.getByRole('dialog').locator('.q-toolbar__title')).toHaveText('Memory - File')
})

test('memory item thumbnails discard late responses after agent changes and clear on logout', async ({ page }) => {
  const item = { ...document, node_kind: 'file' }
  const resource = { id: 'image-a', name: 'Image.png', media_type: 'image/png', size_bytes: 100 }
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5AAAAABJRU5ErkJggg==', 'base64')
  await jsonRoute(page, '**/api/file-share/items/doc-a/resources?*', [resource])
  let release, lateFinished = false
  await page.route('**/api/file-share/items/doc-a/resources/image-a/thumbnail?*', async route => {
    const delayed = new URL(route.request().url()).searchParams.get('agent_id') === '7'
    if (delayed) await new Promise(resolve => { release = resolve })
    await route.fulfill({ contentType: 'image/png', body: png })
    if (delayed) lateFinished = true
  })
  await mount(page, 'app/memory/components/MemoryItemThumbnail.vue', { props: { item, agentId: 7 } })
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  const image = page.locator('img')
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  const latest = await image.getAttribute('src')
  release()
  await expect.poll(() => lateFinished).toBe(true)
  await expect(image).toHaveAttribute('src', latest)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: null })))
  await expect(image).toHaveCount(0)
})

for (const width of [1920, 390]) test(`graph opens modals with metadata and preserves neighbor navigation at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const { item } = await memoryItemFixtures(page)
  item.access_count = 37
  await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
  const makeNode = (id, node_kind, title) => ({ ...item, id, node_kind, entity_kind: node_kind, title,
    activity_at: '2026-09-02T13:45:00Z', has_relations: true, relation_count: 2 })
  const nodes = [makeNode('doc-a', 'memory', item.title), makeNode('folder-a', 'folder', 'Synthetic folder'),
    makeNode('conversation-a', 'conversation', 'Synthetic conversation')]
  const edges = [['doc-a', 'folder-a'], ['folder-a', 'conversation-a'], ['conversation-a', 'doc-a']]
    .map(([source_item_id, target_item_id], index) => ({ id: `edge-${index}`, source_item_id, target_item_id,
      relation_type: 'related_to', confidence: 1, suggested: false }))
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes, edges, has_more: false, next_cursor: null, edges_truncated: false })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
  await page.getByRole('tab', { name: 'Graph', exact: true }).click()
  await settledGraph(page)
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await settledGraph(page)
  await page.screenshot({ path: testInfo.outputPath('memory-graph.png'), fullPage: true })
  await clickGraphNode(page, 'doc-a')
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.q-toolbar__title')).toHaveText('Memory - Memory')
  const metadata = dialog.locator('.q-toolbar')
  await expect(metadata.getByText('Accesses: 37', { exact: true })).toBeVisible()
  const activity = await page.evaluate(() => new Intl.DateTimeFormat('en', {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date('2026-09-02T13:45:00Z')))
  await expect(metadata.getByText(activity, { exact: true })).toBeVisible()
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('Current body')
  await page.screenshot({ path: testInfo.outputPath('graph-memory-modal.png') })
  await dialog.getByRole('tab', { name: 'Links and relations', exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('graph-memory-links.png') })
  await dialog.getByText('Synthetic folder', { exact: true }).click()
  await expect(dialog).toHaveCount(1)
  await expect(dialog.locator('.q-toolbar__title')).toHaveText('Synthetic folder')
  await expect(dialog.getByText('Folder', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'View', exact: true })).toHaveCount(0)
  await dialog.getByText('Synthetic conversation', { exact: true }).click()
  await expect(dialog.locator('.q-toolbar__title')).toHaveText('Synthetic conversation')
  await expect(dialog.getByText('Conversation', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('graph-conversation-modal.png') })
  await dialog.getByText(item.title, { exact: true }).click()
  await expect(dialog).toHaveCount(1)
  await expect(dialog.locator('.q-toolbar__title')).toHaveText('Memory - Memory')
  await expect(dialog.locator('.q-toolbar').getByText('Accesses: 37', { exact: true })).toBeVisible()
  if (width >= 1024) await page.locator('.q-dialog__backdrop').click({ position: { x: 10, y: 10 } })
  else await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await settledGraph(page)
  await clickGraphNode(page, 'doc-a')
  await expect(dialog.locator('.q-toolbar__title')).toHaveText('Memory - Memory')
  await expect(dialog.locator('.q-toolbar').getByText(activity, { exact: true })).toBeVisible()
})

for (const nodeKind of ['file', 'directory']) {
  test(`catalogue ${nodeKind} content can be saved and reopened`, async ({ page }) => {
    const { item } = await memoryItemFixtures(page)
    Object.assign(item, { node_kind: nodeKind, source_managed: true,
      managed_source_kind: 'file_catalogue', read_only: false, deletion_protected: true,
      access: { can_read: true, can_write: true } })
    const writes = []
    await page.route('**/api/memory/items/doc-a?*', route => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON()
        writes.push(body)
        Object.assign(item, body, { revision: 4 })
      }
      return route.fulfill({ json: item })
    })
    await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
    await page.getByText('Current memory', { exact: true }).click()
    const dialog = page.getByRole('dialog')
    const editor = dialog.locator('[data-editor-surface]')
    await expect(editor).toBeEditable()
    await editor.fill('Personal catalogue content')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]).toMatchObject({ payload: { text: '<p>Personal catalogue content</p>' } })
    expect(writes[0]).not.toHaveProperty('title')
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toBeHidden()
    await page.getByText('Current memory', { exact: true }).click()
    await expect(dialog.locator('[data-editor-surface]')).toHaveText('Personal catalogue content')
  })
}

for (const width of [1440, 390]) test(`file graph details show all locations, thumbnails and fullscreen previews at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1kAAAAASUVORK5CYII=', 'base64')
  const resources = [
    { id: 'copy-a', uri: 'console://synthetic/image.png', name: 'image.png', media_type: 'image/png', size_bytes: png.length },
    { id: 'copy-b', uri: 'synthetic-talk://room/image-copy.png', name: 'image-copy.png', media_type: 'image/png', size_bytes: png.length },
  ]
  await jsonRoute(page, '**/api/file-share/items/doc-a/resources?*', resources)
  await page.route('**/api/file-share/items/doc-a/resources/*/thumbnail?*', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/file-share/items/doc-a/resources/*/content?*', route => {
    expect(new URL(route.request().url()).searchParams.get('agent_id')).toBe('7')
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await mount(page, 'app/memory/components/MemoryGraphNodeDetail.vue', { props: {
    agentId: 7, node: { ...document, node_kind: 'file', title: 'Synthetic shared file' }, relations: [],
    color: '#00B8C6', icon: 'insert_drive_file', roleLabel: 'File',
  } })
  for (const resource of resources) {
    await expect(page.getByText(resource.uri, { exact: true })).toBeVisible()
    const card = page.locator('.resource-preview-card').filter({ has: page.getByText(resource.name, { exact: true }) })
    const image = card.getByRole('img', { name: resource.name, exact: true })
    await expect(image).toBeVisible()
    await expect.poll(() => image.evaluate(element => element.naturalWidth)).toBeGreaterThan(0)
    await card.getByRole('button', { name: `Open preview of ${resource.name}`, exact: true }).first().click()
    const viewer = page.getByRole('dialog', { name: `Open preview of ${resource.name}`, exact: true })
    await expect(viewer.getByRole('img', { name: resource.name, exact: true })).toBeVisible()
    await viewer.getByRole('button', { name: 'Enter fullscreen', exact: true }).click()
    await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(true)
    await viewer.getByRole('button', { name: 'Exit fullscreen', exact: true }).click()
    await expect.poll(() => page.evaluate(() => document.fullscreenElement)).toBeNull()
    await viewer.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(viewer).toBeHidden()
    // Browser fullscreen events can arrive after this viewer has closed.
    await page.evaluate(() => document.dispatchEvent(new Event('fullscreenchange')))
  }
  await page.screenshot({ path: testInfo.outputPath('file-locations.png') })
})

test('file previews retry denied reads, reopen, and discard late content after an agent change', async ({ page }) => {
  const resource = { id: 'copy-a', uri: 'console://synthetic/readme.md', name: 'readme.md', media_type: 'text/markdown', size_bytes: 30 }
  let reads = 0, waiting = false, release
  await jsonRoute(page, '**/api/file-share/items/doc-a/resources?*', [resource])
  await page.route('**/api/file-share/items/doc-a/resources/*/thumbnail?*', route => route.fulfill({ status: 404 }))
  await page.route('**/api/file-share/items/doc-a/resources/*/content?*', async route => {
    reads++
    if (reads === 1) return route.fulfill({ status: 403 })
    if (reads === 2) {
      waiting = true
      await new Promise(resolve => { release = resolve })
    }
    return route.fulfill({ contentType: 'text/markdown', body: '# Synthetic preview\n\nOriginal file bytes.' })
  })
  await mount(page, 'app/memory/components/MemoryFileResources.vue', { props: { itemId: 'doc-a', agentId: 7 } })
  const open = page.getByRole('button', { name: 'Open preview of readme.md', exact: true }).first()
  await open.click()
  await expect(page.getByText('The attachment operation failed.', { exact: true })).toBeVisible()
  await open.click()
  await expect.poll(() => waiting).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ agentId: null }))
  release()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  await open.click()
  await expect(page.getByRole('heading', { name: 'Synthetic preview' })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await open.click()
  await expect(page.getByText('Original file bytes.', { exact: true })).toBeVisible()
})

for (const width of [1440, 390]) test(`3d graph represents filtered items and restores them at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const timestamp = '2026-09-01T12:00:00Z'
  const nodes = ['left', 'right', 'shared-0', 'shared-1', 'shared-2', 'shared-3'].map((id, index) => ({
    id, title: `Synthetic ${id}`, entity_kind: index < 2 ? 'topic' : 'memory', node_kind: 'memory',
    owner_agent_id: 7, visibility: 'private', source_managed: false, access_count: 0,
    last_accessed_at: null, created_at: timestamp, updated_at: timestamp, activity_at: timestamp,
    has_relations: true, relation_count: index < 2 ? 4 : 2,
  }))
  const edges = nodes.slice(2).flatMap(node => ['left', 'right'].map(source => ({
    id: `${source}-${node.id}`, source_item_id: source, target_item_id: node.id,
    relation_type: 'topic_contains', confidence: 1, suggested: false,
  })))
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes, edges,
    positions: Object.fromEntries(nodes.map((node, index) => [node.id, [index * 180, index % 2 * 180]])),
    has_more: false, edges_truncated: false })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: {
    agentId: 7, query: '', topicItemId: null, contactItemId: null,
  } })
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await page.getByRole('button', { name: 'Hide “Memory” nodes and their relationships', exact: true }).click()
  await expect(page.getByText('4 hidden item(s)', { exact: true })).toBeVisible()
  await expect(page.locator('.memory-graph__chart--3d').getByText('Synthetic left', { exact: true })).toBeVisible()
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('3d-hidden-items.png') })
  await page.getByRole('button', { name: 'Show “Memory” nodes and their relationships', exact: true }).click()
  await expect(page.getByText('4 hidden item(s)', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await expect(page.locator('.memory-graph__chart--3d').getByText('Synthetic left', { exact: true })).toBeVisible()
})

async function settledGraph(page) {
  const graph = page.locator('.memory-graph__chart--3d')
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  await expect(graph.locator('canvas')).toBeVisible()
  return graph.evaluate(element => ({ ...element.dataset }))
}

async function clickGraphNode(page, id) {
  // Keyboard selection makes low-priority captions available in dense views.
  const graph = page.locator('.memory-graph__chart--3d')
  await graph.focus()
  await expect.poll(async () => {
    const count = Number(await graph.getAttribute('data-graph3d-nodes'))
    for (let index = 0; index < count; index++) {
      await page.keyboard.press('ArrowRight')
      // Selection updates the description immediately, while its caption is
      // painted on the next frame. Observe both before activating the node.
      await graph.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)))
      const selected = await graph.getAttribute('aria-description')
      const title = await graph.locator('[data-node-id]').evaluateAll(
        (elements, id) => elements.find(element => element.dataset.nodeId === id)?.title, id)
      if (title && title === selected) return true
    }
    return false
  }).toBe(true)
  await page.keyboard.press('Enter')
}

test('graph errors can be retried and late branches cannot cross an agent change', async ({ page }) => {
  const timestamp = new Date().toISOString()
  const node = { id: 'recovered', title: 'Synthetic recovered memory', node_kind: 'memory', entity_kind: 'memory',
    owner_agent_id: 7, visibility: 'private', source_managed: false, access_count: 0,
    last_accessed_at: null, created_at: timestamp, updated_at: timestamp, activity_at: timestamp,
    has_relations: false, relation_count: 0 }
  const empty = { nodes: [], edges: [], has_more: false, next_cursor: null, edges_truncated: false }
  let reads = 0, release, completeLate, waiting = false
  const pending = new Promise(resolve => { release = resolve })
  const lateCompleted = new Promise(resolve => { completeLate = resolve })
  const aborted = []
  page.on('requestfailed', request => {
    if (request.url().endsWith('/api/memory/graph/roots')) aborted.push(request.failure()?.errorText)
  })
  await page.route('**/api/memory/graph/roots', async route => {
    const attempt = ++reads
    if (attempt === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary failure' } })
    if (attempt === 3) { waiting = true; await pending }
    try {
      await route.fulfill({ json: { ...empty, nodes: route.request().postDataJSON().agent_id === 7 ? [node] : [] } })
    } finally {
      if (attempt === 3) completeLate()
    }
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: {
    agentId: 7, query: '', topicItemId: null, contactItemId: null,
  } })
  await expect(page.getByText('The memory graph could not be loaded.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('1 node(s)', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Reload graph', exact: true }).click()
  await expect.poll(() => waiting).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  await expect(page.getByText('No memory matches the active filters.', { exact: true })).toBeVisible()
  // The old request is cancelled on context change, so no network response
  // event can arrive. Wait for the controlled server work to finish instead.
  await expect.poll(() => aborted.length).toBe(1)
  release()
  await lateCompleted
  expect(Number((await settledGraph(page)).graph3dNodes)).toBe(0)
  await page.evaluate(() => window.testApp.setProps({ agentId: 7 }))
  await expect(page.getByText('1 node(s)', { exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.emitSocket('memory.invalidate', { data: {} }))
  await expect.poll(() => reads).toBe(6)
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  const graph = page.locator('.memory-graph__chart--3d')
  await expect.poll(async () => Number((await settledGraph(page)).graph3dNodes)).toBe(1)
  await graph.focus()
  await page.keyboard.press('ArrowRight')
  await expect(graph).toHaveAttribute('aria-description', 'Synthetic recovered memory')
})

test('opening memory selects an agent and loads its results and filters only once', async ({ page }) => {
  const { item } = await memoryItemFixtures(page)
  const requests = { filters: 0, results: 0 }
  await page.route('**/api/memory/filter-options?*', route => {
    requests.filters++
    return route.fulfill({ json: { topics: [], contacts: [] } })
  })
  await page.route('**/api/memory/browse', route => {
    requests.results++
    return route.fulfill({ json: { hits: [{ item, score: 1 }], total: 1, has_more: false } })
  })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'] })
  await expect(page.getByText('Current memory', { exact: true }).first()).toBeVisible()
  expect(requests).toEqual({ filters: 1, results: 1 })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'] })
  await expect(page.getByText('Current memory', { exact: true }).first()).toBeVisible()
  expect(requests).toEqual({ filters: 2, results: 2 })
})

test.describe('Galaris global calendar with a different browser timezone', () => {
  test.use({ timezoneId: 'America/Toronto' })
for (const width of [1440, 390]) {
  test(`memory calendar filter is always applied and combines criteria at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.clock.setFixedTime(new Date('2026-09-27T16:12:45Z'))
    const { item } = await memoryItemFixtures(page)
    await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
    const requests = []
    let fail = false
    await page.route('**/api/memory/browse', route => {
      const request = route.request().postDataJSON()
      requests.push(request)
      if (fail) return route.fulfill({ status: 422, json: { detail: 'Invalid target time' } })
      const scheduled = request.temporal.target_at.startsWith('2027-09-27') ? [{
        item: { ...item, id: 'scheduled-memory', title: 'Scheduled reminder',
          temporal: { month: 9, day: 27 } },
        score: 1, temporal_match_at: '2027-09-27T07:30:00Z',
      }] : []
      return route.fulfill({ json: {
        hits: [...scheduled, { item, score: 1, temporal_match_at: null }],
        total: 1 + scheduled.length, has_more: false,
        temporal_window: request.temporal ? { start: request.temporal.target_at, end: request.temporal.target_at, timezone: 'Europe/Paris' } : null,
      } })
    })
    await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
    await expect(page.getByText('Current memory', { exact: true })).toBeVisible()
    await expect(page.getByRole('switch')).toHaveCount(0)
    expect(requests).toHaveLength(1)
    await expect(page.getByLabel('Target date and time', { exact: true })).toHaveValue('2026-09-27T18:12')
    await expect.poll(() => requests.at(-1)?.temporal).toEqual({ target_at: '2026-09-27T16:12:00.000Z', lookahead_hours: 0 })
    await expect(page.getByLabel('Look ahead (hours)', { exact: true })).toHaveCount(0)
    await expect(page.getByLabel('Timezone', { exact: true })).toHaveCount(0)
    await page.getByLabel('Target date and time', { exact: true }).fill('2027-09-27T09:30')
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    await expect.poll(() => requests.at(-1)?.temporal).toEqual({ target_at: '2027-09-27T09:30', lookahead_hours: 0 })
    await expect(page.getByText(/^Match:/)).toBeVisible()
    const expectedMatch = await page.evaluate(() => new Intl.DateTimeFormat('en', {
      timeZone: 'Europe/Paris', dateStyle: 'medium', timeStyle: 'short',
    }).format(new Date('2027-09-27T07:30:00Z')))
    await expect(page.getByText(/^Match:/)).toContainText(expectedMatch)
    await expect(page.getByText('Scheduled reminder', { exact: true })).toBeVisible()
    await expect(page.getByText('Current memory', { exact: true })).toBeVisible()
    await page.getByPlaceholder('Search titles, keywords, and content').fill('calendar')
    await expect.poll(() => requests.at(-1)?.query).toBe('calendar')
    expect(requests.at(-1).temporal.target_at).toBe('2027-09-27T09:30')
    await page.getByText('Current memory', { exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
    // Returning to the list keeps the simulated target and its other filters.
    await page.getByRole('tab', { name: 'Graph', exact: true }).click()
    await page.getByRole('tab', { name: 'List', exact: true }).click()
    await expect(page.getByLabel('Target date and time', { exact: true })).toHaveValue('2027-09-27T09:30')
    await page.getByLabel('Target date and time', { exact: true }).fill('')
    const requestCount = requests.length
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    expect(requests).toHaveLength(requestCount)
    await page.getByLabel('Target date and time', { exact: true }).fill('2027-09-28T09:30')
    fail = true
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    await expect(page.getByText('Current memory', { exact: true })).toHaveCount(0)
    await expect(page.getByText(/^Match:/)).toHaveCount(0)
    fail = false
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(page.getByText('Current memory', { exact: true })).toBeVisible()
    await expect(page.getByText('Scheduled reminder', { exact: true })).toHaveCount(0)
    expect(requests.at(-1).temporal.target_at).toBe('2027-09-28T09:30')
    expect(requests.at(-1).query).toBe('calendar')
    expect(requests.every(request => request.temporal?.target_at && request.temporal.lookahead_hours === 0)).toBe(true)
  })
}

test('calendar default keeps the current instant during a repeated global hour', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-25T01:30:45Z'))
  const { item } = await memoryItemFixtures(page)
  const requests = []
  await page.route('**/api/memory/browse', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { hits: [{ item, score: 1 }], total: 1, has_more: false } })
  })
  await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
  await expect(page.getByText('Current memory', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Target date and time', { exact: true })).toHaveValue('2026-10-25T02:30')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests.at(-1).temporal).toEqual({
    target_at: '2026-10-25T01:30:00.000Z', lookahead_hours: 0,
  })
})

test('calendar waits for the global timezone and recovers its loading failure', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-09-27T16:12:45Z'))
  await memoryItemFixtures(page)
  let fail = true
  await page.route('**/api/memory/temporal/defaults', route => route.fulfill(fail
    ? { status: 503, json: { detail: 'Synthetic settings failure' } }
    : { json: { timezone: 'Europe/Paris', lookahead_hours: 24 } }))
  const requests = []
  await page.route('**/api/memory/browse', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { hits: [], total: 0, has_more: false } })
  })
  await mount(page, 'app/memory/pages/index.vue', { route: '/memory?agent=7' })
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  await expect(page.getByLabel('Target date and time', { exact: true })).toBeDisabled()
  expect(requests).toEqual([])
  fail = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByLabel('Target date and time', { exact: true })).toHaveValue('2026-09-27T18:12')
  await expect.poll(() => requests.length).toBe(1)
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
  expect(requests[0].temporal).not.toHaveProperty('timezone')
})
})

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
    await expect(page.getByRole('dialog').locator('.q-toolbar__title')).toHaveText(locale === 'fr' ? 'Mémoire - Souvenir' : 'Memory - Memory')
  })
}

for (const width of [1440, 390]) {
  test(`attachment memory keeps its description and opens the original file at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const { item } = await memoryItemFixtures(page)
    Object.assign(item, { node_kind: 'attachment', primary_url: 'document://11111111-1111-1111-1111-111111111111/attachments/22222222-2222-2222-2222-222222222222', metadata: {
      resource_media_type: 'text/markdown',
    } })
    await jsonRoute(page, '**/api/memory/items/doc-a?*', item)
    await jsonRoute(page, '**/api/memory/documents/*/attachments/*/info?*', {
      id: '22222222-2222-2222-2222-222222222222', name: 'Original.md', media_type: 'text/markdown', size_bytes: 30,
    })
    // This text attachment has no generated thumbnail; its original remains openable.
    await page.route('**/api/memory/documents/11111111-1111-1111-1111-111111111111/attachments/22222222-2222-2222-2222-222222222222/thumbnail?*', route => route.fulfill({ status: 404 }))
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
    const detail = page.getByRole('dialog')
    await expect(detail.getByText('Current body', { exact: true })).toBeVisible()
    await detail.getByRole('button', { name: 'Open preview of Original.md', exact: true }).first().click()
    await expect(viewer.getByText('Full file content.', { exact: true })).toBeVisible()
    await viewer.getByRole('button', { name: 'Close', exact: true }).click()
    await detail.getByRole('tab', { name: 'Links and relations', exact: true }).click()
    await detail.getByRole('tab', { name: 'Memory', exact: true }).click()
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
      ['memory', '**/api/memory/items/doc-a?*', { json: { ...document, node_kind: 'attachment', primary_url: `document://${documentId}/attachments/${attachmentId}`, metadata: {} } }],
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

for (const nodeKind of ['memory', 'document']) test(`revocation clears an open ${nodeKind} memory and ignores a late browse response`, async ({ page }) => {
  const { item } = await memoryItemFixtures(page)
  Object.assign(item, { node_kind: nodeKind })
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
    await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT', 'TASK_ACCESS'], route: '/memory?agent=7' })
    await page.getByText('Current memory', { exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Current body', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Owner agent', { exact: true })).toHaveCount(0)
    expect(reads).toEqual([])
    await dialog.screenshot({ path: testInfo.outputPath('memory-view.png'), animations: 'disabled' })
    await dialog.getByRole('tab', { name: 'History', exact: true }).click()
    await expect(dialog.getByText('Original body', { exact: true })).toBeVisible()
    await expect(dialog.getByText('Saved version 1', { exact: true })).toBeVisible()
    await dialog.getByText('Version 2', { exact: true }).first().click()
    await expect(dialog.getByText('Revised body', { exact: true })).toBeVisible()
    await dialog.screenshot({ path: testInfo.outputPath('memory-history.png'), animations: 'disabled' })
    await dialog.getByRole('tab', { name: 'Memory', exact: true }).click()
    await dialog.locator('[data-editor-surface]').fill('My current draft')
    const keywordField = dialog.locator('.memory-form-keywords')
    await expect(keywordField.locator('.q-chip')).toContainText('current')
    await dialog.getByRole('combobox', { name: 'Keywords', exact: true }).fill(' release, notes ')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Escape')
    await expect(keywordField.locator('.q-chip')).toContainText(['current', 'release, notes'])
    await dialog.getByRole('tab', { name: 'History', exact: true }).click()
    await expect(dialog.getByText('Original body', { exact: true })).toBeVisible()
    await dialog.getByRole('tab', { name: 'Memory', exact: true }).click()
    await expect(dialog.locator('[data-editor-surface]')).toHaveText('My current draft')
    await expect(keywordField.locator('.q-chip').last()).toContainText('release, notes')
    await dialog.getByLabel('Day of month', { exact: true }).fill('27')
    await dialog.getByLabel('Month', { exact: true }).fill('9')
    await dialog.getByLabel('Hour', { exact: true }).fill('0')
    await dialog.getByLabel('Minute', { exact: true }).fill('0')
    await expect(dialog.getByLabel('Year', { exact: true })).toHaveValue('')
    const linksTab = dialog.getByRole('tab', { name: 'Links and relations', exact: true })
    await linksTab.focus()
    await page.keyboard.press('Enter')
    await expect(linksTab).toHaveAttribute('aria-selected', 'true')
    await expect(dialog.getByRole('link', { name: item.source_refs[0], exact: true }))
      .toHaveAttribute('href', '/task?task_id=11111111-1111-1111-1111-111111111111')
    await expect(dialog.getByText('No explicit relation.', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Add relation', exact: true })).toBeEnabled()
    await dialog.screenshot({ path: testInfo.outputPath('memory-links.png'), animations: 'disabled' })
    await dialog.getByRole('tab', { name: 'Memory', exact: true }).click()
    await expect(dialog.locator('[data-editor-surface]')).toHaveText('My current draft')
    await expect(dialog.getByLabel('Day of month', { exact: true })).toHaveValue('27')
    await expect(dialog.locator('[data-editor-surface]')).toHaveText('My current draft')
    await page.evaluate(() => window.testApp.dark(true))
    await dialog.screenshot({ path: testInfo.outputPath('memory-view-dark.png'), animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(false))
    await linksTab.click()
    expect(writes).toEqual([])
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]).toMatchObject({ expected_revision: 3, keywords: ['current', 'release, notes'], payload: { text: '<p>My current draft</p>' } })
    expect(writes[0]).not.toHaveProperty('title')
    expect(writes[0]).not.toHaveProperty('summary')
    expect(writes[0]).not.toHaveProperty('reason')
    expect(writes[0].temporal).toMatchObject({ day: 27, month: 9, hour: 0, minute: 0 })
    expect(writes[0].temporal).not.toHaveProperty('timezone')
    await expect(dialog.getByRole('tab', { name: 'Memory', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(dialog.getByText('My current draft', { exact: true })).toBeVisible()
    await dialog.locator('[data-editor-surface]').fill('Second saved content')
    await expect(dialog.getByLabel('Day of month', { exact: true })).toHaveValue('27')
    await dialog.getByRole('button', { name: 'Remove temporality', exact: true }).click()
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(2)
    expect(writes[1]).toMatchObject({ expected_revision: 4, payload: { text: '<p>Second saved content</p>' } })
    expect(writes[1].temporal).toBeNull()
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
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('Current body')
  await expect(dialog.locator('[data-editor-surface]')).toHaveAttribute('contenteditable', 'false')
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

for (const locale of ['fr', 'en']) for (const width of [1440, 390]) {
  test(`memory relation labels are readable in ${locale} at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
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
    await dialog.getByRole('tab', { name: locale === 'fr' ? 'Liens et relations' : 'Links and relations', exact: true }).click()
    await expect(dialog.getByText(item.source_refs[0], { exact: true })).toBeVisible()
    await expect(dialog.getByRole('link', { name: item.source_refs[0], exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: locale === 'fr' ? 'Ajouter une relation' : 'Add relation', exact: true })).toHaveCount(0)
    for (const [, fr, en] of relations) {
      await expect(dialog.getByText(locale === 'fr' ? fr : en, { exact: true })).toBeVisible()
    }
    await page.screenshot({ path: testInfo.outputPath('memory-relations.png') })
  })
}

export async function documentFixtures(page) {
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, /\/api\/memory\/documents\/doc-a(?:\?.*)?$/, { item: document, agent_id: 7 })
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [{ path: 'Reports', kind: 'custom', shared: false }])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
}

test('memory list combines hybrid search and calendar, then opens a returned memory', async ({ page }) => {
  const { item } = await memoryItemFixtures(page)
  let deleted = false
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'DELETE') {
      expect(new URL(route.request().url()).searchParams.get('actor_agent_id')).toBe('7')
      deleted = true
      return route.fulfill({ status: 204 })
    }
    return route.fulfill({ json: item })
  })
  const requests = []
  await page.route('**/api/memory/browse', route => {
    requests.push(route.request().postDataJSON())
    const searched = Boolean(requests.at(-1).query) && !deleted
    return route.fulfill({ json: { hits: deleted ? [] : [{ item, score: 0.9 }], total: deleted ? 0 : 1, has_more: false,
      recall_truncated: searched, degradation_reason: searched ? 'embedding_unavailable' : null } })
  })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
  await expect(page.getByText('Current memory', { exact: true })).toBeVisible()
  await page.getByPlaceholder('Search titles, keywords, and content').fill('project evidence')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ agent_id: 7, query: 'project evidence', hybrid: true })
  expect(requests.at(-1).temporal.target_at).toBeTruthy()
  await expect(page.getByText('Results are limited. Refine your search to explore other memories.')).toBeVisible()
  await expect(page.getByText('Semantic search is unavailable. Results match the search words.')).toBeVisible()
  await page.getByText('Current memory', { exact: true }).click()
  await expect(page.getByRole('dialog').locator('.q-toolbar__title')).toHaveText('Memory - Memory')
  await page.getByRole('button', { name: 'Forget permanently', exact: true }).click()
  await page.getByRole('dialog').last().getByRole('button', { name: 'Forget permanently', exact: true }).click()
  await expect.poll(() => deleted).toBe(true)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('Current memory', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Results are limited. Refine your search to explore other memories.')).toHaveCount(0)
})

test('document editor autosaves with its revision and preserves read-only content', async ({ page }) => {
  await documentFixtures(page)
  const updates = []
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { item: document, agent_id: 7 } })
    expect(route.request().method()).toBe('PATCH')
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

for (const remoteField of ['content', 'keywords']) test(`a remote document ${remoteField} change merges untouched fields without losing the local draft`, async ({ page }) => {
  await documentFixtures(page)
  let current = { ...document }
  const updates = []
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { item: current, agent_id: 7 } })
    const body = route.request().postDataJSON()
    updates.push(body)
    current = { ...current, ...body, revision: current.revision + 1 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7, editable: true }, privileges: ['MEMORY_EDIT'] })
  const title = page.getByLabel('Title', { exact: true })
  await expect(title).toHaveValue(document.title)
  const clockTime = new Date('2026-01-01T00:00:00Z')
  await page.clock.install({ time: clockTime })
  await page.clock.pauseAt(new Date(clockTime.getTime() + 1000))
  await title.fill('Local draft')
  current = remoteField === 'content'
    ? { ...document, revision: 4, payload: { text: '# Remote content' } }
    : { ...document, lock_version: document.lock_version + 1, keywords: ['shared-classification'] }
  await page.evaluate(({ revision, lock_version }) => window.testApp.emitSocket('memory.update', {
    data: { id: 'doc-a', node_kind: 'document', revision, lock_version },
  }), current)
  await page.clock.runFor(250)
  await expect(page.locator('.document-editor-revision-button')).toContainText(String(current.revision))
  if (remoteField === 'keywords') {
    await expect(page.locator('.document-editor-keywords-field .q-chip')).toContainText(['shared-classification'])
  }
  await expect(title).toHaveValue('Local draft')
  await page.clock.runFor(1000)
  await expect.poll(() => updates.length).toBe(1)
  expect(updates[0]).toMatchObject({ title: 'Local draft', expected_revision: remoteField === 'content' ? 4 : document.revision })
  expect(updates[0]).not.toHaveProperty('payload')
  expect(updates[0]).not.toHaveProperty('keywords')
  await expect(title).toHaveValue('Local draft')
  await expect(page.locator('.document-editor-revision-button')).toContainText(String(current.revision))
})

for (const width of [1440, 390]) test(`document keyword changes refresh its open memory without losing the synthesis draft at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const { item } = await memoryItemFixtures(page)
  Object.assign(item, { node_kind: 'document', document_id: item.id })
  const writes = []
  await page.route('**/api/memory/items/doc-a?*', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: item })
    const body = route.request().postDataJSON()
    writes.push(body)
    Object.assign(item, body, { lock_version: item.lock_version + 1 })
    return route.fulfill({ json: item })
  })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
  const openMemory = () => width < 1024
    ? page.locator('.memory-mobile-title').filter({ hasText: 'Current memory' }).click()
    : page.getByText('Current memory', { exact: true }).click()
  await openMemory()
  const dialog = page.getByRole('dialog')
  const keywords = dialog.locator('.memory-form-keywords .q-chip__content')
  await expect(dialog.getByRole('button', { name: 'Forget', exact: true })).toHaveCount(0)
  await expect(keywords).toContainText(['current'])
  await dialog.locator('[data-editor-surface]').fill('Local synthesis draft')
  const expectedLock = ++item.lock_version
  item.keywords = ['shared-classification']
  await page.evaluate(({ revision, lock_version }) => window.testApp.emitSocket('memory.update', {
    data: { id: 'doc-a', node_kind: 'document', revision, lock_version },
  }), item)
  await expect(keywords).toHaveText(['shared-classification'])
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('Local synthesis draft')
  await dialog.getByRole('combobox', { name: 'Keywords', exact: true }).fill('memory-classification')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ expected_lock_version: expectedLock,
    keywords: ['shared-classification', 'memory-classification'], payload: { text: '<p>Local synthesis draft</p>' } })
  await expect(keywords).toHaveText(['shared-classification', 'memory-classification'])
  await page.screenshot({ path: testInfo.outputPath('shared-document-memory-keywords.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await openMemory()
  await expect(keywords).toHaveText(['shared-classification', 'memory-classification'])
})

test('conflicting shared keyword changes preserve the memory draft and its original lock', async ({ page }) => {
  const { item } = await memoryItemFixtures(page)
  Object.assign(item, { node_kind: 'document', document_id: item.id })
  const originalLock = item.lock_version
  const writes = []
  await page.route('**/api/memory/items/doc-a?*', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: item })
    writes.push(route.request().postDataJSON())
    await route.fulfill({ status: 409, json: { detail: 'Document or synthesis changed; reload and retry' } })
  })
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
  await page.getByText('Current memory', { exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Keywords', exact: true }).fill('local-keyword')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  item.keywords = ['remote-keyword']
  item.lock_version++
  await page.evaluate(() => window.testApp.emitSocket('memory.update', {
    data: { id: 'doc-a', node_kind: 'document', revision: 3 },
  }))
  await expect.poll(() => page.evaluate(() => window.testApp.pinia.state.value.memory.currentItem.keywords)).toEqual(['remote-keyword'])
  await expect(dialog.locator('.memory-form-keywords .q-chip__content')).toHaveText(['current', 'local-keyword'])
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].expected_lock_version).toBe(originalLock)
  await expect(page.locator('.q-notification')).toContainText('Document or synthesis changed')
  await expect(dialog.locator('.memory-form-keywords .q-chip__content')).toHaveText(['current', 'local-keyword'])
})

test('document keyword refreshes recover errors and ignore late replies after reopening', async ({ page }) => {
  const { item } = await memoryItemFixtures(page)
  Object.assign(item, { node_kind: 'document', document_id: item.id })
  let nextRead, release, waiting = false
  await page.route('**/api/memory/items/doc-a?*', async route => {
    const mode = nextRead
    nextRead = undefined
    if (mode === 'error') return route.fulfill({ status: 503, json: { detail: 'Synthetic refresh failure' } })
    const snapshot = JSON.stringify(item)
    if (mode === 'late') {
      waiting = true
      await new Promise(resolve => { release = resolve })
    }
    await route.fulfill({ contentType: 'application/json', body: snapshot })
  })
  const notify = () => page.evaluate(() => window.testApp.emitSocket('memory.update', {
    data: { id: 'doc-a', node_kind: 'document', revision: 3 },
  }))
  await mount(page, 'app/memory/pages/index.vue', { privileges: ['MEMORY_EDIT'], route: '/memory?agent=7' })
  await page.getByText('Current memory', { exact: true }).click()
  const dialog = page.getByRole('dialog')
  const keywords = dialog.locator('.memory-form-keywords .q-chip__content')
  await dialog.locator('[data-editor-surface]').fill('Preserved local draft')
  nextRead = 'error'
  await notify()
  await expect(page.locator('.q-notification')).toContainText('Synthetic refresh failure')
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('Preserved local draft')
  item.keywords = ['recovered']
  item.lock_version++
  await notify()
  await expect(keywords).toHaveText(['recovered'])
  await expect(dialog.locator('[data-editor-surface]')).toHaveText('Preserved local draft')
  nextRead = 'late'
  await notify()
  await expect.poll(() => waiting).toBe(true)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  item.keywords = ['reopened-current']
  item.lock_version++
  await page.getByText('Current memory', { exact: true }).click()
  await expect(keywords).toHaveText(['reopened-current'])
  const lateResponse = page.waitForResponse(response => response.url().includes('/api/memory/items/doc-a'))
  release()
  await lateResponse
  await expect(keywords).toHaveText(['reopened-current'])
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
  await page.route(/\/api\/memory\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { item: current, agent_id: 7 } })
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
