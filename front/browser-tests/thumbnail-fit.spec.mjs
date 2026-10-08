import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const cores of [2, 16]) test(`an 84-file directory loads every visible thumbnail with ${cores} reported desktop cores and a capped memory estimate`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.addInitScript(cores => {
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => cores })
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 2 })
  }, cores)
  const png = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 320; canvas.height = 200
    const context = canvas.getContext('2d')
    context.fillStyle = '#0866ED'; context.fillRect(0, 0, 320, 200)
    return canvas.toDataURL('image/webp', 1).split(',')[1]
  }), 'base64')
  const timestamp = '2026-09-01T12:00:00Z'
  const files = Array.from({ length: 84 }, (_, index) => ({
    id: `synthetic-image-${index}`, title: `Synthetic image ${index}`, node_kind: 'file', entity_kind: 'file',
    owner_agent_id: 7, visibility: 'private', source_managed: true, access_count: 0,
    last_accessed_at: null, created_at: timestamp, updated_at: timestamp, activity_at: timestamp,
    has_relations: true, relation_count: 3,
  }))
  const directory = { ...files[0], id: 'synthetic-directory', title: 'Synthetic directory',
    node_kind: 'directory', entity_kind: 'directory', relation_count: files.length }
  const edges = files.flatMap((file, index) => [
    { id: `location-${index}`, source_item_id: directory.id, target_item_id: file.id,
      relation_type: 'related_to', confidence: 1, suggested: false },
    { id: `neighbor-${index}`, source_item_id: file.id, target_item_id: files[(index + 1) % files.length].id,
      relation_type: 'related_to', confidence: 1, suggested: false },
  ])
  await jsonRoute(page, '**/api/memory/graph/roots', {
    nodes: [directory, ...files], edges, has_more: false, next_cursor: null, edges_truncated: false,
  })
  let thumbnailReads = 0
  await page.route('**/api/file-share/items/synthetic-image-*/resources?*', route => route.fulfill({ json: [{
    id: 'image', name: 'synthetic.png', media_type: 'image/png', size_bytes: png.length, uri: 'file://synthetic/image.png',
  }] }))
  await page.route('**/api/file-share/items/synthetic-image-*/resources/image/thumbnail?*', route => {
    thumbnailReads++
    return route.fulfill({ contentType: 'image/webp', body: png })
  })
  await mount(page, 'app/memory/components/MemoryGraph.vue', {
    props: { agentId: 7, query: '', topicItemId: null, contactItemId: null },
  })
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  const rendererUrl = await page.evaluate(() => performance.getEntriesByType('resource').map(entry => entry.name)
    .find(name => /\/echarts(?:\/core|_core)\.js/.test(name)))
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await page.evaluate(async url => {
    const chart = (await import(url)).getInstanceByDom(document.querySelector('.memory-graph__chart'))
    const data = chart.getModel().getSeries()[0].getData()
    const points = Array.from({ length: data.count() }, (_, index) =>
      chart.convertToPixel({ seriesId: 'memory-graph' }, data.getItemLayout(index)))
    const xs = points.map(point => point[0]), ys = points.map(point => point[1])
    chart.dispatchAction({ type: 'graphRoam', seriesId: 'memory-graph',
      dx: chart.getWidth() / 2 - (Math.min(...xs) + Math.max(...xs)) / 2,
      dy: chart.getHeight() / 2 - (Math.min(...ys) + Math.max(...ys)) / 2 })
  }, rendererUrl)
  const snapshot = () => page.evaluate(async url => {
    const chart = (await import(url)).getInstanceByDom(document.querySelector('.memory-graph__chart'))
    const data = chart.getModel().getSeries()[0].getData()
    const files = Array.from({ length: data.count() }, (_, index) => {
      if (!data.getId(index).startsWith('synthetic-image-')) return null
      const point = chart.convertToPixel({ seriesId: 'memory-graph' }, data.getItemLayout(index))
      const image = data.getItemGraphicEl(index)?.childAt(0)
      return { id: data.getId(index), visible: point[0] >= 0 && point[0] <= chart.getWidth()
        && point[1] >= 0 && point[1] <= chart.getHeight(),
        thumbnail: image?.type === 'image' && Boolean(image.__image?.naturalWidth) }
    }).filter(Boolean)
    return { files, zoom: chart.getOption().series[0].zoom }
  }, rendererUrl)
  await expect.poll(async () => (await snapshot()).files.filter(file => file.thumbnail).length).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
  await expect.poll(async () => (await snapshot()).files.filter(file => file.visible).length).toBe(84)
  await expect.poll(async () => (await snapshot()).files.filter(file => file.visible && !file.thumbnail).length).toBe(0)
  const reads = thumbnailReads
  expect(reads).toBe(84)
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('84-file-thumbnails.png') })
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
  await expect.poll(async () => (await snapshot()).files.filter(file => file.visible && !file.thumbnail).length).toBe(0)
  expect(thumbnailReads).toBe(reads)
  await page.clock.install()
  const pan = direction => page.evaluate(async ({ direction, url }) => {
    const chart = (await import(url)).getInstanceByDom(document.querySelector('.memory-graph__chart'))
    chart.dispatchAction({ type: 'graphRoam', seriesId: 'memory-graph', dx: direction * chart.getWidth() * 2, dy: 0 })
  }, { direction, url: rendererUrl })
  await pan(1)
  await page.clock.runFor(500)
  expect((await snapshot()).files.filter(file => file.visible)).toHaveLength(0)
  expect((await snapshot()).files.filter(file => file.thumbnail)).toHaveLength(84)
  await pan(-1)
  await page.clock.runFor(500)
  expect((await snapshot()).files.filter(file => file.thumbnail)).toHaveLength(84)
  expect(thumbnailReads).toBe(reads)
})

