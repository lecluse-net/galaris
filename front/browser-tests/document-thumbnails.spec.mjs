import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document as documentFixture } from './data.mjs'
import { writeFile } from 'node:fs/promises'

test.beforeEach(async ({ page }) => {
  await jsonRoute(page, '**/api/memory/items/*?agent_id=*', { ...documentFixture, payload: { text: '<h1>Report</h1><p>Body</p>' } })
  await jsonRoute(page, '**/api/memory/documents/doc-a', { item: { ...documentFixture, payload: { text: '<h1>Report</h1>' } } })
})

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5AAAAABJRU5ErkJggg==', 'base64')

test('document cards inside messages display and refresh their saved revision thumbnail', async ({ page }, testInfo) => {
  const id = '00000000-0000-0000-0000-000000000001'
  const pagePreview = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 520; canvas.height = 320
    const context = canvas.getContext('2d')
    context.fillStyle = 'white'; context.fillRect(0, 0, 520, 320)
    context.fillStyle = '#292C30'; context.font = 'bold 26px sans-serif'
    context.fillText('Beginning of the document', 25, 45)
    context.font = '16px sans-serif'
    for (let line = 0; line < 8; line++) context.fillText(`Paragraph ${line + 1} — full page width`, 25, 85 + line * 27)
    return canvas.toDataURL('image/png').split(',')[1]
  }), 'base64')
  let revision = 1, captures = 0, readable = true
  await page.route('**/api/chat/rooms/room/messages/message/previews*', route => route.fulfill({ json: readable ? [{
    uri: `document://${id}`, kind: 'document', title: 'Report', description: 'Saved report', subtitle: '',
    media_type: 'text/html', image_available: false, download_available: false, open_mode: 'inline', metadata: { revision },
  }] : [] }))
  await page.route(`**/api/memory/documents/${id}/thumbnail*`, route => {
    captures += 1
    return route.fulfill({ contentType: 'image/png', body: pagePreview })
  })
  await mount(page, 'app/chat/components/MessageResourcePreviews.vue', {
    props: { roomId: 'room', messageId: 'message', conversationAgentId: 7, canReadDocuments: true, canEditDocuments: true },
  })
  const card = page.locator('.resource-preview-card')
  const image = card.locator('.resource-preview-visual img')
  await expect(image).toHaveJSProperty('naturalWidth', 520)
  await expect(image).toBeVisible()
  await card.screenshot({ path: testInfo.outputPath('document-page-thumbnail.png') })
  const first = await image.getAttribute('src')
  const update = () => page.evaluate(({ id, revision }) => window.testApp.emitSocket('memory.update', {
    data: { id, node_kind: 'document', revision },
  }), { id, revision })
  revision = 2
  await update()
  await expect.poll(() => captures).toBe(2)
  await expect(image).toHaveJSProperty('naturalWidth', 520)
  await expect(image).toBeVisible()
  await expect(image).not.toHaveAttribute('src', first)
  await card.hover()
  await card.getByRole('button', { name: 'Open in co-editing', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.find(event => event.name === 'openDocument')?.args[0])).toEqual({ id, label: 'Report' })
  readable = false
  await update()
  await expect(card).toHaveCount(0)
})

test('thumbnails use the print snapshot with embedded images for the saved revision', async ({ page, context }, testInfo) => {
  const id = '00000000-0000-0000-0000-000000000001'
  const attachment = '00000000-0000-0000-0000-000000000002'
  const body = '<h1>Rapport de mission</h1><p>Le début du document conserve sa mise en page.</p><table><tbody><tr><th>Élément</th><th>Résultat</th></tr><tr><td>Document long</td><td>Première page</td></tr></tbody></table>'
    + `<figure class="image"><img src="document://${id}/attachments/${attachment}" alt="Illustration"></figure>`
    + '<p>Suite du document</p>'.repeat(300)
  await jsonRoute(page, `**/api/memory/items/${id}?agent_id=7`, { ...documentFixture, revision: 12, lock_version: 17, title: 'Rapport de mission', payload: { text: body } })
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII=', 'base64')
  await page.route(`**/api/memory/documents/${id}/attachments/${attachment}?agent_id=7`, route => route.fulfill({ contentType: 'image/png', body: image }))
  let snapshot
  await page.route(`**/api/memory/documents/${id}/thumbnail?agent_id=7`, route => {
    snapshot = route.request().postDataJSON()
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await mount(page, 'app/memory/components/DocumentThumbnail.vue', { props: { documentId: id, agentId: 7, revision: 12 } })
  await expect(page.locator('.document-thumbnail img')).toHaveJSProperty('naturalWidth', 1)
  expect(snapshot.revision).toBe(12)
  expect(snapshot.lock_version).toBe(17)
  const expected = await page.evaluate(async ({ body, image }) => {
    const { preparePortableDocumentSnapshot } = await import('/core/util/documentSnapshot.ts')
    return preparePortableDocumentSnapshot(body, 'Rapport de mission', new AbortController().signal,
      async () => new Blob([Uint8Array.from(atob(image), x => x.charCodeAt(0))], { type: 'image/png' }))
  }, { body, image: image.toString('base64') })
  expect(snapshot.html).toBe(expected)
  await writeFile(testInfo.outputPath('thumbnail-print-snapshot.html'), snapshot.html)
  const preview = await context.newPage()
  await preview.setContent(snapshot.html)
  await preview.pdf({ path: testInfo.outputPath('thumbnail-first-page.pdf'), pageRanges: '1', preferCSSPageSize: true, printBackground: true })
  await preview.close()
})

test('document thumbnails refresh on revisions, discard late responses and clear on session changes', async ({ page }) => {
  let calls = 0, release, lateFinished = false
  await page.route('**/api/memory/documents/doc-a/thumbnail*', async route => {
    calls += 1
    const delayed = calls === 2
    if (delayed) await new Promise(resolve => { release = resolve })
    await route.fulfill({ contentType: 'image/png', body: png })
    if (delayed) lateFinished = true
  })
  await mount(page, 'app/memory/components/DocumentThumbnail.vue', { props: { documentId: 'doc-a', revision: 1, agentId: 7 } })
  const image = page.locator('.document-thumbnail img')
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  await page.evaluate(() => window.testApp.setProps({ revision: 2 }))
  await expect.poll(() => Boolean(release)).toBe(true)
  await expect(image).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ revision: 3 }))
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  const latest = await image.getAttribute('src')
  release()
  await expect.poll(() => lateFinished).toBe(true)
  await expect(image).toHaveAttribute('src', latest)
  expect(calls).toBe(3)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: null })))
  await expect(image).toHaveCount(0)
})

