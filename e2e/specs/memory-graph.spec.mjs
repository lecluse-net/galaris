import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [1440, 390]) test(`exclusive memory branches remain accessible in 3D after zoom and reopening at ${width}px`, async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt =>
    prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  const errors = collectPageErrors(page)
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok(), await seeded.text()).toBeTruthy()
  const fixture = await seeded.json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const items = []
  for (let index = 0; index < 9; index++) {
    const response = await request.post('/api/memory/items', { headers, data: {
      owner_agent_id: fixture.agent_id, title: `Synthetic branch ${index}`,
      payload: { text: `Synthetic preserved content ${index}` },
    } })
    expect(response.ok(), await response.text()).toBeTruthy()
    items.push(await response.json())
  }
  for (const leaf of items.slice(1)) {
    const linked = await request.post(`/api/memory/links?actor_agent_id=${fixture.agent_id}`, { headers,
      data: { source_item_id: items[0].id, target_item_id: leaf.id, relation_type: 'related_to' } })
    expect(linked.ok(), await linked.text()).toBeTruthy()
  }
  await errors.settle()
  await page.goto(`/memory?agent=${fixture.agent_id}`)
  // Each full navigation restores the mobile drawer; dismiss it before page actions.
  if (width < 1024) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }))
  await page.getByRole('tab', { name: 'Graphe', exact: true }).click()
  const grouped = page.getByText('8 nœud(s) regroupé(s)', { exact: true })
  await expect(grouped).toBeVisible()
  await expect(page.getByText('8 élément(s) masqué(s)', { exact: true })).toBeVisible()
  await expect(page.locator('.memory-graph__chart--loading')).toHaveCount(0)
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('graph-overview.png') })
  await page.locator('.memory-graph__chart--3d').focus()
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Enter')
  await expect(grouped).toHaveCount(0)
  await page.locator('.memory-graph').screenshot({ path: testInfo.outputPath('graph-detail.png') })
  {
    const graph = page.locator('.memory-graph__chart--3d')
    // A bounded label layer can omit an unselected caption on a small viewport.
    // Select the intended canonical node before exercising its mouse gestures.
    // Its description/caption can now also report related hidden items.
    const anchorName = new RegExp(`^${items[0].title}(?: |$)`)
    await graph.focus()
    for (let index = 0; index < items.length; index++) {
      await page.keyboard.press('ArrowRight')
      if (anchorName.test(await graph.getAttribute('aria-description') ?? '')) break
    }
    await expect(graph).toHaveAttribute('aria-description', anchorName)
    const marker = graph.getByText(anchorName)
    await expect(marker).toBeVisible()
    const center = () => marker.evaluate(element => ({ x: Number(element.dataset.nodeX), y: Number(element.dataset.nodeY) }))
    const glyph = async () => {
      const rect = await graph.boundingBox()
      const point = await center()
      return { x: rect.x + point.x, y: rect.y + point.y }
    }
    const canvas = graph.locator('canvas')
    // Native locator actions dismiss optional onboarding and scroll the hit
    // point into view before starting the raw pointer gestures.
    await canvas.hover({ position: await center() })
    const { x, y } = await glyph()
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x + 45, y + 20, { steps: 6 })
    await page.mouse.move(x, y, { steps: 6 })
    await page.mouse.up()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const chart = await page.locator('.memory-graph__chart--3d').boundingBox()
    // Hidden mass can animate the caption's offset from the glyph. Observe
    // the rendered glyph center to verify panning follows the pointer.
    const beforePanCenter = await center()
    await page.mouse.move(chart.x + 15, chart.y + 15)
    await page.mouse.down()
    await page.mouse.move(chart.x + 45, chart.y + 35, { steps: 5 })
    await expect.poll(async () => (await center()).x - beforePanCenter.x).toBeCloseTo(30, 0)
    expect((await center()).y - beforePanCenter.y).toBeCloseTo(20, 0)
    await page.mouse.move(chart.x + 15, chart.y + 15, { steps: 5 })
    await page.mouse.up()
    await expect.poll(async () => (await center()).x).toBeCloseTo(beforePanCenter.x, 0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    // Aim at an off-center node after panning, rather than the chart's center.
    await page.mouse.move(chart.x + 15, chart.y + 15)
    await page.mouse.down()
    await page.mouse.move(chart.x + 75, chart.y + 15, { steps: 5 })
    await page.mouse.up()
    await expect.poll(async () => (await center()).x - beforePanCenter.x).toBeCloseTo(60, 0)
    const beforeWheel = await center()
    const wheelPoint = await glyph()
    await page.mouse.move(wheelPoint.x, wheelPoint.y)
    await page.mouse.wheel(0, -120)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect.poll(async () => (await center()).x).toBeCloseTo(beforeWheel.x, 0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await canvas.click({ position: await center() })
    await expect(page.getByRole('dialog').locator('[data-editor-surface]')).toContainText('Synthetic preserved content 0')
    await page.getByRole('dialog').getByRole('button', { name: 'Fermer', exact: true }).click()
  }
  await page.getByRole('button', { name: 'Ajuster le graphe à la fenêtre', exact: true }).click()
  await expect(grouped).toBeVisible()
  const context = { agent_id: fixture.agent_id, query: '' }
  const savedView = async () => {
    const response = await request.post('/api/memory/graph/state/read', { headers, data: context })
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const savedPositions = async () => {
    const response = await request.post('/api/memory/graph/roots', { headers,
      data: { ...context, include_saved_positions: true, limit: 500 } })
    expect(response.ok(), await response.text()).toBeTruthy()
    return (await response.json()).positions
  }
  await page.getByRole('button', { name: 'Masquer les nœuds « Contact » et leurs relations', exact: true }).click()
  await expect.poll(async () => (await savedView()).preferences.hidden_entity_kinds).toEqual(['contact'])
  await expect.poll(async () => Object.keys(await savedPositions()).length).toBeGreaterThanOrEqual(items.length)
  const positions = await savedPositions()
  expect((await savedView()).preferences).toMatchObject({ expanded_branches: [] })
  expect((await savedView()).preferences.camera_3d).toMatchObject({ position: expect.any(Array), target: expect.any(Array) })
  await page.goto(`/memory?agent=${fixture.agent_id}`)
  await page.getByRole('tab', { name: 'Graphe', exact: true }).click()
  await expect(grouped).toBeVisible()
  await expect(page.getByRole('button', { name: 'Afficher les nœuds « Contact » et leurs relations', exact: true })).toBeVisible()
  expect(await savedPositions()).toEqual(positions)
  await page.getByRole('button', { name: 'Afficher les nœuds « Contact » et leurs relations', exact: true }).click()
  await page.getByRole('tab', { name: 'Liste', exact: true }).click()
  await page.getByText(items[1].title, { exact: true }).first().click()
  await expect(page.getByRole('dialog').locator('[data-editor-surface]')).toContainText('Synthetic preserved content 1')
  const detail = page.getByRole('dialog')
  await expect(detail.getByText('Mémoire - Souvenir', { exact: true })).toBeVisible()
  await expect(detail.getByRole('status', { name: /^Dernier accès ou modification :/ })).toBeVisible()
  await expect(detail.getByRole('status', { name: /^Accès :/ })).toBeVisible()
  const checkMemories = page.getByRole('dialog').getByRole('button', { name: 'Vérifier les souvenirs', exact: true })
  await expect(checkMemories).toBeEnabled()
  const actionResponse = page.waitForResponse(response => response.url().includes(`/dream/memory/${items[1].id}/actions/findings`)
    && response.request().method() === 'POST')
  await checkMemories.click()
  const result = await actionResponse
  expect(result.ok(), await result.text()).toBeTruthy()
  expect((await result.json()).receipt_id).toBeTruthy()
  await expect(page.getByRole('dialog').locator('[data-editor-surface]')).toContainText('Synthetic preserved content 1')
  await expect(checkMemories).toBeEnabled()
  await page.getByRole('dialog').getByRole('tab', { name: 'Liens et relations', exact: true }).click()
  await expect(page.getByRole('dialog').getByText(items[0].title, { exact: true })).toBeVisible()
  await page.getByRole('dialog').screenshot({ path: testInfo.outputPath('memory-links.png'), animations: 'disabled' })
  await page.getByRole('dialog').getByRole('tab', { name: 'Mémoire', exact: true }).click()
  await expect(page.getByRole('dialog').locator('[data-editor-surface]')).toContainText('Synthetic preserved content 1')
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer', exact: true }).click()
  await page.getByRole('tab', { name: 'Graphe', exact: true }).click()
  await expect(grouped).toBeVisible()

  const documentResponse = await request.post('/api/memory/items', { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic thumbnail report', node_kind: 'document',
    media_type: 'text/html', payload: { text: '<h1>Synthetic report</h1><p>Preserved document content.</p>' },
  } })
  expect(documentResponse.ok(), await documentResponse.text()).toBeTruthy()
  const document = await documentResponse.json()
  const capturedThumbnail = page.waitForResponse(response => response.url().includes(`/documents/${document.id}/thumbnail`)
    && response.request().method() === 'POST' && response.status() === 200)
  await page.goto(`/memory?agent=${fixture.agent_id}`)
  const documentRow = page.locator(width >= 1024 ? '.memory-list-table tbody tr' : '.memory-mobile-card')
    .filter({ hasText: document.title })
  const thumbnail = documentRow.locator('img')
  await expect(thumbnail).toHaveJSProperty('naturalHeight', 320)
  const dimensions = await thumbnail.evaluate(image => ({ width: image.naturalWidth, height: image.naturalHeight }))
  expect(dimensions.width).toBeLessThanOrEqual(320)
  expect(dimensions.width / dimensions.height).toBeCloseTo(210 / 297, 2)
  expect((await capturedThumbnail).headers()['content-type']).toBe('image/webp')
  await thumbnail.click()
  const dialog = page.getByRole('dialog')
  const regenerate = dialog.getByRole('button', { name: 'Régénérer la miniature', exact: true })
  const receipts = []
  for (let index = 0; index < 2; index++) {
    await expect(regenerate).toBeEnabled()
    const response = page.waitForResponse(response => response.url().includes(`/dream/memory/${document.id}/actions/thumbnail`)
      && response.request().method() === 'POST')
    await regenerate.focus()
    await page.keyboard.press('Enter')
    const result = await response
    expect(result.ok(), await result.text()).toBeTruthy()
    const action = await result.json()
    expect(action.result_count).toBe(1)
    expect(result.request().postDataJSON().html).toContain('Preserved document content.')
    receipts.push(action.receipt_id)
    await expect(regenerate).toBeEnabled()
    await expect(dialog.locator('[data-editor-surface]')).toHaveText('')
  }
  expect(new Set(receipts).size).toBe(2)
  await dialog.evaluate(async element => {
    await Promise.all(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})))
  })
  await page.screenshot({ path: testInfo.outputPath('dream-document-thumbnail.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Ouvrir le document', exact: true }).click()
  await expect(page.getByRole('dialog').locator('.document-editor [data-editor-surface]')).toContainText('Preserved document content.')
  await errors.settle()
  expect(errors()).toEqual([])
})
