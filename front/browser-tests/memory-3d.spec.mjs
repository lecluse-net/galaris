import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const timestamp = '2026-09-01T12:00:00Z'
const makeNode = (id, kind = 'memory', count = 0) => ({
  id, title: `Synthetic ${id}`, node_kind: kind, entity_kind: kind,
  owner_agent_id: 7, visibility: 'private', source_managed: false, access_count: 0,
  last_accessed_at: null, created_at: timestamp, updated_at: timestamp,
  activity_at: timestamp, has_relations: count > 0, relation_count: count,
})
const props = { agentId: 7, query: '', topicItemId: null, contactItemId: null }
const scene = page => page.locator('.memory-graph__chart--3d')
const snapshot = page => scene(page).evaluate(element => ({ ...element.dataset }))

let rendererWarnings = []
test.beforeEach(async ({ page }) => {
  rendererWarnings = []
  page.on('console', message => {
    // Chromium screenshots themselves cause driver ReadPixels performance
    // notices. Keep application/shader errors, rather than screenshot notices.
    if (['warning', 'error'].includes(message.type()) && /THREE|Shader Error|INVALID_/i.test(message.text())) rendererWarnings.push(message.text())
  })
})
test.afterEach(() => { expect(rendererWarnings).toEqual([]) })

async function graphFixture(page, nodes, edges = [], positions = {}, defer = false) {
  const requests = []
  const ready = new Promise(resolve => { requests.release = resolve })
  await page.route('**/api/memory/graph/roots', async route => {
    const body = route.request().postDataJSON()
    requests.push(body)
    const offset = Number(body.cursor?.id ?? 0), end = Math.min(nodes.length, offset + body.limit)
    const ids = new Set(nodes.slice(offset, end).map(node => node.id))
    if (defer && offset === 0) await ready
    await route.fulfill({ json: { nodes: nodes.slice(offset, end),
      edges: edges.filter(edge => ids.has(edge.source_item_id) || ids.has(edge.target_item_id)),
      positions: Object.fromEntries(Object.entries(positions).filter(([id]) => ids.has(id))),
      has_more: end < nodes.length, next_cursor: end < nodes.length ? { id: String(end), activity_at: timestamp } : null,
      edges_truncated: false } })
  })
  return requests
}

test('3D rebuilds an incompatible saved view and retries persistence without changing the current camera', async ({ page }) => {
  const root = makeNode('10000000-0000-4000-8000-000000000001', 'topic')
  const contact = makeNode('10000000-0000-4000-8000-000000000002', 'contact')
  await graphFixture(page, [root, contact], [], { [root.id]: [1e9, 1e9], [contact.id]: [1e9, -1e9] })
  let reads = 0, available = false
  const writes = []
  await page.route('**/api/memory/graph/state/read', route => {
    reads++
    return route.fulfill({ json: { format_version: 99, revision: 8,
      preferences: { incompatible: true }, positions: {} } })
  })
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    return route.fulfill(available ? { json: { format_version: 1, revision: body.expected_revision + 1,
      preferences: body.preferences, positions: body.positions } } : { status: 503, json: { detail: 'Temporarily unavailable' } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(page.getByText('2 node(s)', { exact: true })).toBeVisible()
  const warning = page.getByText('Positions or display preferences could not be restored or saved.', { exact: true })
  await expect(warning).toBeVisible()
  expect(writes[0].reset_layout).toBe(true)
  expect(writes[0].expected_revision).toBe(8)
  expect(Object.values(writes[0].positions).every(point => Math.abs(point.x) < 1e9 && Math.abs(point.y) < 1e9)).toBe(true)
  await page.getByRole('button', { name: 'Hide “Contact” nodes and their relationships', exact: true }).click()
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(async () => Number((await snapshot(page)).graph3dZoom)).toBeGreaterThan(1)
  const before = (await snapshot(page)).graph3dCamera
  available = true
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(warning).toHaveCount(0)
  expect((await snapshot(page)).graph3dCamera).toBe(before)
  expect(reads).toBe(1)
  expect(writes.at(-1).preferences.hidden_entity_kinds).toEqual(['contact'])
  await expect(page.getByRole('button', { name: 'Show “Contact” nodes and their relationships', exact: true })).toBeVisible()
})

for (const width of [1440, 390]) test(`3D resets saved positions and keeps filters on reopening at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const root = makeNode('10000000-0000-4000-8000-000000000004', 'topic')
  const contact = makeNode('10000000-0000-4000-8000-000000000005', 'contact')
  const positions = { [root.id]: [1e9, 1e9], [contact.id]: [1e9, -1e9] }
  await graphFixture(page, [root, contact], [], positions)
  let saved = { format_version: 1, revision: 8,
    preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null }, positions: {} }
  const writes = []
  await page.route('**/api/memory/graph/state/read', route => route.fulfill({ json: saved }))
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    if (body.reset_layout) for (const id of Object.keys(positions)) delete positions[id]
    for (const [id, point] of Object.entries(body.positions)) positions[id] = [point.x, point.y]
    saved = { format_version: 1, revision: body.expected_revision + 1,
      preferences: { ...(body.reset_layout ? {} : saved.preferences), ...body.preferences }, positions: body.positions }
    return route.fulfill({ json: saved })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  const reset = page.getByRole('button', { name: 'Reset node positions', exact: true })
  await expect(reset).toBeEnabled()
  await page.getByRole('button', { name: 'Hide “Contact” nodes and their relationships', exact: true }).click()
  await expect(reset).toBeEnabled()
  await reset.focus()
  await page.keyboard.press('Enter')
  await expect.poll(() => writes.some(body => body.reset_layout)).toBe(true)
  await expect(page.getByRole('button', { name: 'Show “Contact” nodes and their relationships', exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dZoom)).toBeCloseTo(1)
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('reset-positions.png') })
  expect(saved.preferences.hidden_entity_kinds).toEqual(['contact'])
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(reset).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Show “Contact” nodes and their relationships', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Show “Contact” nodes and their relationships', exact: true }).click()
  await expect.poll(() => Object.keys(positions).length).toBe(2)
  expect(Object.values(positions).every(point => point.every(value => Math.abs(value) < 1e9))).toBe(true)
  const rebuilt = structuredClone(positions)
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(reset).toBeEnabled()
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(2)
  expect(positions).toEqual(rebuilt)
  expect(writes.filter(body => body.reset_layout)).toHaveLength(1)
})

test('3D resumes saving automatically after restoration becomes available', async ({ page }) => {
  await graphFixture(page, [makeNode('10000000-0000-4000-8000-000000000003', 'topic')])
  let reads = 0
  const writes = []
  await page.route('**/api/memory/graph/state/read', route => {
    reads++
    return route.fulfill(reads === 1 ? { status: 503, json: { detail: 'Temporarily unavailable' } }
      : { json: { format_version: 1, revision: 8,
        preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null }, positions: {} } })
  })
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    return route.fulfill({ json: { format_version: 1, revision: body.expected_revision + 1,
      preferences: body.preferences, positions: body.positions } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(page.getByText('1 node(s)', { exact: true })).toBeVisible()
  await expect.poll(() => writes.length).toBeGreaterThan(0)
  expect(reads).toBe(2)
  expect(writes[0].expected_revision).toBe(8)
  await expect(page.getByText('Positions or display preferences could not be restored or saved.', { exact: true })).toHaveCount(0)
})

// Measure the colored folder artwork in the actual WebGL screenshot, rather
// than a computed size or an attribute that might never reach the GPU.
async function folderWidths(page) {
  const png = await scene(page).locator('canvas').screenshot()
  return page.evaluate(async base64 => {
    const image = new Image()
    image.src = `data:image/png;base64,${base64}`
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = image.width; canvas.height = image.height
    const context = canvas.getContext('2d')
    context.drawImage(image, 0, 0)
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
    const ranges = [[Infinity, -Infinity], [Infinity, -Infinity]]
    for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
      const offset = (y * canvas.width + x) * 4
      const colors = [data[offset], data[offset + 1], data[offset + 2]]
      if (Math.max(...colors) - Math.min(...colors) < 60) continue
      const range = ranges[Number(x >= canvas.width / 2)]
      range[0] = Math.min(range[0], x); range[1] = Math.max(range[1], x)
    }
    return ranges.map(([min, max]) => Math.max(0, max - min + 1))
  }, png.toString('base64'))
}

for (const width of [1440, 390]) test(`3D distant directories visibly represent 84 unloaded children at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const full = { ...makeNode('full', 'directory', 84), children_count: 84, resource_uri: 'synthetic://full' }
  const empty = { ...makeNode('empty', 'directory'), children_count: 0, resource_uri: 'synthetic://empty' }
  await graphFixture(page, [full, empty], [], { full: [-300, 0], empty: [300, 0] })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(page.getByText('84 hidden item(s)', { exact: true })).toBeVisible()
  await expect(scene(page).getByText('Synthetic full', { exact: true })).toBeVisible()
  await expect.poll(async () => {
    const sizes = await folderWidths(page)
    return sizes[0] / sizes[1]
  }).toBeGreaterThan(3)
  const sizes = await folderWidths(page)
  expect(sizes[1]).toBeGreaterThan(0)
  expect(sizes[0] / sizes[1]).toBeLessThanOrEqual(4.3) // Raster rounding of the small base icon.
  await testInfo.attach('folder-artwork-widths', { body: JSON.stringify(sizes), contentType: 'application/json' })
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath(`hidden-directory-${width}.png`) })
})

