import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const timestamp = '2026-09-01T12:00:00Z'
const makeNode = (id, kind = 'memory', count = 0) => ({
  id, title: `Synthetic ${id}`, node_kind: kind, entity_kind: kind,
  owner_agent_id: 7, visibility: 'private', source_managed: false, access_count: 0,
  last_accessed_at: null, created_at: timestamp, updated_at: timestamp,
  activity_at: timestamp, has_relations: count > 0, relation_count: count,
})
const props = { agentId: 7, query: '', topicItemId: null, contactItemId: null, renderer: '3d' }
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

for (const renderer of ['2d', '3d']) test(`memory ${renderer} benchmark preserves ${renderer === '3d' ? 10000 : 5000} nodes and ${renderer === '3d' ? 20000 : 10000} links`, async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const count = renderer === '3d' ? 10000 : 5000
  const nodes = Array.from({ length: count }, (_, i) => makeNode(`node-${i}`, 'memory', 4))
  const edges = nodes.flatMap((node, i) => [1, 37].map(step => ({ id: `edge-${i}-${step}`,
    source_item_id: node.id, target_item_id: nodes[(i + step) % count].id,
    relation_type: 'related_to', confidence: 1, suggested: false })))
  const positions = Object.fromEntries(nodes.map((node, i) => [node.id,
    [(i % 100 - 49.5) * 70, (Math.floor(i / 100) - 24.5) * 70]]))
  const requests = await graphFixture(page, nodes, edges, positions)
  const start = Date.now()
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props: { ...props, renderer } })
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0, { timeout: 40_000 })
  await expect(page.getByText(`${count} node(s)`, { exact: true })).toBeVisible()
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

