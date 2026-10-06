import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

async function memoryItemFixtures(page) {
  const item = { ...document, title: 'Current memory', node_kind: 'memory', memory_type: 'semantic',
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
  await jsonRoute(page, '**/api/memory/items/doc-a/sharing', { lock_version: 3, can_manage: true, grants: [], options: [],
    level: 'private', can_write: false, owner: { kind: 'agent', id: 7, label: 'Alice', can_write: true }, owner_groups: [] })
  await page.route('**/api/memory/browse', route => route.fulfill({ json: { hits: [{ item, score: 1 }], total: 1, has_more: false } }))
  return { item, versions }
}

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
  for (const item of items) await jsonRoute(page, `**/api/memory/items/${item.id}?*`, item)
  const resource = { id: 'image-a', name: 'Illustration.png', media_type: 'image/png', size_bytes: 100, uri: 'file://synthetic/illustration.png' }
  await jsonRoute(page, '**/api/file-share/items/doc-a/resources?*', [resource])
  await jsonRoute(page, '**/api/file-share/items/unavailable-a/resources?*', [resource])
  await page.route('**/api/file-share/items/doc-a/resources/image-a/thumbnail?*', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/file-share/items/unavailable-a/resources/image-a/thumbnail?*', route => route.fulfill({ status: 404 }))
  await page.route('**/api/memory/documents/00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002/thumbnail?*', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/memory/documents/document-a/thumbnail?*', route => route.fulfill({ contentType: 'image/png', body: png }))
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
  await expect(page.getByRole('dialog').getByLabel('Title', { exact: true })).toHaveValue('Indexed illustration')
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

for (const nodeKind of ['file', 'directory']) {
  test(`catalogue ${nodeKind} title and content can be saved and reopened`, async ({ page }) => {
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
    await dialog.getByLabel('Title', { exact: true }).fill('Personal catalogue title')
    const editor = dialog.locator('.ck-editor__editable')
    await expect(editor).toBeEditable()
    await editor.fill('Personal catalogue content')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]).toMatchObject({ title: 'Personal catalogue title',
      payload: { text: '<p>Personal catalogue content</p>' } })
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toBeHidden()
    await page.getByText('Personal catalogue title', { exact: true }).click()
    await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Personal catalogue title')
    await expect(dialog.locator('.ck-editor__editable')).toHaveText('Personal catalogue content')
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
    await viewer.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(viewer).toBeHidden()
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

for (const width of [1440, 390]) test(`file and directory graph markers agree with their legend through filtering and theme changes at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const kinds = ['file', 'directory', 'attachment', 'folder']
  const timestamp = new Date().toISOString()
  const nodes = kinds.map(kind => ({
    id: `catalogue-${kind}`, node_kind: kind, entity_kind: kind,
    title: `Synthetic ${kind}`, owner_agent_id: 7, memory_type: 'working',
    visibility: 'private', source_managed: true, access_count: 0,
    last_accessed_at: null, created_at: timestamp, updated_at: timestamp,
    activity_at: timestamp, has_relations: false, relation_count: 0,
  }))
  await jsonRoute(page, '**/api/memory/graph/roots', {
    nodes, edges: [], has_more: false, next_cursor: null, edges_truncated: false,
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: {
    agentId: 7, query: '', memoryTypes: [], topicItemId: null,
    contactItemId: null, timeRangeMilliseconds: null,
  } })
  const graphColors = async () => page.evaluate(async () => {
    const moduleUrl = performance.getEntriesByType('resource')
      .map(entry => entry.name).find(name => /\/echarts(?:\/core|_core)\.js/.test(name))
    if (!moduleUrl) throw new Error('The real graph renderer was not loaded')
    const echarts = await import(moduleUrl)
    const chart = echarts.getInstanceByDom(document.querySelector('.memory-graph__chart'))
    if (!chart) return []
    const series = chart.getModel().getSeries()[0]
    if (!series) return []
    const data = series.getData()
    const context = document.createElement('canvas').getContext('2d')
    const normalize = color => { context.fillStyle = color; return context.fillStyle }
    return chart.getOption().series[0].data.flatMap((node, index) => {
      // Invisible placeholders reserve the map bounds; only actual markers belong to the legend.
      if (node.symbol === 'none') return []
      const kind = node.id.replace('catalogue-', '')
      const legend = document.querySelector(`.memory-graph__role-symbol--${kind}`)
      return [{ kind, color: normalize(data.getItemVisual(index, 'style').fill),
        legend: normalize(getComputedStyle(legend).backgroundColor) }]
    })
  })
  for (const dark of [false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await expect.poll(async () => (await graphColors()).map(row => row.kind).sort()).toEqual([...kinds].sort())
    for (const row of await graphColors()) expect(row.color, `${row.kind} must match its legend`).toBe(row.legend)
    const files = page.getByRole('button', { name: 'Hide “File” nodes and their relationships', exact: true })
    await files.click()
    await expect.poll(async () => (await graphColors()).map(row => row.kind).sort()).toEqual(kinds.filter(kind => kind !== 'file').sort())
    await page.getByRole('button', { name: 'Show “File” nodes and their relationships', exact: true }).click()
    await expect.poll(async () => (await graphColors()).length).toBe(kinds.length)
    await page.screenshot({ path: testInfo.outputPath(`graph-${dark ? 'dark' : 'light'}.png`), animations: 'disabled' })
  }
})

for (const [count, interconnected] of [[500, false], [3000, false], [3000, true]]) test(`a ${count}-node ${interconnected ? 'interconnected ' : ''}graph becomes usable and keeps every paginated node`, async ({ page }, testInfo) => {
  test.setTimeout(60_000)
  const timestamp = new Date().toISOString()
  const nodes = Array.from({ length: count }, (_, index) => ({
    id: `synthetic-${index}`, title: `Synthetic memory ${index}`, node_kind: 'memory', entity_kind: 'memory',
    owner_agent_id: 7, memory_type: 'semantic', visibility: 'private', source_managed: false,
    access_count: 0, last_accessed_at: null, created_at: timestamp, updated_at: timestamp,
    activity_at: timestamp, has_relations: true, relation_count: interconnected ? 4 : index > 0 ? 1 : count - 1,
  }))
  const requests = []
  const connections = interconnected ? nodes.flatMap((node, index) => [1, 7].map(step => ({ id: `edge-${node.id}-${step}`,
    source_item_id: node.id, target_item_id: nodes[(index + step) % count].id,
    relation_type: 'related_to', confidence: 1, suggested: false }))) : []
  await page.route('**/api/memory/graph/roots', async route => {
    const body = route.request().postDataJSON()
    requests.push(body)
    const offset = body.cursor ? Number(body.cursor.id) : 0
    const end = Math.min(count, offset + body.limit)
    const pageIds = new Set(nodes.slice(offset, end).map(node => node.id))
    const knownIds = new Set([...body.known_item_ids, ...pageIds])
    await route.fulfill({ json: { nodes: nodes.slice(offset, end),
      edges: interconnected ? connections.filter(edge => knownIds.has(edge.source_item_id) && knownIds.has(edge.target_item_id)
        && (pageIds.has(edge.source_item_id) || pageIds.has(edge.target_item_id)))
        : nodes.slice(Math.max(1, offset), end).map(node => ({ id: `edge-${node.id}`,
          source_item_id: nodes[0].id, target_item_id: node.id, relation_type: 'related_to', confidence: 1, suggested: false })),
      has_more: end < count, next_cursor: end < count ? { id: String(end), activity_at: timestamp } : null,
      edges_truncated: false } })
  })
  const start = Date.now()
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: {
    agentId: 7, query: '', memoryTypes: [], topicItemId: null, contactItemId: null, timeRangeMilliseconds: null,
  } })
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0, { timeout: 20_000 })
  await expect(page.locator('.memory-graph__chart canvas')).toBeVisible()
  await expect(page.getByText(`${count} node(s)`, { exact: true })).toBeVisible()
  const represented = await graphSnapshot(page)
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await testInfo.attach('graph-loading.json', { body: JSON.stringify({ nodes: count,
    milliseconds: Date.now() - start, requests: requests.length,
    rendered: represented.nodes.filter(node => node.symbol !== 'none').length }), contentType: 'application/json' })
  if (interconnected) {
    expect(represented.nodes.filter(node => node.symbol !== 'none')).toHaveLength(count)
    expect(represented.edges).toHaveLength(count * 2)
    await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
    expect((await graphSnapshot(page)).nodes).toEqual(represented.nodes)
    return
  }
  const expansionStart = Date.now()
  await page.getByRole('switch', { name: 'Branch details', exact: true }).click()
  await expect(page.getByText(`${count - 1} grouped node(s)`, { exact: true })).toHaveCount(0)
  const detailed = await graphSnapshot(page)
  expect(detailed.nodes.filter(node => node.symbol !== 'none')).toHaveLength(count)
  if (count > 600) expect(detailed.nodes.map(({ id, x, y }) => ({ id, x, y }))).toEqual(represented.nodes.map(({ id, x, y }) => ({ id, x, y })))
  else expect(detailed.layout).toBe('force')
  await testInfo.attach('graph-expansion.json', { body: JSON.stringify({ nodes: count,
    milliseconds: Date.now() - expansionStart, requests: requests.length }), contentType: 'application/json' })
})

async function graphSnapshot(page) {
  return page.evaluate(async () => {
    const moduleUrl = performance.getEntriesByType('resource')
      .map(entry => entry.name).find(name => /\/echarts(?:\/core|_core)\.js/.test(name))
    const echarts = await import(moduleUrl)
    const chart = echarts.getInstanceByDom(document.querySelector('.memory-graph__chart'))
    const series = chart.getOption().series[0]
    // Test-only observation of the live renderer: production uses public chart actions.
    const data = chart.getModel().getSeries()[0].getData()
    const nodes = series.data.map((node, index) => {
      const point = series.layout === 'force' ? data.getItemLayout(index) : [node.x, node.y]
      return { id: node.id, symbol: node.symbol, x: point[0], y: point[1] }
    })
    return { layout: series.layout, nodes,
      edges: series.links, center: series.center, zoom: series.zoom,
      points: nodes.map(node => ({ id: node.id, point: chart.convertToPixel({ seriesId: series.id }, [node.x, node.y]) })) }
  })
}

async function settledGraph(page, timeout = 20_000) {
  let previous = await graphSnapshot(page)
  let sampled = false
  await expect.poll(async () => {
    const current = await graphSnapshot(page)
    const moved = Math.max(...current.nodes.map((node, index) => Math.hypot(node.x - previous.nodes[index]?.x,
      node.y - previous.nodes[index]?.y)))
    previous = current
    if (!sampled) { sampled = true; return Infinity }
    return moved
  }, { timeout, intervals: [400] }).toBe(0)
  return previous
}

async function recordGraphReveal(page, ids) {
  return page.evaluate(async memberIds => {
    const moduleUrl = performance.getEntriesByType('resource')
      .map(entry => entry.name).find(name => /\/echarts(?:\/core|_core)\.js/.test(name))
    const echarts = await import(moduleUrl)
    const chart = echarts.getInstanceByDom(document.querySelector('.memory-graph__chart'))
    const wanted = new Set(memberIds), frames = [], start = performance.now()
    return new Promise(resolve => {
      const sample = () => {
        const data = chart.getModel().getSeries()[0].getData()
        const opacity = []
        for (let index = 0; index < data.count(); index++) {
          if (!wanted.has(data.getId(index))) continue
          const symbol = data.getItemGraphicEl(index)?.childAt(0)
          if (symbol) opacity.push(symbol.style.opacity)
        }
        frames.push(opacity)
        if ((opacity.length === wanted.size && opacity.every(value => value === 1)) || performance.now() - start > 4000) {
          resolve(frames)
        } else requestAnimationFrame(sample)
      }
      requestAnimationFrame(sample)
    })
  }, ids)
}

for (const width of [1440, 750, 390]) test(`mixed graph keeps linked subjects together through branch expansion at ${width}px`, async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width, height: 1000 })
  const timestamp = new Date().toISOString()
  const nodes = [], edges = []
  const addNode = (id, entity_kind = 'memory') => nodes.push({ id, title: `Synthetic ${id}`, entity_kind,
    node_kind: entity_kind === 'topic' || entity_kind === 'contact' ? 'memory' : entity_kind,
    owner_agent_id: 7, memory_type: entity_kind === 'contact' ? 'social' : 'semantic', visibility: 'private',
    source_managed: false, access_count: 0, last_accessed_at: null, created_at: timestamp,
    updated_at: timestamp, activity_at: timestamp, has_relations: true, relation_count: 0 })
  const addEdge = (source, target, relation_type = 'topic_contains') => edges.push({ id: `link-${edges.length}`,
    source_item_id: source, target_item_id: target, relation_type, confidence: 1, suggested: false })
  for (let group = 0; group < 8; group++) addNode(`subject-${group}`, 'topic')
  for (let contact = 0; contact < 2; contact++) addNode(`contact-${contact}`, 'contact')
  for (let i = 0; i < 96; i++) {
    addNode(`leaf-${i}`, i % 3 === 0 ? 'file' : 'memory')
    addEdge(`subject-${i % 8}`, `leaf-${i}`)
  }
  for (let i = 0; i < 64; i++) {
    addNode(`shared-${i}`, i % 4 === 0 ? 'document' : 'memory')
    addEdge(`subject-${i % 8}`, `shared-${i}`)
    addEdge(`shared-${i}`, `shared-${(i + 8) % 64}`, 'related_to')
    addEdge('contact-0', `shared-${i}`, 'contact_contains')
    if (i % 8 === 1) addEdge('contact-1', `shared-${i}`, 'contact_contains')
  }
  for (let group = 0; group < 7; group++) addEdge(`subject-${group}`, `subject-${group + 1}`, 'related_to')
  for (let i = 0; i < 8; i++) addNode(`isolated-${i}`)
  for (const node of nodes) {
    node.relation_count = new Set(edges.flatMap(edge => edge.source_item_id === node.id ? [edge.target_item_id]
      : edge.target_item_id === node.id ? [edge.source_item_id] : [])).size
    node.has_relations = node.relation_count > 0
  }
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes, edges, has_more: false, next_cursor: null, edges_truncated: false })
  const start = Date.now()
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: {
    agentId: 7, query: '', memoryTypes: [], topicItemId: null, contactItemId: null, timeRangeMilliseconds: null,
  } })
  await expect(page.getByText('96 grouped node(s)', { exact: true })).toBeVisible()
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  const moving = await graphSnapshot(page)
  expect(moving.layout).toBe('force')
  await expect.poll(async () => (await graphSnapshot(page)).nodes).not.toEqual(moving.nodes)
  const settlingStart = Date.now()
  const initial = await settledGraph(page)
  const settlingMilliseconds = Date.now() - settlingStart
  const positions = new Map(initial.nodes.map(node => [node.id, node]))
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y)
  let local = 0, remote = 0
  for (let i = 0; i < 64; i++) {
    local += distance(positions.get(`shared-${i}`), positions.get(`subject-${i % 8}`))
    remote += distance(positions.get(`shared-${i}`), positions.get(`subject-${(i + 4) % 8}`))
  }
  expect(local).toBeLessThan(remote)
  await testInfo.attach('mixed-layout.json', { body: JSON.stringify({ nodes: nodes.length, edges: edges.length,
    milliseconds: Date.now() - start, settlingMilliseconds, meanLocalDistance: local / 64, meanRemoteDistance: remote / 64 }),
    contentType: 'application/json' })
  await page.screenshot({ path: testInfo.outputPath('mixed-graph-collapsed.png') })
  await page.getByRole('switch', { name: 'Branch details', exact: true }).click()
  await expect(page.getByText('96 grouped node(s)', { exact: true })).toHaveCount(0)
  const expanded = await settledGraph(page, 2500)
  expect(expanded.nodes).toHaveLength(nodes.length)
  for (const node of expanded.nodes) {
    const previous = initial.nodes.find(candidate => candidate.id === node.id)
    if (previous) expect({ x: node.x, y: node.y }).toEqual({ x: previous.x, y: previous.y })
  }
  expect(expanded.center).toEqual(initial.center)
  expect(expanded.zoom).toBe(initial.zoom)
  await page.screenshot({ path: testInfo.outputPath('mixed-graph-expanded.png') })
  const linksShown = graph => graph.edges.filter(edge => edge.lineStyle.opacity > 0).length
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
  const far = await graphSnapshot(page)
  expect(linksShown(far)).toBeLessThan(linksShown(initial))
  const expandedPositions = new Map(expanded.nodes.map(node => [node.id, { x: node.x, y: node.y }]))
  for (const node of far.nodes) expect({ x: node.x, y: node.y }).toEqual(expandedPositions.get(node.id))
  await page.screenshot({ path: testInfo.outputPath('mixed-graph-overview.png') })
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  const zoomedBack = await settledGraph(page, 2500)
  expect(linksShown(zoomedBack)).toBe(linksShown(initial))
  for (const node of zoomedBack.nodes) expect({ x: node.x, y: node.y }).toEqual(expandedPositions.get(node.id))
})

for (const width of [1440, 390]) test(`exclusive branches reveal on zoom while keeping shared nodes accessible at ${width}px`, async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width, height: 1000 })
  const timestamp = new Date().toISOString()
  const makeNode = (id, relation_count) => ({ id, title: `Synthetic ${id}`, node_kind: 'memory', entity_kind: 'memory',
    owner_agent_id: 7, memory_type: 'semantic', visibility: 'private', source_managed: false, access_count: 0,
    last_accessed_at: null, created_at: timestamp, updated_at: timestamp, activity_at: timestamp,
    has_relations: relation_count > 0, relation_count })
  const nodes = [makeNode('anchor', 31), ...Array.from({ length: 30 }, (_, i) => makeNode(`leaf-${i}`, 1)),
    makeNode('shared', 2)]
  const edges = nodes.slice(1).map(node => ({ id: `edge-${node.id}`, source_item_id: 'anchor',
    target_item_id: node.id, relation_type: 'related_to', confidence: 1, suggested: false }))
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes, edges, has_more: false, next_cursor: null, edges_truncated: false })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: {
    agentId: 7, query: '', memoryTypes: [], topicItemId: null, contactItemId: null, timeRangeMilliseconds: null,
  } })
  await expect(page.getByText('30 grouped node(s)', { exact: true })).toBeVisible()
  const initial = await settledGraph(page)
  expect(initial.nodes.filter(node => node.symbol !== 'none').map(node => node.id).sort()).toEqual(['anchor', 'shared'])
  await page.screenshot({ path: testInfo.outputPath('branches-collapsed.png') })
  // The explicit switch gives keyboard/touch users the same access as zoom.
  const details = page.getByRole('switch', { name: 'Branch details', exact: true })
  await details.focus()
  await page.keyboard.press('Space')
  await expect(page.getByText('30 grouped node(s)', { exact: true })).toHaveCount(0)
  const expanded = await settledGraph(page)
  expect(expanded.nodes.every(node => node.symbol !== 'none')).toBe(true)
  expect(expanded.center).toEqual(initial.center)
  expect(expanded.zoom).toBe(initial.zoom)
  await page.screenshot({ path: testInfo.outputPath('branches-expanded.png') })
  await details.click()
  await expect(page.getByText('30 grouped node(s)', { exact: true })).toBeVisible()
  const reveal = recordGraphReveal(page, nodes.filter(node => node.id.startsWith('leaf-')).map(node => node.id))
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect(page.getByText('30 grouped node(s)', { exact: true })).toHaveCount(0)
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  const frames = await reveal
  expect(frames.some(opacity => opacity.some(value => value > 0 && value < 1))).toBe(true)
  expect(frames.some(opacity => new Set(opacity).size > 1)).toBe(true)
  expect(frames.at(-1)).toEqual(Array(30).fill(1))
  const near = await settledGraph(page)
  const box = await page.locator('.memory-graph__chart').boundingBox()
  // Dense leaves can overlap on mobile. Click an actually exposed symbol,
  // rather than assuming the first model coordinate is the topmost target.
  const hittable = await page.evaluate(async () => {
    const moduleUrl = performance.getEntriesByType('resource').map(entry => entry.name).find(name => /\/echarts(?:\/core|_core)\.js/.test(name))
    const chart = (await import(moduleUrl)).getInstanceByDom(document.querySelector('.memory-graph__chart'))
    const data = chart.getModel().getSeries()[0].getData(), ids = []
    for (let index = 0; index < data.count(); index++) {
      if (!data.getId(index).startsWith('leaf-')) continue
      const point = chart.convertToPixel({ seriesId: chart.getOption().series[0].id }, data.getItemLayout(index))
      if (chart.getZr().findHover(point[0], point[1]).target === data.getItemGraphicEl(index)?.childAt(0)) ids.push(data.getId(index))
    }
    return ids
  })
  const leaf = near.points.find(node => hittable.includes(node.id) && node.point[0] > 10 && node.point[0] < box.width - 10
    && node.point[1] > 10 && node.point[1] < box.height - 10)
  expect(leaf).toBeTruthy()
  const leafId = leaf.id, leafTitle = `Synthetic ${leafId}`
  expect(leaf.point[0]).toBeGreaterThan(0)
  expect(leaf.point[0]).toBeLessThan(box.width)
  expect(leaf.point[1]).toBeGreaterThan(0)
  expect(leaf.point[1]).toBeLessThan(box.height)
  await page.locator('.memory-graph__chart').click({ position: { x: leaf.point[0], y: leaf.point[1] } })
  if (width < 1024) {
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'open').map(event => event.value))).toEqual([leafId])
  } else {
    await expect(page.locator('.memory-graph__inspector').getByText(leafTitle, { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'View', exact: true }).click()
    expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'open').map(event => event.value))).toEqual([leafId])
    const pinned = await graphSnapshot(page)
    const blank = [{ x: 6, y: 6 }, { x: box.width - 6, y: 6 }, { x: 6, y: box.height - 6 }]
      .find(point => pinned.points.every(node => Math.hypot(node.point[0] - point.x, node.point[1] - point.y) > 60))
    expect(blank).toBeTruthy()
    await page.locator('.memory-graph__chart').click({ position: blank })
    await expect(page.locator('.memory-graph__inspector')).toHaveCount(0)
    const dismissed = await settledGraph(page, 2500)
    expect(dismissed.nodes).toEqual(pinned.nodes)
    expect(dismissed.points).toEqual(pinned.points)
    expect(dismissed.center).toEqual(pinned.center)
    expect(dismissed.zoom).toBe(pinned.zoom)
    await page.locator('.memory-graph__chart').click({ position: { x: leaf.point[0], y: leaf.point[1] } })
    await expect(page.locator('.memory-graph__inspector').getByText(leafTitle, { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
    await expect(page.locator('.memory-graph__inspector')).toHaveCount(0)
    const unpinnedByZoom = await settledGraph(page, 2500)
    for (const node of unpinnedByZoom.nodes) {
      const previous = pinned.nodes.find(candidate => candidate.id === node.id)
      expect({ x: node.x, y: node.y }).toEqual({ x: previous.x, y: previous.y })
    }
    const point = unpinnedByZoom.points.find(node => node.id === leafId).point
    await page.locator('.memory-graph__chart').click({ position: { x: point[0], y: point[1] } })
    await expect(page.locator('.memory-graph__inspector').getByText(leafTitle, { exact: true })).toBeVisible()
    await details.click()
    await expect(page.getByText('29 grouped node(s)', { exact: true })).toBeVisible()
    expect((await graphSnapshot(page)).nodes.find(node => node.id === leafId).symbol).not.toBe('none')
    await page.locator('.memory-graph__inspector').getByText('Synthetic anchor', { exact: true }).click()
    await expect(page.getByText('30 grouped node(s)', { exact: true })).toBeVisible()
    await page.locator('.memory-graph__inspector').getByText(leafTitle, { exact: true }).click()
    await expect(page.getByText('29 grouped node(s)', { exact: true })).toBeVisible()
    expect((await graphSnapshot(page)).nodes.find(node => node.id === leafId).symbol).not.toBe('none')
    const beforeRelease = await graphSnapshot(page)
    await page.getByRole('button', { name: 'Close details', exact: true }).click()
    await expect(page.getByText('30 grouped node(s)', { exact: true })).toBeVisible()
    await expect(page.locator('.memory-graph__inspector')).toHaveCount(0)
    const released = await settledGraph(page, 2500)
    for (const node of released.nodes) {
      const previous = beforeRelease.nodes.find(candidate => candidate.id === node.id)
      expect({ x: node.x, y: node.y }).toEqual({ x: previous.x, y: previous.y })
    }
    expect(released.center).toEqual(beforeRelease.center)
    expect(released.zoom).toBe(beforeRelease.zoom)
    expect(released.points).toEqual(beforeRelease.points)
    await details.click()
  }
  await page.screenshot({ path: testInfo.outputPath('branches-near.png') })
  for (let i = 0; i < 2; i++) await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
  await expect(page.getByText('30 grouped node(s)', { exact: true })).toBeVisible()
  const back = await graphSnapshot(page)
  expect(back.layout).toBe('force')
  expect(back.nodes.find(node => node.id === 'shared').symbol).not.toBe('none')
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  const fitted = await settledGraph(page)
  const anchor = fitted.points.find(node => node.id === 'anchor')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const immediate = recordGraphReveal(page, nodes.filter(node => node.id.startsWith('leaf-')).map(node => node.id))
  await page.locator('.memory-graph__chart').click({ position: { x: anchor.point[0], y: anchor.point[1] } })
  await expect(page.getByText('30 grouped node(s)', { exact: true })).toHaveCount(0)
  expect((await graphSnapshot(page)).zoom).toBeGreaterThanOrEqual(1.8)
  expect((await immediate).every(opacity => opacity.every(value => value === 1))).toBe(true)
})

test('graph errors can be retried and late branches cannot cross an agent change', async ({ page }) => {
  const timestamp = new Date().toISOString()
  const node = { id: 'recovered', title: 'Synthetic recovered memory', node_kind: 'memory', entity_kind: 'memory',
    owner_agent_id: 7, memory_type: 'semantic', visibility: 'private', source_managed: false, access_count: 0,
    last_accessed_at: null, created_at: timestamp, updated_at: timestamp, activity_at: timestamp,
    has_relations: false, relation_count: 0 }
  const empty = { nodes: [], edges: [], has_more: false, next_cursor: null, edges_truncated: false }
  let reads = 0, release, waiting = false
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/graph/roots', async route => {
    reads++
    if (reads === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary failure' } })
    if (reads === 3) { waiting = true; await pending }
    return route.fulfill({ json: { ...empty, nodes: route.request().postDataJSON().agent_id === 7 ? [node] : [] } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: {
    agentId: 7, query: '', memoryTypes: [], topicItemId: null, contactItemId: null, timeRangeMilliseconds: null,
  } })
  await expect(page.getByText('The memory graph could not be loaded.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('1 node(s)', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Reload graph', exact: true }).click()
  await expect.poll(() => waiting).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  await expect(page.getByText('No memory matches the active filters.', { exact: true })).toBeVisible()
  const late = page.waitForResponse(response => response.url().endsWith('/api/memory/graph/roots') && response.request().postDataJSON().agent_id === 7)
  release()
  await late
  expect((await graphSnapshot(page)).nodes).toEqual([])
  await page.evaluate(() => window.testApp.setProps({ agentId: 7 }))
  await expect(page.getByText('1 node(s)', { exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.emitSocket('memory.invalidate', { data: {} }))
  await expect.poll(() => reads).toBe(6)
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  expect((await graphSnapshot(page)).nodes.map(node => node.id)).toEqual(['recovered'])
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
        item: { ...item, id: 'scheduled-memory', title: 'Scheduled reminder', memory_type: 'working',
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
    await expect(page.getByRole('dialog').getByLabel(locale === 'fr' ? 'Titre' : 'Title', { exact: true })).toHaveValue(item.title)
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
    await dialog.getByLabel('Day of month', { exact: true }).fill('27')
    await dialog.getByLabel('Month', { exact: true }).fill('9')
    await dialog.getByLabel('Hour', { exact: true }).fill('0')
    await dialog.getByLabel('Minute', { exact: true }).fill('0')
    await expect(dialog.getByLabel('Year', { exact: true })).toHaveValue('')
    expect(writes).toEqual([])
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]).toMatchObject({ title: 'My current draft', expected_revision: 3, keywords: ['current', 'release, notes'], payload: { text: '<p>Current body</p>' } })
    expect(writes[0]).not.toHaveProperty('summary')
    expect(writes[0]).not.toHaveProperty('reason')
    expect(writes[0].temporal).toMatchObject({ day: 27, month: 9, hour: 0, minute: 0 })
    expect(writes[0].temporal).not.toHaveProperty('timezone')
    await expect(dialog.getByRole('tab', { name: 'Memory', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(dialog.getByText('Current body', { exact: true })).toBeVisible()
    await dialog.getByLabel('Title', { exact: true }).fill('Second saved title')
    await expect(dialog.getByLabel('Day of month', { exact: true })).toHaveValue('27')
    await dialog.getByRole('button', { name: 'Remove temporality', exact: true }).click()
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(2)
    expect(writes[1]).toMatchObject({ title: 'Second saved title', expected_revision: 4 })
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

test('memory list combines hybrid search, type and calendar, then opens a returned memory', async ({ page }) => {
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
  await page.getByLabel('Type', { exact: true }).click()
  await page.getByRole('option', { name: 'Knowledge', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ agent_id: 7, query: 'project evidence', memory_types: ['semantic'], hybrid: true })
  expect(requests.at(-1).temporal.target_at).toBeTruthy()
  await expect(page.getByText('Results are limited. Refine your search to explore other memories.')).toBeVisible()
  await expect(page.getByText('Semantic search is unavailable. Results match the search words.')).toBeVisible()
  await page.getByText('Current memory', { exact: true }).click()
  await expect(page.getByRole('dialog').getByLabel('Title', { exact: true })).toHaveValue(item.title)
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
  const clockTime = new Date('2026-01-01T00:00:00Z')
  await page.clock.install({ time: clockTime })
  await page.clock.pauseAt(new Date(clockTime.getTime() + 1000))
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