test('3D keeps every hidden-population caption visible beyond the ordinary label budget and through collisions', async ({ page }) => {
  const nodes = Array.from({ length: 16 }, (_, index) => ({
    ...makeNode(`directory-${index}`, 'directory', 84), children_count: 84, resource_uri: `synthetic://directory-${index}`,
  }))
  await graphFixture(page, nodes, [], Object.fromEntries(nodes.map((node, index) => [node.id, [index % 4, Math.floor(index / 4)]])))
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(page.getByText('1344 hidden item(s)', { exact: true })).toBeVisible()
  for (const node of nodes) await expect(scene(page).getByText(node.title, { exact: true })).toBeVisible()
})

test('memory 3d benchmark preserves 10000 nodes and 20000 links', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const renderer = '3d', count = 10000
  const nodes = Array.from({ length: count }, (_, i) => makeNode(`node-${i}`, 'memory', 4))
  const edges = nodes.flatMap((node, i) => [1, 37].map(step => ({ id: `edge-${i}-${step}`,
    source_item_id: node.id, target_item_id: nodes[(i + step) % count].id,
    relation_type: 'related_to', confidence: 1, suggested: false })))
  const positions = Object.fromEntries(nodes.map((node, i) => [node.id,
    [(i % 100 - 49.5) * 70, (Math.floor(i / 100) - 24.5) * 70]]))
  const requests = await graphFixture(page, nodes, edges, positions)
  const start = Date.now()
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0, { timeout: 40_000 })
  // The first page is already usable while the remaining pages load.
  await expect(page.getByText(`${count} node(s)`, { exact: true })).toBeVisible({ timeout: 40_000 })
  await expect(page.getByText(`${edges.length} relation(s)`, { exact: true })).toBeVisible()
  if (renderer === '3d') await expect.poll(async () => Number((await snapshot(page)).graph3dRepresented)).toBe(count)
  const openedMs = Date.now() - start
  expect(requests).toHaveLength(count / 500)
  expect(requests.every(request => request.edge_limit === (renderer === '3d' ? 10000 : 2500))).toBe(true)
  expect(requests.every(request => request.order_by === (renderer === '3d' ? 'hierarchy' : 'activity'))).toBe(true)
  const timings = await page.evaluate(async () => {
    const samples = []
    const buttons = [...document.querySelectorAll('button')]
    const zoomIn = buttons.find(button => button.getAttribute('aria-label') === 'Zoom in')
    const zoomOut = buttons.find(button => button.getAttribute('aria-label') === 'Zoom out')
    for (let i = 0; i < 40; i++) {
      const before = performance.now()
      ;(i % 20 < 10 ? zoomIn : zoomOut).click()
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      samples.push(performance.now() - before)
    }
    return samples.sort((a, b) => a - b)
  })
  const evidence = { renderer, nodes: count, links: edges.length, openedMs,
    actionMedianMs: timings[Math.floor(timings.length / 2)], actionP95Ms: timings[Math.floor(timings.length * 0.95)],
    ...(renderer === '3d' ? await snapshot(page) : {}) }
  await testInfo.attach('renderer-measurements', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' })
  if (renderer === '3d') {
    expect(Number(evidence.graph3dDrawCalls)).toBeLessThanOrEqual(2)
    expect(Number(evidence.graph3dSourceLinks)).toBe(edges.length)
    await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
    await expect.poll(async () => Number((await snapshot(page)).graph3dRepresented)).toBe(count)
    expect(Number((await snapshot(page)).graph3dNodes)).toBeLessThan(1000)
    for (let i = 0; i < 15; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
    await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBeLessThan(500)
    await scene(page).focus()
    await page.keyboard.press('Home')
    await expect.poll(async () => Number((await snapshot(page)).graph3dRepresented)).toBe(count)
    await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('3d-spatial-overview.png') })
    const label = scene(page).getByText(/^Group of \d+ items$/).first()
    await expect(label).toBeVisible()
    const box = await label.boundingBox()
    await page.mouse.click(box.x + box.width / 2, box.y - 12)
    await expect.poll(async () => Number((await snapshot(page)).graph3dZoom)).toBeGreaterThan(1.8)
    await scene(page).focus()
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('Enter')
    await expect.poll(() => page.evaluate(() => window.testApp.events.some(event => event.name === 'open' && event.value.startsWith('node-')))).toBe(true)
    await page.keyboard.press('Home')
  }
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath(`${renderer}-${count}.png`) })
})