for (const width of [1920, 390]) test(`graph thumbnails preserve decoded image proportions through zoom and reuse at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const shapes = [['landscape', 320, 160], ['portrait', 160, 320], ['square', 160, 160], ['panorama', 320, 40], ['document', 226, 320]]
  const images = await page.evaluate(shapes => shapes.map(([id, width, height]) => {
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    context.fillStyle = '#FFFFFF'
    context.fillRect(0, 0, width, height)
    context.fillStyle = '#0866ED'
    context.beginPath()
    context.arc(width / 2, height / 2, Math.min(width, height) / 3, 0, Math.PI * 2)
    context.fill()
    return { id, png: canvas.toDataURL('image/webp', 1).split(',')[1] }
  }), shapes)
  const timestamp = '2026-09-01T12:00:00Z'
  const nodes = shapes.map(([id]) => ({ id, title: `Synthetic ${id}`, node_kind: id === 'document' ? 'document' : 'file', entity_kind: id === 'document' ? 'document' : 'file',
    owner_agent_id: 7, visibility: 'private', source_managed: true, access_count: 0, last_accessed_at: null,
    created_at: timestamp, updated_at: timestamp, activity_at: timestamp, has_relations: true, relation_count: 3 }))
  const edges = nodes.flatMap((node, index) => nodes.slice(index + 1).map(other => ({
    id: `${node.id}-${other.id}`, source_item_id: node.id, target_item_id: other.id,
    relation_type: 'related_to', confidence: 1, suggested: false,
  })))
  for (const { id, png } of images) {
    if (id === 'document') {
      const document = {
        id, title: 'Synthetic document', document_type: 'html', revision: 1, lock_version: 1,
        payload: { text: '<h1>Synthetic document</h1><p>First page.</p>' },
      }
      await jsonRoute(page, '**/api/memory/documents/document?*', { item: document, agent_id: 7 })
      await jsonRoute(page, '**/api/memory/items/document?*', document)
      await page.route('**/api/memory/documents/document/thumbnail?*', route =>
        route.fulfill({ contentType: 'image/webp', body: Buffer.from(png, 'base64') }))
      continue
    }
    await jsonRoute(page, `**/api/file-share/items/${id}/resources?*`, [{
      id: 'image', name: `${id}.png`, media_type: 'image/png', size_bytes: 100, uri: `file://synthetic/${id}.png`,
    }])
    await page.route(`**/api/file-share/items/${id}/resources/image/thumbnail?*`, route =>
      route.fulfill({ contentType: 'image/webp', body: Buffer.from(png, 'base64') }))
  }
  await jsonRoute(page, '**/api/memory/graph/roots', { nodes, edges, has_more: false, next_cursor: null, edges_truncated: false })
  await mount(page, 'app/memory/components/MemoryGraph.vue', {
    props: { agentId: 7, query: '', topicItemId: null, contactItemId: null },
  })
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  const proportions = () => page.evaluate(async () => {
    const moduleUrl = performance.getEntriesByType('resource')
      .map(entry => entry.name).find(name => /\/echarts(?:\/core|_core)\.js/.test(name))
    if (!moduleUrl) return []
    const echarts = await import(moduleUrl)
    const chart = echarts.getInstanceByDom(document.querySelector('.memory-graph__chart'))
    const data = chart?.getModel().getSeries()[0]?.getData()
    if (!data) return []
    return Array.from({ length: data.count() }, (_, index) => {
      // Observe painted geometry, including image fitting and the renderer's transforms.
      const image = data.getItemGraphicEl(index)?.childAt(0)
      if (image?.type !== 'image' || !image.__image?.naturalWidth) return null
      const transform = image.getComputedTransform()
      const paintedWidth = image.getWidth() * Math.hypot(transform[0], transform[1])
      const paintedHeight = image.getHeight() * Math.hypot(transform[2], transform[3])
      return { id: data.getId(index), width: image.__image.naturalWidth, height: image.__image.naturalHeight,
        error: Math.abs(paintedWidth / paintedHeight
        - image.__image.naturalWidth / image.__image.naturalHeight) }
    }).filter(Boolean)
  })
  const panToNode = id => page.evaluate(async id => {
    const moduleUrl = performance.getEntriesByType('resource')
      .map(entry => entry.name).find(name => /\/echarts(?:\/core|_core)\.js/.test(name))
    const echarts = await import(moduleUrl)
    const chart = echarts.getInstanceByDom(document.querySelector('.memory-graph__chart'))
    const series = chart.getModel().getSeries()[0]
    const data = series.getData()
    const index = Array.from({ length: data.count() }, (_, index) => index).find(index => data.getId(index) === id)
    const point = chart.convertToPixel({ seriesId: series.id }, data.getItemLayout(index))
    chart.dispatchAction({ type: 'graphRoam', seriesId: series.id,
      dx: chart.getWidth() / 2 - point[0], dy: chart.getHeight() / 2 - point[1] })
  }, id)
  const assertProportions = async () => {
    // Zoom may move nodes outside the viewport, where thumbnails deliberately stay unloaded.
    for (const node of nodes) {
      await panToNode(node.id)
      await expect.poll(async () => (await proportions()).find(image => image.id === node.id)?.error).toBeLessThan(0.01)
      const [, sourceWidth, sourceHeight] = shapes.find(([id]) => id === node.id)
      const scale = Math.min(1, 320 / sourceWidth, 320 / sourceHeight)
      const decoded = (await proportions()).find(image => image.id === node.id)
      expect(decoded.width).toBe(Math.round(sourceWidth * scale))
      expect(decoded.height).toBe(Math.round(sourceHeight * scale))
      const rendered = await page.evaluate(async id => {
        const moduleUrl = performance.getEntriesByType('resource').map(entry => entry.name)
          .find(name => /\/echarts(?:\/core|_core)\.js/.test(name))
        const chart = (await import(moduleUrl)).getInstanceByDom(document.querySelector('.memory-graph__chart'))
        const data = chart.getModel().getSeries()[0].getData()
        const index = Array.from({ length: data.count() }, (_, index) => index).find(index => data.getId(index) === id)
        const source = data.getItemGraphicEl(index).childAt(0).__image.src
        const blob = await (await fetch(source)).blob()
        return { type: blob.type, bytes: [...new Uint8Array(await blob.arrayBuffer())] }
      }, node.id)
      expect(rendered.type).toBe('image/webp')
      expect(Buffer.from(rendered.bytes)).toEqual(Buffer.from(images.find(image => image.id === node.id).png, 'base64'))
    }
  }
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await assertProportions()
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('graph-thumbnail-proportions.png') })
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
  await expect.poll(proportions).toEqual([])
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await assertProportions()
  await page.getByRole('button', { name: 'Hide “File” nodes and their relationships', exact: true }).click()
  await page.getByRole('button', { name: 'Show “File” nodes and their relationships', exact: true }).click()
  await assertProportions()
})