for (const width of [1440, 390]) test(`3D approaches directories to load children, restores visited branches and preserves the complete 2D fallback at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const root = { ...makeNode('scheme', 'directory', 2), resource_uri: 'synthetic://', children_count: 2 }
  const child = { ...makeNode('branch', 'directory', 2), resource_uri: 'synthetic://branch', children_count: 1 }
  const sibling = { ...makeNode('sibling', 'directory', 1), resource_uri: 'synthetic://sibling', children_count: 0 }
  const detail = makeNode('detail', 'memory', 1)
  const edge = (source, target) => ({ id: `${source.id}-${target.id}`, source_item_id: source.id,
    target_item_id: target.id, relation_type: 'parent_of', confidence: 1, suggested: false })
  let preferences = {}, revision = 0
  const expansions = [], rootRequests = []
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
    return route.fulfill({ json: { nodes: body.defer_resource_children ? [root] : [root, child, sibling, detail],
      edges: body.defer_resource_children ? [] : [edge(root, child), edge(root, sibling), edge(child, detail)],
      positions: { scheme: [0, 0] }, has_more: false } })
  })
  await page.route('**/api/memory/graph/expand', route => {
    const body = route.request().postDataJSON()
    expansions.push(body)
    expect(body.children_only).toBe(true)
    expect(body.limit).toBe(100)
    const children = body.item_id === root.id ? [child, sibling] : [detail]
    const parent = body.item_id === root.id ? root : child
    return route.fulfill({ json: { nodes: [parent, ...children], edges: children.map(node => edge(parent, node)), has_more: false } })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(1)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(expansions).toHaveLength(0)
  for (let i = 0; i < 4; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(() => expansions.some(body => body.item_id === root.id)).toBe(true)
  await expect(page.getByText('3 node(s)', { exact: true })).toBeVisible()
  await expect.poll(async () => Number((await snapshot(page)).graph3dSourceLinks)).toBe(2)
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(3)
  const label = scene(page).getByText('Synthetic branch', { exact: true })
  await expect(label).toBeVisible()
  for (let i = 0; i < 12 && !expansions.some(body => body.item_id === child.id); i++) {
    const box = await label.boundingBox()
    if (!box) break
    await page.mouse.move(box.x + box.width / 2, box.y - 12)
    await page.mouse.wheel(0, -120)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  }
  await expect.poll(() => expansions.some(body => body.item_id === child.id)).toBe(true)
  await expect(page.getByText('4 node(s)', { exact: true })).toBeVisible()
  await expect.poll(() => preferences.resource_branches?.branch).toBe(1)
  const countBefore = expansions.length
  await page.evaluate(() => window.testApp.unmount())
  await page.evaluate(args => window.testApp.mount(args), { component: 'app/memory/components/MemoryGraph.vue', props })
  await expect(page.getByText('4 node(s)', { exact: true })).toBeVisible()
  expect(expansions.slice(countBefore).map(body => body.item_id)).toEqual([root.id, child.id])
  await page.getByRole('button', { name: '2D view', exact: true }).click()
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  await expect(page.getByText('4 node(s)', { exact: true })).toBeVisible()
  expect(rootRequests.at(-1).defer_resource_children).toBe(false)
  expect(rootRequests.at(-1).edge_limit).toBe(2500)
  await page.getByRole('button', { name: '3D view', exact: true }).click()
  await expect(page.getByText('4 node(s)', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath(`hierarchy-${width}.png`) })
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

for (const width of [1440, 390]) for (const count of [8, 30]) test(`3D ${count}-leaf groups, filters, keyboard selection and 2D fallback preserve content at ${width}px`, async ({ page }, testInfo) => {
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
  await page.getByRole('button', { name: '2D view', exact: true }).click()
  await expect(page.locator('.memory-graph__chart:not(.memory-graph__chart--3d) canvas')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show “Contact” nodes and their relationships', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '3D view', exact: true }).click()
  await expect(scene(page).locator('canvas')).toBeVisible()
  await page.evaluate(() => {
    const canvas = document.querySelector('.memory-graph__chart--3d canvas')
    canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }))
  })
  await expect(page.getByText('3D is unavailable in this browser. The graph remains accessible in 2D.')).toBeVisible()
  await expect(page.locator('.memory-graph__chart:not(.memory-graph__chart--3d) canvas')).toBeVisible()
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

test('3D left dragging empty space pans and preserves orientation until release', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
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
  // Exercise panning directly from the fitted overview, then with a rotated view.
  for (const rotateFirst of [false, true]) {
    if (rotateFirst) {
      const beforeRotate = cameras.at(-1)
      const pivot = await point()
      await page.mouse.move(pivot.x, pivot.y)
      await page.mouse.down()
      await page.mouse.move(pivot.x + 45, pivot.y + 25, { steps: 5 })
      await page.mouse.up()
      await frame()
      await expect.poll(() => Math.hypot(...cameras.at(-1).position.map((value, i) => value - beforeRotate.position[i]))).toBeGreaterThan(0.1)
    }
    const initial = await point()
    const before = structuredClone(cameras.at(-1))
    const start = { x: initial.x - 100, y: initial.y - 80 }
    await page.mouse.move(start.x, start.y)
    await page.mouse.down()
    await page.mouse.move(initial.x, initial.y, { steps: 5 })
    await frame()
    const moved = await point()
    expect(moved.x - initial.x).toBeCloseTo(100, 0)
    expect(moved.y - initial.y).toBeCloseTo(80, 0)
    await expect.poll(() => Math.hypot(...cameras.at(-1).position.map((value, i) => value - before.position[i]))).toBeGreaterThan(0.1)
    const after = cameras.at(-1)
    for (let i = 0; i < 3; i++) expect(after.position[i] - after.target[i]).toBeCloseTo(before.position[i] - before.target[i], 5)
    // Return to the original camera pose without turning this gesture into a click.
    await page.mouse.move(start.x, start.y, { steps: 5 })
    await page.mouse.up()
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
  expect(Number((await snapshot(page)).graph3dLinks)).toBe(0)
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await expect.poll(async () => Number((await snapshot(page)).graph3dNodes)).toBe(2)
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