for (const width of [1440, 390]) test(`3D background refresh preserves navigation and applies paged changes at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await page.clock.install()
  await page.addInitScript(() => {
    const NativeWorker = window.Worker
    window.graphPlacementRuns = 0
    window.Worker = class extends NativeWorker {
      constructor(url, options) {
        super(url, options)
        if (String(url).includes('graph3d.worker')) window.graphPlacementRuns++
      }
    }
  })
  const anchor = makeNode('anchor', 'topic'), removed = makeNode('removed', 'topic'), added = makeNode('added', 'topic')
  let requests = 0, release, mode = 'initial'
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/graph/roots', async route => {
    requests++
    const body = route.request().postDataJSON()
    if (mode === 'initial') return route.fulfill({ json: { nodes: [anchor, removed], edges: [], has_more: false } })
    if (mode === 'delay') { mode = 'changed'; await pending }
    if (mode === 'error') return route.fulfill({ status: 503, json: { detail: 'Synthetic background failure' } })
    if (mode === 'denied') return route.fulfill({ status: 403, json: { detail: 'Synthetic lost management access' } })
    const nodes = body.cursor ? [added] : [{ ...anchor,
      title: mode === 'title' ? 'Synthetic second title' : 'Synthetic renamed anchor' }]
    return route.fulfill({ json: { nodes, edges: [], has_more: !body.cursor,
      next_cursor: body.cursor ? null : { id: anchor.id, activity_at: timestamp, role_rank: 3 } } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(2)
  mode = 'delay'
  const before = requests
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect.poll(() => requests).toBeGreaterThan(before)
  await expect(page.getByText('2 node(s)', { exact: true })).toBeVisible()
  await expect(scene(page)).not.toHaveClass(/memory-graph__chart--loading/)
  const anchorBox = await scene(page).getByText('Synthetic anchor', { exact: true }).boundingBox()
  await page.mouse.move(anchorBox.x + anchorBox.width / 2, anchorBox.y - 12)
  await page.mouse.wheel(0, -80)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const navigated = (await snapshot(page)).graph3dCamera
  release()
  await expect(scene(page).getByText('Synthetic renamed anchor', { exact: true })).toBeVisible()
  await expect(scene(page).getByText('Synthetic removed', { exact: true })).toHaveCount(0)
  await expect(page.getByText('2 node(s)', { exact: true })).toBeVisible()
  expect((await snapshot(page)).graph3dCamera).toBe(navigated)
  const placements = await page.evaluate(() => window.graphPlacementRuns)
  mode = 'title'
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect(scene(page).getByText('Synthetic second title', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.graphPlacementRuns)).toBe(placements)
  expect((await snapshot(page)).graph3dCamera).toBe(navigated)
  const beforePoll = requests
  await page.clock.runFor(30_001)
  await expect.poll(() => requests).toBeGreaterThan(beforePoll)
  await expect(page.getByRole('button', { name: 'Reload graph', exact: true })).toBeEnabled()
  expect(await page.evaluate(() => window.graphPlacementRuns)).toBe(placements)
  await page.getByRole('switch', { name: 'Auto refresh', exact: true }).click()
  const pausedRequests = requests
  await page.clock.runFor(30_001)
  expect(requests).toBe(pausedRequests)
  const after = requests
  mode = 'error'
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect.poll(() => requests).toBeGreaterThan(after)
  await expect(page.getByRole('button', { name: 'Reload graph', exact: true })).toBeEnabled()
  await expect(page.getByText('2 node(s)', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
  mode = 'denied'
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect(page.getByText('0 node(s)', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
})

for (const width of [1440, 390]) test(`3D shows known directories immediately, loads files on approach and restores visited branches at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const root = { ...makeNode('scheme', 'directory', 2), resource_uri: 'synthetic://', children_count: 2 }
  const child = { ...makeNode('branch', 'directory', 2), resource_uri: 'synthetic://branch', children_count: 501 }
  const sibling = { ...makeNode('sibling', 'directory', 1), resource_uri: 'synthetic://sibling', children_count: 0 }
  const details = Array.from({ length: 501 }, (_, index) => makeNode(`detail-${index}`, 'file', 1))
  const edge = (source, target) => ({ id: `${source.id}-${target.id}`, source_item_id: source.id,
    target_item_id: target.id, relation_type: 'parent_of', confidence: 1, suggested: false })
  let preferences = {}, revision = 0
  let failNextPage = width === 1440
  const expansions = [], rootRequests = []
  await jsonRoute(page, '**/api/file-share/items/*/resources?*', [])
  await page.route('**/api/memory/graph/state/read', route => route.fulfill({ json: {
    format_version: 1, revision, preferences, positions: {},
  } }))
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    preferences = { ...preferences, ...body.preferences }
    return route.fulfill({ json: { format_version: 1, revision: ++revision, preferences, positions: body.positions } })
  })
  await page.route('**/api/memory/graph/roots', route => {
    const body = route.request().postDataJSON()
    rootRequests.push(body)
    expect(body.defer_resource_children).toBe(false)
    expect(body.defer_resource_files).toBe(true)
    return route.fulfill({ json: { nodes: [root, child, sibling],
      edges: [edge(root, child), edge(root, sibling)],
      positions: { scheme: [0, 0] }, has_more: false } })
  })
  await page.route('**/api/memory/graph/expand', route => {
    const body = route.request().postDataJSON()
    expansions.push(body)
    expect(body.children_only).toBe(true)
    expect(body.limit).toBe(500)
    const offset = body.cursor ? details.findIndex(node => node.id === body.cursor.id) + 1 : 0
    if (offset && failNextPage) {
      failNextPage = false
      return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary file-page failure' } })
    }
    const children = body.item_id === root.id ? [child, sibling] : details.slice(offset, offset + body.limit)
    const parent = body.item_id === root.id ? root : child
    const hasMore = body.item_id === child.id && offset + children.length < details.length
    return route.fulfill({ json: { nodes: [parent, ...children], edges: children.map(node => edge(parent, node)),
      has_more: hasMore, next_cursor: hasMore ? { id: children.at(-1).id, activity_at: timestamp, role_rank: 1 } : null } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(3)
  await expect(page.getByText('501 hidden item(s)', { exact: true })).toBeVisible()
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(expansions).toHaveLength(0)
  await expect(page.getByText('3 node(s)', { exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dSourceLinks)).toBe(2)
  const label = scene(page).getByText(/^Synthetic branch\b/)
  await expect(label).toBeVisible()
  for (let i = 0; i < 12 && !expansions.some(body => body.item_id === child.id); i++) {
    const box = await label.boundingBox()
    if (!box) break
    await page.mouse.move(box.x + box.width / 2, box.y - 12)
    await page.mouse.wheel(0, -120)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  }
  await expect.poll(() => expansions.some(body => body.item_id === child.id)).toBe(true)
  if (width === 1440) {
    await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
    await expect(page.getByText('503 node(s)', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
  }
  await expect(page.getByText('504 node(s)', { exact: true })).toBeVisible()
  expect(expansions.filter(body => body.item_id === child.id)).toHaveLength(width === 1440 ? 4 : 2)
  await expect.poll(() => preferences.resource_branches?.branch).toBe(2)
  const countBefore = expansions.length
  await page.evaluate(() => window.testApp.unmount())
  await page.evaluate(args => window.testApp.mount(args), { component: 'app/memory/components/MemoryGraph.vue', props })
  await expect(page.getByText('504 node(s)', { exact: true })).toBeVisible()
  expect(expansions.slice(countBefore).map(body => body.item_id)).toEqual([child.id, child.id])
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await expect(page.getByText('504 node(s)', { exact: true })).toBeVisible()
  await expect(page.getByText('501 hidden item(s)', { exact: true })).toBeVisible()
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath(`hierarchy-${width}.png`) })
  const camera = (await snapshot(page)).graph3dCamera
  details.shift()
  details.push(makeNode('new-file-a', 'file', 1), makeNode('new-file-b', 'file', 1))
  child.children_count = details.length
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect(page.getByText('505 node(s)', { exact: true })).toBeVisible()
  await expect(page.getByText('502 hidden item(s)', { exact: true })).toBeVisible()
  expect((await snapshot(page)).graph3dCamera).toBe(camera)
})

test('3D opens the complete known directory map of large shares before any zoom', async ({ page }, testInfo) => {
  const roots = Array.from({ length: 4 }, (_, index) => ({ ...makeNode(`share-${index}`, 'directory', 249),
    resource_uri: `synthetic-${index}://`, children_count: 249 }))
  const directories = roots.flatMap((root, share) => Array.from({ length: 249 }, (_, index) => ({
    ...makeNode(`directory-${share}-${index}`, 'directory', 251),
    resource_uri: `${root.resource_uri}directory-${index}/`, children_count: 250,
  })))
  const edges = directories.map((node, index) => ({ id: `parent-${node.id}`,
    source_item_id: roots[Math.floor(index / 249)].id, target_item_id: node.id,
    relation_type: 'parent_of', confidence: 1, suggested: false }))
  let expansions = 0
  await page.route('**/api/memory/graph/expand', route => {
    expansions++
    return route.fulfill({ json: { nodes: [], edges: [], has_more: false } })
  })
  const requests = await graphFixture(page, [...roots, ...directories], edges)
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(page.getByText('1000 node(s)', { exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dRepresented)).toBe(1000)
  expect(requests).toHaveLength(2)
  expect(requests.every(request => request.defer_resource_files && !request.defer_resource_children)).toBe(true)
  expect(expansions).toBe(0)
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('large-shares-overview.png') })
  const group = scene(page).getByText(/^Group of \d+ items$/).first()
  await expect(group).toBeVisible()
  const bounds = await scene(page).boundingBox()
  const groupPoint = await group.evaluate(element => ({ x: Number(element.dataset.nodeX), y: Number(element.dataset.nodeY) }))
  await page.mouse.click(bounds.x + groupPoint.x, bounds.y + groupPoint.y)
  await expect.poll(async () => Number((await snapshot(page)).graph3dZoom)).toBeGreaterThan(1.8)
  const directoryPoint = await scene(page).locator('[data-node-id^="directory-"]').evaluateAll(elements => {
    const bounds = elements[0]?.parentElement.getBoundingClientRect()
    return elements.map(element => ({ x: Number(element.dataset.nodeX), y: Number(element.dataset.nodeY) }))
      .filter(point => bounds && point.x >= 0 && point.x < bounds.width && point.y >= 0 && point.y < bounds.height)
      .sort((a, b) => Math.hypot(a.x - bounds.width / 2, a.y - bounds.height / 2)
        - Math.hypot(b.x - bounds.width / 2, b.y - bounds.height / 2))[0]
  })
  expect(directoryPoint).toBeDefined()
  await page.mouse.click(bounds.x + directoryPoint.x, bounds.y + directoryPoint.y)
  await expect.poll(() => page.evaluate(() => window.testApp.events.some(event =>
    event.name === 'open' && event.value.startsWith('directory-')))).toBe(true)
})

test('3D cancels directory expansion on agent change and never merges its late response', async ({ page }) => {
  const root = { ...makeNode('old-scheme', 'directory', 1), resource_uri: 'synthetic://', children_count: 1 }
  const replacement = makeNode('new-entry', 'topic')
  let requested = false, release
  const pending = new Promise(resolve => { release = resolve })
  const aborted = []
  page.on('requestfailed', request => {
    if (request.url().endsWith('/memory/graph/expand')) aborted.push(request.failure()?.errorText)
  })
  await page.route('**/api/memory/graph/roots', route => route.fulfill({ json: {
    nodes: [route.request().postDataJSON().agent_id === 7 ? root : replacement], edges: [], has_more: false,
  } }))
  await page.route('**/api/memory/graph/expand', async route => {
    requested = true
    await pending
    await route.fulfill({ json: { nodes: [root, makeNode('late-child')], edges: [], has_more: false } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  for (let i = 0; i < 4; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(() => requested).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  await expect(scene(page).getByText('Synthetic new-entry', { exact: true })).toBeVisible()
  await expect.poll(() => aborted.length).toBe(1)
  release()
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(page.getByText('1 node(s)', { exact: true })).toBeVisible()
  await expect(scene(page).getByText('Synthetic old-scheme', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
})

for (const width of [1440, 390]) test(`3D renders early pages, preserves navigation and recovers a later page error at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  let releasePage, secondRequested = false, failPage = false
  const waitPage = new Promise(resolve => { releasePage = resolve })
  const anchor = makeNode('large-anchor', 'memory', 2), leaf = makeNode('early-leaf', 'memory', 1)
  const last = makeNode('last-leaf', 'memory', 1)
  const edge = target => ({ id: `edge-${target.id}`, source_item_id: anchor.id, target_item_id: target.id,
    relation_type: 'related_to', confidence: 1, suggested: false })
  await page.route('**/api/memory/graph/roots', async route => {
    const body = route.request().postDataJSON()
    expect(body.order_by).toBe('hierarchy')
    expect(body.edge_limit).toBe(10000)
    if (body.cursor) {
      secondRequested = true
      await waitPage
      if (failPage) return route.fulfill({ status: 503, json: { detail: 'Synthetic late-page failure' } })
      return route.fulfill({ json: { nodes: [last], edges: [edge(last)], has_more: false } })
    }
    return route.fulfill({ json: { nodes: [anchor, leaf], edges: [edge(leaf)],
      has_more: true, next_cursor: { id: leaf.id, activity_at: timestamp, role_rank: 3 } } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(() => secondRequested).toBe(true)
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(2)
  await expect(scene(page)).not.toHaveClass(/memory-graph__chart--loading/)
  const initial = (await snapshot(page)).graph3dCamera
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(async () => (await snapshot(page)).graph3dCamera).not.toBe(initial)
  const navigated = (await snapshot(page)).graph3dCamera
  releasePage()
  await expect(page.getByText('3 node(s)', { exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dSourceLinks)).toBe(2)
  expect((await snapshot(page)).graph3dCamera).toBe(navigated)
  failPage = true
  await page.getByRole('button', { name: 'Reload graph', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  await expect(page.getByText('2 node(s)', { exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dSourceLinks)).toBe(1)
  await expect(scene(page)).not.toHaveClass(/memory-graph__chart--loading/)
  failPage = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('3 node(s)', { exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dSourceLinks)).toBe(2)
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
})

for (const width of [1440, 390]) for (const count of [8, 30]) test(`3D ${count}-leaf groups, filters, keyboard selection and renderer recovery preserve content at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  if (count === 8) await page.addInitScript(() => {
    // Keep the actual placement worker, but delay delivery past the HTTP load
    // and a resize. An empty placeholder camera must never become a preference.
    const NativeWorker = window.Worker
    window.Worker = class extends NativeWorker {
      constructor(url, options) { super(url, options); this.delayedGraph = String(url).includes('graph3d.worker') }
      set onmessage(handler) {
        super.onmessage = this.delayedGraph && handler ? event => setTimeout(() => handler.call(this, event), 500) : handler
      }
      get onmessage() { return super.onmessage }
    }
  })
  const nodes = [makeNode('anchor', 'memory', count), ...Array.from({ length: count }, (_, i) => makeNode(`leaf-${i}`, 'memory', 1)),
    makeNode('person', 'contact')]
  const edges = nodes.slice(1, count + 1).map(node => ({ id: `edge-${node.id}`, source_item_id: 'anchor',
    target_item_id: node.id, relation_type: 'related_to', confidence: 1, suggested: false }))
  const requests = await graphFixture(page, nodes, edges, {}, count === 8)
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  if (count === 8) {
    // A genuinely empty scene is ready before the first authorized page. Its
    // placeholder framing must not become the framing of the arriving graph.
    await expect.poll(async () => Number((await snapshot(page)).graph3dFrames)).toBeGreaterThan(0)
    requests.release()
    await expect(page.getByText(`${count + 2} node(s)`, { exact: true })).toBeVisible()
    await page.setViewportSize({ width, height: 990 })
    await page.setViewportSize({ width, height: 1000 })
  }
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(2)
  await expect(page.getByText(`${count} grouped node(s)`, { exact: true })).toBeVisible()
  await scene(page).focus()
  for (let i = 0; i < 2 && !(await scene(page).getAttribute('aria-description'))?.startsWith('Synthetic anchor'); i++) {
    await page.keyboard.press('ArrowRight')
  }
  await page.keyboard.press('Enter')
  await expect(page.getByText(`${count} grouped node(s)`, { exact: true })).toHaveCount(0)
  await scene(page).focus()
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.events.some(event => event.name === 'open'))).toBe(true)
  await page.getByRole('button', { name: 'Hide “Contact” nodes and their relationships', exact: true }).click()
  await expect(page.getByText(`${count + 1} node(s)`, { exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dZoom)).toBeCloseTo(1)
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('3d-filtered.png') })
  await page.evaluate(() => {
    const canvas = document.querySelector('.memory-graph__chart--3d canvas')
    canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }))
  })
  await expect(page.getByText('The 3D graph is unavailable. Check WebGL support in your browser and try again.')).toBeVisible()
  await expect(scene(page).locator('canvas')).toHaveCount(0)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(scene(page).locator('canvas')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show “Contact” nodes and their relationships', exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBeGreaterThan(0)
})

test('3D clears the old scene on agent changes, no selection and unmounting', async ({ page }) => {
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes: [makeNode('first')], edges: [], has_more: false })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes: [], edges: [], has_more: false })
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  await expect(page.getByText('No memory matches the active filters.')).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(0)
  await page.evaluate(() => window.testApp.setProps({ agentId: null }))
  await expect(scene(page)).toHaveCount(0)
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes: [makeNode('second')], edges: [], has_more: false })
  await page.evaluate(() => window.testApp.setProps({ agentId: 7 }))
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  await page.evaluate(() => window.testApp.unmount())
  await expect(scene(page)).toHaveCount(0)
})