test('a mounted thumbnail refreshes on document changes even when its parent keeps the old revision', async ({ page }) => {
  let captures = 0
  await page.route('**/api/memory/documents/doc-a/thumbnail*', route => {
    captures += 1
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await mount(page, 'app/memory/components/DocumentThumbnail.vue', { props: { documentId: 'doc-a', revision: 1, agentId: 7 } })
  const image = page.locator('.document-thumbnail img')
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  const first = await image.getAttribute('src')
  await page.evaluate(() => window.testApp.emitSocket('memory.update', { data: { id: 'doc-a', node_kind: 'document', revision: 2 } }))
  await expect.poll(() => captures).toBe(2)
  await expect(image).not.toHaveAttribute('src', first)
  await page.evaluate(() => window.testApp.emitSocket('memory.delete', { data: { id: 'doc-a', node_kind: 'document' } }))
  await expect(image).toHaveCount(0)
})

test('offscreen documents wait for visibility and failures recover on reopening', async ({ page }) => {
  let calls = 0, available = false
  await page.route('**/api/memory/documents/doc-a/thumbnail*', route => {
    calls += 1
    return available ? route.fulfill({ contentType: 'image/png', body: png }) : route.fulfill({ status: 503 })
  })
  await mount(page, 'app/memory/components/DocumentThumbnail.vue', {
    props: { documentId: 'doc-a', revision: 1 }, containerStyle: { marginTop: '2000px' },
  })
  await expect(page.locator('.document-thumbnail')).toBeAttached()
  expect(calls).toBe(0)
  await page.locator('.document-thumbnail').scrollIntoViewIfNeeded()
  await expect.poll(() => calls).toBe(1)
  await expect(page.locator('.document-thumbnail .q-icon')).toBeVisible()
  available = true
  await mount(page, 'app/memory/components/DocumentThumbnail.vue', { props: { documentId: 'doc-a', revision: 1 } })
  await expect(page.locator('.document-thumbnail img')).toHaveJSProperty('naturalWidth', 1)
})

for (const surface of ['chat', 'library']) test(`rendered thumbnail keeps the ${surface} document accessible`, async ({ page }) => {
  await page.route('**/api/memory/documents/doc-a/thumbnail*', route => route.fulfill({ contentType: 'image/png', body: png }))
  if (surface === 'chat') {
    await jsonRoute(page, '**/api/chat/rooms/room-a/documents?*', { items: [{ id: 'doc-a', label: 'Report', uri: 'document://doc-a', revision: 1 }], total: 1 })
    await mount(page, 'app/chat/components/ConversationDocumentsPanel.vue', {
      props: { roomId: 'room-a', fromMessageId: 'message-a', canRead: true, embedded: true, conversationAgentId: 7 },
    })
  } else {
    await mount(page, 'app/memory/components/DocumentLibraryEntryRow.vue', {
      props: { entry: { item: { ...documentFixture, title: 'Report' }, owner_label: 'Alice', agent_ids: [7] }, loading: false, selectedDocumentId: null },
    })
  }
  const image = page.locator('.document-thumbnail img')
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  await image.click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => ['select', 'open'].includes(event.name)).length)).toBe(1)
  const icon = page.getByRole(surface === 'chat' ? 'img' : 'button', { name: 'Icon for document Report', exact: true })
  await expect(icon).toBeVisible()
  if (surface === 'chat') {
    await icon.click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'open').length)).toBe(2)
    await expect(page.locator('.tag-icon-picker')).toHaveCount(0)
  }
})
