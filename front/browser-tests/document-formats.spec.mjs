import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as fixture } from './data.mjs'

async function editorFixtures(page, item) {
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice' }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments*', [])
  await page.route(/\/api\/documents\/doc-a(?:\?|$)/, route => route.fulfill({ json: { item, agent_id: 7 } }))
}

for (const width of [1440, 390]) test(`an unavailable format preserves literal source and offers recovery (${width}px)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  const source = '<img src="https://unavailable.example.test/private" onerror="throw Error(1)">'
  const item = { ...fixture, document_format: 'missing.plugin', format_version: 2,
    media_type: 'application/x-example', payload: { text: source } }
  await editorFixtures(page, item)
  await page.route('**/api/documents/doc-a/source?*', route => route.fulfill({ contentType: 'application/x-example', body: source }))
  await mount(page, 'app/document/components/DocumentEditor.vue', { props: { documentId: item.id, agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
  await expect(page.getByText('The viewer or editor for this format is unavailable. Its source is preserved.')).toBeVisible()
  await expect(page.locator('pre.unavailable-format-source')).toHaveText(source)
  await expect(page.locator('pre.unavailable-format-source img')).toHaveCount(0)
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download source', exact: true }).click()
  expect((await downloaded).suggestedFilename()).toBe(item.title)
})

test('a contributed editor uses common saving, validation and reopening without a native format branch', async ({ page }) => {
  let item = { ...fixture, document_format: 'example.note', format_version: 1,
    media_type: 'application/x-example-note', payload: { text: 'note:First' } }
  const writes = []
  await editorFixtures(page, item)
  await page.route(/\/api\/documents\/doc-a(?:\?|$)/, async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON(); writes.push(body)
      item = { ...item, ...body, revision: item.revision + 1, lock_version: item.lock_version + 1 }
      return route.fulfill({ json: item })
    }
    return route.fulfill({ json: { item, agent_id: 7 } })
  })
  await mount(page, 'test-support/browser/DocumentFormatHarness.vue', { props: { documentId: item.id, agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
  const input = page.getByRole('textbox', { name: 'Content', exact: true })
  await expect(input).toHaveValue('note:First')
  await input.fill('invalid draft')
  await input.blur()
  await expect.poll(() => writes.length).toBe(0)
  await input.fill('note:Second')
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].payload.text).toBe('note:Second')
  await page.evaluate(() => window.testApp.mount({ component: 'test-support/browser/DocumentFormatHarness.vue', props: { documentId: 'doc-a', agentId: 7 } }))
  await expect(input).toHaveValue('note:Second')
})

test('format catalogue distinguishes declared support and qualification and recovers after an error', async ({ page }, testInfo) => {
  let calls = 0
  await page.route('**/api/documents/formats', route => {
    calls++
    if (calls === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic failure' } })
    return route.fulfill({ json: [{ code: 'example.partial', provider: 'example', version: 1, contract_version: 1,
      storage_kind: 'text', media_type: 'application/x-example', icon: 'account_tree', qualification: 'not_run',
      capability_complete: false, import_extensions: [], capabilities: { editor: 'unavailable', preview: 'fallback', embed: 'fallback', thumbnail: 'fallback', pdf: 'fallback', native_export: 'native', import: 'unavailable' } }] })
  })
  await mount(page, 'app/document/components/DocumentFormatsDialog.vue', { props: { modelValue: true }, privileges: ['DOCUMENT_ACCESS'] })
  await expect(page.getByRole('alert')).toContainText('Unable to load document formats.')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('cell', { name: /example.partial/ })).toBeVisible()
  await expect(page.getByText('Declared capabilities are not certification.', { exact: false })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('document-formats.png'), animations: 'disabled' })
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('binary editors use the host revision boundary and retain bytes after a failed save', async ({ page }) => {
  let content = 'Synthetic binary source', fail = true
  let item = { ...fixture, document_format: 'example.binary', format_version: 1, content_type: 'binary',
    media_type: 'application/x-example-binary', payload: { base64: Buffer.from(content).toString('base64') } }
  await editorFixtures(page, item)
  const writes = []
  await page.route('**/api/documents/doc-a/source?*', route => route.fulfill({ contentType: item.media_type, body: content }))
  await page.route(/\/api\/documents\/doc-a(?:\?|$)/, route => {
    if (route.request().method() === 'PATCH') {
      const update = route.request().postDataJSON(); writes.push(update)
      if (fail) return route.fulfill({ status: 409, json: { detail: 'Synthetic conflict' } })
      content = Buffer.from(update.payload.base64, 'base64').toString()
      item = { ...item, revision: item.revision + 1, lock_version: item.lock_version + 1, payload: update.payload }
      return route.fulfill({ json: item })
    }
    return route.fulfill({ json: { item, agent_id: 7 } })
  })
  await mount(page, 'test-support/browser/DocumentFormatHarness.vue', { props: { documentId: item.id, agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
  const input = page.getByRole('textbox', { name: 'Synthetic binary content', exact: true })
  await expect(input).toHaveValue(content)
  await input.fill('Synthetic edited bytes')
  await page.getByRole('button', { name: 'Save synthetic binary', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('draft retained')
  await expect(input).toHaveValue('Synthetic edited bytes')
  expect(writes[0].expected_revision).toBe(fixture.revision)
  fail = false
  await page.getByRole('button', { name: 'Save synthetic binary', exact: true }).click()
  await expect.poll(() => content).toBe('Synthetic edited bytes')
  await expect(input).toHaveValue('Synthetic edited bytes')
  let exported = ''
  await page.route('**/api/documents/doc-a/export-pdf', route => {
    exported = route.request().postDataJSON().html
    return route.fulfill({ contentType: 'application/pdf', body: '%PDF-Synthetic snapshot' })
  })
  await page.getByRole('button', { name: 'Export PDF', exact: true }).click()
  await expect.poll(() => exported).toBe('<pre>Synthetic edited bytes</pre>')
})

test('a contributed file reader previews an attachment without importing a document', async ({ page }) => {
  let reads = 0
  await page.route('**/api/synthetic-viewer/source', route => { reads++; return route.fulfill({ contentType: 'application/x-example-note', body: 'Synthetic contributed viewer' }) })
  await mount(page, 'test-support/browser/ResourceViewerHarness.vue')
  expect(reads).toBe(0)
  await page.getByRole('button', { name: 'Open preview of synthetic.note', exact: true }).click()
  await expect(page.locator('pre')).toHaveText('Synthetic contributed viewer')
  expect(reads).toBe(1)
})

for (const archive of [false, true]) test(`Sample drawing autosaves PNG bytes and keeps a failed draft (${archive ? 'signed module' : 'checkout'})`, async ({ page }, testInfo) => {
  let png = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 320
    canvas.height = 200
    return canvas.toDataURL('image/png').split(',')[1]
  }), 'base64')
  const format = archive ? 'sample.drawing-bundle' : 'sample.drawing'
  const moduleUrl = `/api/plugins/assets/${'a'.repeat(64)}/${format}.mjs`
  let item = { ...fixture, document_format: format, format_version: 1, content_type: 'binary',
    media_type: 'image/png', payload: { base64: png.toString('base64') } }
  await editorFixtures(page, item)
  await page.route('**/api/documents/formats', route => route.fulfill({ json: [{
    code: format, provider: format, version: 1, contract_version: 1,
    media_type: 'image/png', storage_kind: 'file', icon: 'brush', qualification: 'not_run',
    capabilities: { editor: 'native', preview: 'native', embed: 'fallback', thumbnail: 'fallback', pdf: 'native', native_export: 'native', import: 'native' },
    capability_complete: true, import_extensions: ['.png'],
    ...(archive ? { plugin_editor: { module_url: moduleUrl, label: { en: 'Drawing (ZIP)', fr: 'Dessin (ZIP)' } } } : {}),
  }] }))
  if (archive) await page.route(url => url.pathname === moduleUrl, async route => route.fulfill({
    response: await route.fetch({ url: new URL('/test-support/drawing-module.mjs', route.request().url()).href }),
  }))
  await page.route('**/api/documents/doc-a/source?*', route => route.fulfill({ contentType: 'image/png', body: png }))
  const writes = []
  await page.route(/\/api\/documents\/doc-a(?:\?|$)/, async route => {
    if (route.request().method() !== 'PATCH') return route.fulfill({ json: { item, agent_id: 7 } })
    const update = route.request().postDataJSON()
    writes.push(update)
    if (await route.request().headerValue('x-editorial-profile-version') !== '1') {
      return route.fulfill({ status: 409, json: { detail: 'Editorial HTML profile 1 is required.' } })
    }
    if (writes.length === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable' } })
    png = Buffer.from(update.payload.base64, 'base64')
    item = { ...item, revision: item.revision + 1, lock_version: item.lock_version + 1, payload: update.payload }
    return route.fulfill({ json: item })
  })
  await mount(page, 'test-support/browser/DrawingSampleHarness.vue', { props: { documentId: item.id, agentId: 7, archive }, privileges: ['DOCUMENT_EDIT'] })
  const canvas = page.getByLabel('Drawing canvas', { exact: true })
  await expect(canvas).toBeVisible()
  const toolbar = page.getByRole('toolbar', { name: 'Drawing (Sample)', exact: true })
  const brush = toolbar.getByRole('button', { name: 'Brush', exact: true })
  const eraser = toolbar.getByRole('button', { name: 'Eraser', exact: true })
  await expect(brush).toHaveAttribute('aria-pressed', 'true')
  await brush.press('ArrowRight')
  await expect(eraser).toBeFocused()
  await eraser.press('Space')
  await expect(eraser).toHaveAttribute('aria-pressed', 'true')
  await brush.click()
  await expect(toolbar.getByLabel('Paint color')).toBeEnabled()
  await expect(toolbar.getByRole('slider', { name: 'Brush size' })).toBeEnabled()
  await canvas.click()
  const pixel = () => canvas.evaluate(element => [...element.getContext('2d').getImageData(160, 100, 1, 1).data])
  expect(await pixel()).toEqual([8, 127, 245, 255])
  await expect(page.getByRole('alert')).toContainText('Your draft is still open')
  expect(await pixel()).toEqual([8, 127, 245, 255])
  await page.getByRole('button', { name: 'Save drawing', exact: true }).click()
  await expect(page.getByText('Drawing saved', { exact: true })).toBeVisible()
  expect(writes.map(write => write.expected_revision)).toEqual([fixture.revision, fixture.revision])
  expect(writes[1].payload.base64).toBe(writes[0].payload.base64)
  await canvas.click({ position: { x: 80, y: 70 } })
  await expect.poll(() => writes.length).toBe(3)
  await expect(page.getByText('Drawing saved', { exact: true })).toBeVisible()
  expect(writes[2].expected_revision).toBe(fixture.revision + 1)
  const focus = await page.evaluate(() => window.testApp.invoke('captureFocus'))
  expect(focus).toMatchObject({
    revision: fixture.revision + 2, document_format: format,
    anchor: { kind: 'point' },
  })
  expect(Math.abs(focus.anchor.x - 80)).toBeLessThanOrEqual(1)
  expect(Math.abs(focus.anchor.y - 70)).toBeLessThanOrEqual(1)
  expect(await canvas.evaluate((element, { x, y }) => [...element.getContext('2d').getImageData(x, y, 1, 1).data],
    focus.anchor)).toEqual([8, 127, 245, 255])
  let exported = ''
  await page.route('**/api/documents/doc-a/export-pdf', route => {
    exported = route.request().postDataJSON().html
    return route.fulfill({ contentType: 'application/pdf', body: '%PDF-Synthetic snapshot' })
  })
  const pdfDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export PDF', exact: true }).click()
  await expect.poll(() => exported).toContain(`data:image/png;base64,${png.toString('base64')}`)
  expect((await pdfDownload).suggestedFilename()).toBe(`${item.title}.pdf`)
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download source', exact: true }).click()
  expect((await downloaded).suggestedFilename()).toBe(`${item.title}.png`)
  await page.screenshot({ path: testInfo.outputPath('sample-drawing.png'), animations: 'disabled' })
  await page.evaluate(useArchive => window.testApp.mount({ component: 'test-support/browser/DrawingSampleHarness.vue',
    props: { documentId: 'doc-a', agentId: 7, archive: useArchive } }), archive)
  await expect(canvas).toBeVisible()
  expect(await pixel()).toEqual([8, 127, 245, 255])
  await page.evaluate(() => window.testApp.dark(true))
  await page.setViewportSize({ width: 390, height: 844 })
  await toolbar.getByRole('button', { name: 'More tools', exact: true }).click()
  const clear = page.getByRole('menuitem', { name: 'Clear', exact: true })
  await expect(clear).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('sample-drawing-mobile.png'), animations: 'disabled' })
  await clear.click()
  expect(await pixel()).toEqual([0, 0, 0, 0])
})
