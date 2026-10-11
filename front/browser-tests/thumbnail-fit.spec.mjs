import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const props = { agentId: 7, query: '', topicItemId: null, contactItemId: null }
const node = (id, kind = 'file') => ({ id, title: `Synthetic ${id}`, node_kind: kind, entity_kind: kind,
  owner_agent_id: 7, visibility: 'private', source_managed: true, access_count: 0, last_accessed_at: null,
  created_at: '2026-09-01T12:00:00Z', updated_at: '2026-09-01T12:00:00Z', activity_at: '2026-09-01T12:00:00Z',
  has_relations: false, relation_count: 0 })
const chart = page => page.locator('.memory-graph__chart--3d')
const images = page => chart(page).locator('img')
async function png(page, width, height) {
  return Buffer.from(await page.evaluate(({ width, height }) => {
    const canvas = document.createElement('canvas')
    canvas.width = width; canvas.height = height
    const context = canvas.getContext('2d')
    context.fillStyle = '#FFFFFF'; context.fillRect(0, 0, width, height)
    context.fillStyle = '#0866ED'; context.fillRect(width / 4, height / 4, width / 2, height / 2)
    return canvas.toDataURL('image/webp', 1).split(',')[1]
  }, { width, height }), 'base64')
}

for (const cores of [2, 16]) test(`an 84-file directory loads every visible thumbnail with ${cores} reported desktop cores and a capped memory estimate`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.addInitScript(cores => {
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => cores })
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 2 })
  }, cores)
  const bytes = await png(page, 320, 200)
  const files = Array.from({ length: 84 }, (_, index) => node(`synthetic-image-${index}`))
  const directory = node('synthetic-directory', 'directory')
  const bounds = [node('synthetic-top', 'memory'), node('synthetic-bottom', 'memory')]
  await jsonRoute(page, '**/api/memory/graph/roots', {
    nodes: [directory, ...files, ...bounds], edges: [], has_more: false, next_cursor: null, edges_truncated: false,
    positions: Object.fromEntries([[directory.id, [0, -280]], [bounds[0].id, [-1400, -900]], [bounds[1].id, [1400, 900]],
      ...files.map((file, i) => [file.id, [(i % 12 - 5.5) * 80, (Math.floor(i / 12) - 3) * 80]])]),
  })
  // Exercise the thumbnail budget independently of navigation by restoring a
  // near view with the entire synthetic directory inside the viewport.
  await jsonRoute(page, '**/api/memory/graph/state/read', {
    format_version: 1, revision: 0, positions: {}, preferences: {
      hidden_entity_kinds: [], expanded_branches: [], camera: null,
      camera_3d: { layout_version: 2, position: [0, 0, 0], target: [0, 0, -960] },
    },
  })
  let reads = 0
  await page.route('**/api/file-share/items/synthetic-image-*/resources?*', route => route.fulfill({ json: [{
    id: 'image', name: 'synthetic.png', media_type: 'image/png', size_bytes: bytes.length, uri: 'file://synthetic/image.png',
  }] }))
  await page.route('**/api/file-share/items/synthetic-image-*/resources/image/thumbnail?*', route => {
    reads++
    return route.fulfill({ contentType: 'image/webp', body: bytes })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(images(page)).toHaveCount(84)
  await expect.poll(() => images(page).evaluateAll(elements => elements.every(image => image.naturalWidth === 320))).toBe(true)
  expect(reads).toBe(84)
  const rectangles = await images(page).evaluateAll(elements => elements.map(image => {
    const rect = image.getBoundingClientRect()
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  }))
  for (let i = 0; i < rectangles.length; i++) for (const other of rectangles.slice(i + 1)) {
    const image = rectangles[i]
    expect(image.x + image.width <= other.x + 0.01 || other.x + other.width <= image.x + 0.01
      || image.y + image.height <= other.y + 0.01 || other.y + other.height <= image.y + 0.01).toBe(true)
  }
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('84-file-thumbnails.png') })
  const pan = async direction => {
    const rect = await chart(page).boundingBox()
    await page.mouse.move(rect.x + 10, rect.y + 10)
    await page.mouse.down()
    await page.mouse.move(rect.x + 10 + direction * rect.width * 2, rect.y + 10, { steps: 5 })
    await page.mouse.up()
  }
  await pan(1)
  await expect(images(page)).toHaveCount(0)
  await pan(-1)
  await expect(images(page)).toHaveCount(84)
  expect(reads).toBe(84)
})

for (const width of [1920, 390]) for (const [shape, sourceWidth, sourceHeight] of [
  ['landscape', 320, 160], ['portrait', 160, 320], ['square', 160, 160],
  ['panorama', 320, 40], ['document', 226, 320],
]) test(`3D ${shape} thumbnails preserve decoded proportions through zoom and reuse at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  const bytes = await png(page, sourceWidth, sourceHeight)
  const item = node(shape, shape === 'document' ? 'document' : 'file')
  await jsonRoute(page, '**/api/memory/graph/roots', {
    nodes: [item], edges: [], has_more: false, next_cursor: null, edges_truncated: false,
  })
  let reads = 0
  if (shape === 'document') {
    await jsonRoute(page, '**/api/memory/documents/document?*', {
      item: { id: 'document', title: 'Synthetic document', document_type: 'html', revision: 1, lock_version: 1,
        payload: { text: '<h1>Synthetic document</h1>' } }, agent_id: 7,
    })
    await page.route('**/api/memory/documents/document/thumbnail?*', route => {
      reads++
      return route.fulfill({ contentType: 'image/webp', body: bytes })
    })
  } else {
    await jsonRoute(page, `**/api/file-share/items/${shape}/resources?*`, [{
      id: 'image', name: `${shape}.png`, media_type: 'image/png', size_bytes: bytes.length, uri: `file://synthetic/${shape}.png`,
    }])
    await page.route(`**/api/file-share/items/${shape}/resources/image/thumbnail?*`, route => {
      reads++
      return route.fulfill({ contentType: 'image/webp', body: bytes })
    })
  }
  await mount(page, 'app/memory/components/MemoryGraph.vue', { props })
  await expect(chart(page)).toHaveAttribute('data-graph3d-nodes', '1')
  const approach = async () => {
    for (let i = 0; i < 18; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  }
  const assertProportions = async () => {
    await expect(images(page)).toHaveCount(1)
    const image = images(page).first()
    await expect(image).toHaveJSProperty('naturalWidth', sourceWidth)
    await expect(image).toHaveJSProperty('naturalHeight', sourceHeight)
    const rect = await image.boundingBox()
    expect(rect.width / rect.height).toBeCloseTo(sourceWidth / sourceHeight, 2)
    expect(rect.width).toBeLessThanOrEqual(sourceWidth + 0.01)
    expect(rect.height).toBeLessThanOrEqual(sourceHeight + 0.01)
    const actual = await image.evaluate(async image => [...new Uint8Array(await (await fetch(image.src)).arrayBuffer())])
    expect(Buffer.from(actual)).toEqual(bytes)
  }
  await approach()
  await assertProportions()
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await assertProportions()
  await page.getByRole('button', { name: 'Fit graph to viewport', exact: true }).click()
  await expect(images(page)).toHaveCount(0)
  await approach()
  await assertProportions()
  const kind = shape === 'document' ? 'Document' : 'File'
  await page.getByRole('button', { name: `Hide “${kind}” nodes and their relationships`, exact: true }).click()
  await expect(images(page)).toHaveCount(0)
  await page.getByRole('button', { name: `Show “${kind}” nodes and their relationships`, exact: true }).click()
  await approach()
  await assertProportions()
  expect(reads).toBe(1)
})