test('3D left dragging orbits the pointed node and never opens it, even after returning to the starting point', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  const nodes = [makeNode('pivot-a'), makeNode('pivot-b'), makeNode('pivot-c')]
  await graphFixture(page, nodes, [], { 'pivot-a': [-80, 0], 'pivot-b': [400, 0], 'pivot-c': [-400, 0] })
  const cameras = []
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    if (body.preferences.camera_3d) cameras.push(body.preferences.camera_3d)
    return route.fulfill({ json: { format_version: 1, revision: body.expected_revision + 1,
      preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null, ...body.preferences }, positions: body.positions } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(3)
  await expect.poll(() => cameras.length).toBeGreaterThan(0)
  const fitting = cameras.at(-1)
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(() => cameras.at(-1).target[2]).not.toBe(fitting.target[2])
  const beforeOrbit = cameras.at(-1).position
  const beforeTarget = cameras.at(-1).target
  const pointed = async () => {
    const label = scene(page).getByText('Synthetic pivot-a', { exact: true })
    await expect(label).toBeVisible()
    const box = await label.boundingBox()
    return { x: box.x + box.width / 2, y: box.y - 12 }
  }
  const opens = () => page.evaluate(() => window.testApp.events.filter(event => event.name === 'open').length)
  const start = await pointed()
  await page.mouse.move(start.x, start.y)
  await page.mouse.down()
  await page.mouse.move(start.x + 1, start.y)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const firstMove = await pointed()
  expect(Math.hypot(firstMove.x - start.x, firstMove.y - start.y)).toBeLessThan(2)
  await page.mouse.move(start.x + 100, start.y + 30, { steps: 8 })
  await expect.poll(() => Math.hypot(...cameras.at(-1).position.map((value, i) => value - beforeOrbit[i]))).toBeGreaterThan(0.1)
  const duringMove = await pointed()
  expect(Math.hypot(duringMove.x - start.x, duringMove.y - start.y)).toBeLessThan(2)
  await page.mouse.move(start.x, start.y, { steps: 8 })
  await page.mouse.up()
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(await opens()).toBe(0)
  await expect.poll(() => Math.hypot(...cameras.at(-1).position.map((value, i) => value - beforeOrbit[i]))).toBeLessThan(0.001)
  for (let i = 0; i < 3; i++) expect(cameras.at(-1).target[i]).toBeCloseTo(beforeTarget[i], 5)
  const next = await pointed()
  await page.mouse.click(next.x, next.y, { button: 'right' })
  await page.mouse.move(next.x, next.y)
  await page.mouse.down()
  await page.mouse.move(next.x + 1, next.y)
  await page.mouse.move(next.x, next.y)
  await page.mouse.up()
  expect(await opens()).toBe(0)
  const click = await pointed()
  await scene(page).locator('canvas').evaluate(canvas => canvas.addEventListener('pointerdown', event => {
    canvas.dispatchEvent(new PointerEvent('pointercancel', { pointerId: event.pointerId, bubbles: true }))
  }, { once: true }))
  await page.mouse.click(click.x, click.y)
  expect(await opens()).toBe(0)
  await page.mouse.click(click.x, click.y)
  await expect.poll(opens).toBe(1)
  expect(await page.evaluate(() => window.testApp.events.find(event => event.name === 'open').value)).toBe('pivot-a')
})

for (const width of [1440, 390]) test(`3D dragging empty space pans at pointer speed and preserves orientation at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await graphFixture(page, [makeNode('pan-a', 'topic'), makeNode('pan-b', 'topic'), makeNode('pan-c', 'topic')], [],
    { 'pan-a': [-80, 0], 'pan-b': [400, 0], 'pan-c': [-400, 0] })
  const cameras = []
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    if (body.preferences.camera_3d) cameras.push(body.preferences.camera_3d)
    return route.fulfill({ json: { format_version: 1, revision: body.expected_revision + 1,
      preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null, ...body.preferences }, positions: body.positions } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(3)
  await expect.poll(() => cameras.length).toBeGreaterThan(0)
  const label = scene(page).getByText('Synthetic pan-a', { exact: true })
  const point = async () => {
    await expect(label).toBeVisible()
    const box = await label.boundingBox()
    return { x: box.x + box.width / 2, y: box.y - 12 }
  }
  const frame = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  // Keep pointer translation proportional in overview, rotated and zoomed views.
  for (const { rotateFirst, zoomFirst } of [
    { rotateFirst: false, zoomFirst: false }, { rotateFirst: true, zoomFirst: false },
    { rotateFirst: false, zoomFirst: true }, { rotateFirst: true, zoomFirst: true },
  ]) {
    await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
    await frame()
    if (rotateFirst) {
      const beforeRotate = JSON.parse((await snapshot(page)).graph3dCamera)
      const pivot = await point()
      await page.mouse.move(pivot.x, pivot.y)
      await page.mouse.down()
      await page.mouse.move(pivot.x + 45, pivot.y + 25, { steps: 5 })
      await page.mouse.up()
      await frame()
      await expect.poll(async () => Math.hypot(...JSON.parse((await snapshot(page)).graph3dCamera).position
        .map((value, i) => value - beforeRotate.position[i]))).toBeGreaterThan(0.1)
    }
    if (zoomFirst) {
      const pivot = await point()
      await page.mouse.move(pivot.x, pivot.y)
      for (let step = 0; step < 10; step++) {
        await page.mouse.wheel(0, -120)
        await frame()
      }
      await expect.poll(async () => Number((await snapshot(page)).graph3dZoom)).toBeGreaterThan(3)
    }
    const initial = await point()
    const before = JSON.parse((await snapshot(page)).graph3dCamera)
    const dx = zoomFirst ? 30 : 100, dy = zoomFirst ? 20 : 80
    const button = zoomFirst && rotateFirst ? 'right' : 'left'
    const start = { x: initial.x - dx, y: initial.y - dy }
    await page.mouse.move(start.x, start.y)
    await page.mouse.down({ button })
    await page.mouse.move(initial.x, initial.y, { steps: 5 })
    await frame()
    const moved = await point()
    expect(moved.x - initial.x).toBeCloseTo(dx, 0)
    expect(moved.y - initial.y).toBeCloseTo(dy, 0)
    const after = JSON.parse((await snapshot(page)).graph3dCamera)
    expect(Math.hypot(...after.position.map((value, i) => value - before.position[i]))).toBeGreaterThan(0.1)
    for (let i = 0; i < 3; i++) expect(after.position[i] - after.target[i]).toBeCloseTo(before.position[i] - before.target[i], 5)
    // Return to the original camera pose without turning this gesture into a click.
    await page.mouse.move(start.x, start.y, { steps: 5 })
    await page.mouse.up({ button })
    await frame()
    const returned = await point()
    expect(Math.hypot(returned.x - initial.x, returned.y - initial.y)).toBeLessThan(2)
    await page.mouse.move(initial.x, initial.y)
    await frame()
    const released = await point()
    expect(Math.hypot(released.x - returned.x, released.y - returned.y)).toBeLessThan(2)
  }
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'open'))).toEqual([])
})

test('3D wheel navigation follows the pointer without recentering or rotating the view', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await graphFixture(page, [makeNode('cursor-a', 'file'), makeNode('cursor-b', 'topic'), makeNode('cursor-c', 'topic')], [],
    { 'cursor-a': [-240, 100], 'cursor-b': [400, 0], 'cursor-c': [-400, 0] })
  const png = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 128; canvas.height = 80
    return canvas.toDataURL('image/png').split(',')[1]
  }), 'base64')
  await jsonRoute(page, '**/api/file-share/items/cursor-a/resources?*', [{ id: 'image', name: 'Synthetic cursor.png',
    media_type: 'image/png', size_bytes: png.length, uri: 'file://synthetic/cursor.png' }])
  await page.route('**/api/file-share/items/cursor-a/resources/image/thumbnail?*', route =>
    route.fulfill({ contentType: 'image/png', body: png }))
  const cameras = []
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    if (body.preferences.camera_3d) cameras.push(body.preferences.camera_3d)
    return route.fulfill({ json: { format_version: 1, revision: body.expected_revision + 1,
      preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null, ...body.preferences }, positions: body.positions } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(3)
  await expect.poll(() => cameras.length).toBeGreaterThan(0)
  const fitting = structuredClone(cameras.at(-1))
  // Approach the off-center file along its ray. A fixed number of central
  // zoom steps could remove it from the tighter, aspect-aware overview.
  await scene(page).focus()
  for (let i = 0; i < 3 && await scene(page).getAttribute('aria-description') !== 'Synthetic cursor-a'; i++) await page.keyboard.press('ArrowRight')
  const caption = scene(page).getByText('Synthetic cursor-a', { exact: true })
  await expect(caption).toBeVisible()
  const glyph = await caption.boundingBox()
  await page.mouse.move(glyph.x + glyph.width / 2, glyph.y - 12)
  for (let i = 0; i < 12 && (i === 0 || !await scene(page).locator('img').isVisible()); i++) {
    await page.mouse.wheel(0, -120)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  }
  await expect.poll(() => cameras.at(-1).target[2]).not.toBe(fitting.target[2])
  const image = scene(page).locator('img')
  const point = async () => {
    await expect(image).toBeVisible()
    const box = await image.boundingBox()
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  }
  const initial = await point()
  await page.mouse.move(initial.x, initial.y)
  const wheel = async delta => {
    const previous = cameras.length
    await page.mouse.wheel(0, delta)
    await expect.poll(() => cameras.length).toBeGreaterThan(previous)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  }
  for (let i = 0; i < 4; i++) {
    await wheel(-120)
    const moved = await point()
    expect(Math.hypot(moved.x - initial.x, moved.y - initial.y)).toBeLessThan(2)
  }
  await expect.poll(() => Math.hypot(...cameras.at(-1).position.map((value, i) => value - fitting.position[i]))).toBeGreaterThan(0.1)
  const zoomed = cameras.at(-1)
  for (let i = 0; i < 3; i++) expect(zoomed.position[i] - zoomed.target[i]).toBeCloseTo(fitting.position[i] - fitting.target[i], 5)
  await wheel(120)
  const backed = await point()
  expect(Math.hypot(backed.x - initial.x, backed.y - initial.y)).toBeLessThan(2)
  // Switching the pointer to empty space must still cause lateral camera travel.
  const box = await scene(page).boundingBox()
  const beforeEmpty = structuredClone(cameras.at(-1))
  await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.15)
  await wheel(-120)
  await expect.poll(() => cameras.at(-1).position[0]).toBeGreaterThan(beforeEmpty.position[0])
  for (let i = 0; i < 35; i++) await page.mouse.wheel(0, 120)
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(3)
  await expect.poll(() => Math.hypot(...cameras.at(-1).target.map((value, i) => value - fitting.target[i]))).toBeLessThan(0.001)
  // Captions at the frame boundary may be omitted by collision/clipping rules;
  // camera stability is the durable maximum-retreat guarantee.
  const boundary = structuredClone(cameras.at(-1))
  for (let i = 0; i < 4; i++) {
    await page.mouse.wheel(0, 120)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  }
  expect(cameras.at(-1)).toEqual(boundary)
  expect(Number((await snapshot(page)).graph3dZoom)).toBeCloseTo(1)
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'open'))).toEqual([])
})

test('3D hides the whole relation when either endpoint is behind the camera and restores it on fit', async ({ page }) => {
  const front = makeNode('foreground', 'topic', 1), back = makeNode('background', 'memory', 1)
  // This direction leaves independent role placement: both nodes share their
  // lateral coordinates, with the entry point ahead of the detail.
  await graphFixture(page, [front, back], [{ id: 'depth-link', source_item_id: back.id,
    target_item_id: front.id, relation_type: 'related_to', confidence: 1, suggested: false }],
  { foreground: [0, 0], background: [0, 0] })
  await jsonRoute(page, '**/api/memory/graph/state/read', { format_version: 1, revision: 0,
    preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null,
      camera_3d: { position: [0, 0, -200], target: [0, 0, -400], layout_version: 2 } }, positions: {} })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  expect(Number((await snapshot(page)).graph3dSourceLinks)).toBe(1)
  await expect(page.getByText('1 hidden item(s)', { exact: true })).toBeVisible()
  expect(Number((await snapshot(page)).graph3dLinks)).toBe(0)
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(2)
  await expect(page.getByText('1 hidden item(s)', { exact: true })).toHaveCount(0)
  await expect.poll(async () => Number((await snapshot(page)).graph3dLinks)).toBe(1)
})

test('3D camera navigation passes a node and continues through empty space with buttons, wheel and pinch', async ({ page }) => {
  await graphFixture(page, [makeNode('fly-through')])
  const cameras = []
  await page.route('**/api/memory/graph/state', route => {
    const body = route.request().postDataJSON()
    if (body.preferences.camera_3d) cameras.push(body.preferences.camera_3d)
    return route.fulfill({ json: { format_version: 1, revision: body.expected_revision + 1,
      preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null, ...body.preferences }, positions: body.positions } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  await expect.poll(() => cameras.length).toBeGreaterThan(0)
  const initial = cameras.at(-1)
  const direction = initial.target.map((value, i) => value - initial.position[i])
  const progress = camera => camera.position.reduce((total, value, i) => total + (value - initial.target[i]) * direction[i], 0)
  for (let i = 0; i < 80; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(() => progress(cameras.at(-1))).toBeGreaterThan(0)
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(0)
  const passed = progress(cameras.at(-1))
  const box = await scene(page).boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 6; i++) await page.mouse.wheel(0, -120)
  await expect.poll(() => progress(cameras.at(-1))).toBeGreaterThan(passed)
  const wheeled = progress(cameras.at(-1))
  const touch = await page.context().newCDPSession(page)
  const x = Math.round(box.x + box.width / 2), y = Math.round(box.y + box.height / 2)
  await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 21 }, { x: x + 50, y, id: 22 }] })
  await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y, id: 21 }, { x: x + 100, y, id: 22 }] })
  await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await touch.detach()
  await expect.poll(() => progress(cameras.at(-1))).toBeGreaterThan(wheeled)
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'open'))).toEqual([])
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
})

test('3D delays authorized previews, preserves native pixels and opens the image before navigating past it', async ({ page }, testInfo) => {
  const node = makeNode('picture', 'file')
  const png = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 320; canvas.height = 200
    const context = canvas.getContext('2d')
    context.fillStyle = '#087FF5'; context.fillRect(0, 0, 320, 200)
    return canvas.toDataURL('image/png').split(',')[1]
  }), 'base64')
  await graphFixture(page, [node])
  await jsonRoute(page, '**/api/file-share/items/picture/resources?*', [{ id: 'image', name: 'Synthetic.png',
    media_type: 'image/png', size_bytes: png.length, uri: 'file://synthetic/image.png' }])
  let reads = 0
  await page.route('**/api/file-share/items/picture/resources/image/thumbnail?*', route => {
    reads++
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  expect(reads).toBe(0)
  const image = scene(page).locator('img')
  await expect(image).toHaveCount(0)
  for (let i = 0; i < 18; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect(image).toHaveJSProperty('naturalWidth', 320)
  await expect.poll(async () => Math.round((await image.boundingBox()).width)).toBe(320)
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(async () => Math.round((await image.boundingBox()).width)).toBe(320)
  expect(Math.round((await image.boundingBox()).height)).toBe(200)
  expect(reads).toBe(1)
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('native-thumbnail-deep-zoom.png') })
  const box = await image.boundingBox()
  await page.mouse.click(box.x + 20, box.y + 20)
  await expect.poll(() => page.evaluate(() => window.testApp.events.some(event => event.name === 'open' && event.value === 'picture'))).toBe(true)
  await scene(page).focus()
  await page.keyboard.press('Home')
  await expect(image).toHaveCount(0)
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  await page.clock.install()
  await page.clock.runFor(1000)
  const frames = (await snapshot(page)).graph3dFrames
  await page.clock.runFor(2000)
  expect((await snapshot(page)).graph3dFrames).toBe(frames)
})
