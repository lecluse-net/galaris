import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'
const documentId = '00000000-0000-0000-0000-000000000001'
const attachmentId = '00000000-0000-0000-0000-000000000002'
const uri = `document://${documentId}/attachments/${attachmentId}`
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII='
const component = 'core/util/components/RichTextEditor.vue'

async function paste(page, text) {
  await page.locator('.ck-editor__editable').evaluate((root, text) => {
    const data = new DataTransfer(); data.setData('text/plain', text)
    root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, text)
}

test('conversation cards show the description collected with their shared thumbnail', async ({ page }, testInfo) => {
  let reads = 0
  await page.route('**/api/chat/rooms/room/messages/message/previews?*', route => route.fulfill({ json: [{
    uri: 'https://example.org', kind: 'web', title: 'News', subtitle: 'Publisher',
    description: ++reads > 1 ? 'Shared site description' : '', media_type: 'text/html',
    image_available: true, download_available: false, open_mode: 'external', external_url: 'https://example.org',
  }] }))
  await page.route('**/api/chat/rooms/room/messages/message/previews/image?*', route => route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') }))
  await mount(page, 'app/chat/components/MessageResourcePreviews.vue', { props: { roomId: 'room', messageId: 'message', viewerAgentId: 7 } })
  const card = page.locator('.resource-preview-card')
  await expect(card).toContainText('Shared site description')
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  await expect(card).toHaveCSS('background-color', 'rgb(251, 252, 254)')
  await expect(card).toHaveClass(/resource-preview-block--below-page/)
  const visual = await card.locator('.resource-preview-visual').boundingBox()
  const copy = await card.locator('.resource-preview-copy').boundingBox()
  expect(copy.x).toBeGreaterThanOrEqual(visual.x + visual.width)
  expect(copy.y).toBeCloseTo(visual.y, 0)
  const subtitle = card.locator('.resource-preview-subtitle')
  await expect(subtitle).not.toContainText('https://')
  await expect(card.locator('.resource-preview-uri')).toHaveText('https://example.org')
  const subtitleBox = await subtitle.boundingBox()
  const uriBox = await card.locator('.resource-preview-uri').boundingBox()
  expect(uriBox.y).toBeGreaterThanOrEqual(subtitleBox.y + subtitleBox.height)
  await card.screenshot({ path: testInfo.outputPath('shared-below-page.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await card.evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(390)
})

for (const dark of [false, true]) test(`static link cards roundtrip and export in ${dark ? 'dark' : 'light'} mode`, async ({ page }, testInfo) => {
  await page.route('https://www.youtube-nocookie.com/embed/**', route => route.fulfill({ contentType: 'text/html', body: '<button>Play</button>' }))
  await mount(page, component)
  await page.evaluate(async ({ uri, png, dark }) => {
    await window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', dark, props: {
      profile: 'document', modelValue: '<p>Report</p>', documentTitle: 'Report',
      attachments: [{ uri, name: 'scene.html', size: 850305 }],
      resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
      createLinkCard: async url => `<blockquote class="galaris-link-card"><figure class="image"><a href="${url}"><img src="${uri}" alt="Mont Saint-Michel" width="320"></a></figure><p><a href="${url}"><strong>Mont Saint-Michel</strong></a></p><p>A video of the island</p><p><a href="${url}">YouTube</a></p></blockquote>`,
      exportBundle: async html => { window.bundleSnapshot = html; return new Blob(['PK fixture'], { type: 'application/zip' }) },
    } })
  }, { uri, png, dark })
  await page.evaluate(dark => window.testApp.dark(dark), dark)
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('Control+End')
  await expect(page.getByRole('button', { name: 'Link preview or attachment', exact: true })).toHaveCount(0)
  await paste(page, 'https://youtu.be/dQw4w9WgXcQ')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.locator('.ck-editor__editable a').click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  const card = page.locator('.ck-editor__editable .galaris-link-card')
  await expect(card).toContainText('Mont Saint-Michel')
  await expect(card).toHaveCSS('background-color', dark ? 'rgb(36, 40, 47)' : 'rgb(251, 252, 254)')
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  await expect(card.locator('iframe')).toHaveAttribute('src', 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ')
  await expect(card.locator('iframe')).toBeVisible()
  const playerBox = await card.locator('iframe').boundingBox()
  const descriptionBox = await card.locator('p').filter({ hasText: 'A video of the island' }).boundingBox()
  const cardBox = await card.boundingBox()
  expect(playerBox.y).toBeGreaterThan(descriptionBox.y + descriptionBox.height)
  expect(playerBox.width).toBeCloseTo(cardBox.width - 26, 0)
  expect(playerBox.width / playerBox.height).toBeCloseTo(16 / 9, 1)
  await expect(card.locator('figure.image')).not.toBeVisible()
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  const source = await page.locator('.ck-source-editing-area textarea').inputValue()
  expect(source).toContain('galaris-link-card')
  expect(source).toContain(uri)
  expect(source).not.toContain('blob:')
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  await card.screenshot({ path: testInfo.outputPath(`link-card-${dark ? 'dark' : 'light'}.png`) })
  await expect(page.getByRole('button', { name: 'Export document and attachments (ZIP)', exact: true }).locator('.ck-button__label')).not.toBeVisible()
  await page.getByRole('button', { name: 'Export document and attachments (ZIP)', exact: true }).screenshot({ path: testInfo.outputPath('archive-icon.png') })
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export document and attachments (ZIP)', exact: true }).click()
  expect((await downloaded).suggestedFilename()).toBe('Report.zip')
  const snapshot = await page.evaluate(() => window.bundleSnapshot)
  expect(snapshot).toContain('data:image/png;base64,')
  expect(snapshot).toContain('Attachments')
  expect(snapshot).toContain('scene.html')
  expect(snapshot).toContain('0.850305 MB')
  expect(snapshot).toContain(uri)
  expect(snapshot).not.toContain('<iframe')
  await card.locator('p').filter({ hasText: 'A video of the island' }).click()
  await page.getByRole('button', { name: 'Show URL', exact: true }).click()
  await expect(card).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable a')).toHaveText('https://youtu.be/dQw4w9WgXcQ')
  await page.keyboard.press('Control+z')
  await expect(card).toContainText('Mont Saint-Michel')
  for (const selector of ['p:has(strong)', 'p:last-of-type a', 'p:has-text("A video of the island")']) {
    await card.locator(selector).click()
    await page.getByRole('button', { name: 'Show URL', exact: true }).click()
    await expect(card).toHaveCount(0)
    await page.locator('.ck-editor__editable a').click()
    await page.getByRole('button', { name: 'Show card', exact: true }).click()
    await expect(card).toContainText('Mont Saint-Michel')
    await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
    await expect(card.locator('iframe')).toBeVisible()
  }
})

test('reading a YouTube card embeds only the official player and leaves plain links as links', async ({ page }) => {
  await page.route('https://www.youtube-nocookie.com/embed/**', route => route.fulfill({ contentType: 'text/html', body: '<button>Play</button>' }))
  for (const url of ['https://youtu.be/dQw4w9WgXcQ', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'https://www.youtube.com/shorts/dQw4w9WgXcQ']) {
    await mount(page, 'core/util/components/RichText.vue', { props: { profile: 'document', content:
      `<blockquote class="galaris-link-card"><p><a href="${url}"><strong>Video</strong></a></p><p>Description</p></blockquote><p><a href="${url}">Plain link</a></p><blockquote class="galaris-link-card"><p><a href="https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ">Another site</a></p></blockquote>`,
    } })
    await expect(page.locator('iframe')).toHaveCount(1)
    await expect(page.locator('iframe')).toHaveAttribute('src', 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ')
    await expect(page.locator('iframe')).toHaveAttribute('allowfullscreen', '')
    await expect(page.getByRole('link', { name: 'Plain link', exact: true })).toHaveAttribute('target', '_blank')
  }
})

test('the card action is hidden for links that cannot become preview cards', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async ({ component, uri }) => window.testApp.mount({ component, props: {
    profile: 'document', modelValue: `<p><a href="${uri}">Attachment</a></p><p><a href="https://example.org">Website</a></p>`,
    createLinkCard: async () => '',
  } }), { component, uri })
  await page.locator('.ck-editor__editable a').first().click()
  await expect(page.getByRole('button', { name: 'Show card', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.locator('.ck-editor__editable a').last().click()
  await expect(page.getByRole('button', { name: 'Show card', exact: true })).toBeVisible()
})

// Direct upload remains covered through paste after removal of its toolbar shortcut.
for (const directUpload of [false, true]) test(`the document ${directUpload ? 'uploads and inserts a pasted file' : 'inserts an existing attachment from its toolbar'}`, async ({ page }) => {
  const current = { ...documentFixture, id: documentId, media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Report</p>' } }
  const attachment = { id: attachmentId, name: 'scene.html', media_type: 'text/html', size_bytes: 850305 }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [])
  let uploaded = !directUpload
  await page.route(`**/api/memory/documents/${documentId}/attachments?*`, route => {
    if (route.request().method() === 'POST') {
      uploaded = true
      return route.fulfill({ json: attachment })
    }
    return route.fulfill({ json: uploaded ? [attachment] : [] })
  })
  await page.route(`**/api/memory/documents/${documentId}/attachments/${attachmentId}/thumbnail?*`, route => route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') }))
  await page.route(`**/api/memory/items/${documentId}?*`, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: current })
    Object.assign(current, route.request().postDataJSON(), { revision: current.revision + 1, lock_version: current.lock_version + 1 })
    return route.fulfill({ json: current })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId, agentId: 7 }, privileges: ['MEMORY_EDIT'] })
  await expect(page.getByRole('textbox', { name: 'Content', exact: true })).toContainText('Report')
  if (!directUpload) {
    await expect(page.locator('.document-attachments')).toContainText('scene.html')
    await expect(page.locator('.document-attachments')).toContainText('0.850305 MB')
    const attachmentCard = page.locator('.document-attachments__item')
    const visual = await attachmentCard.locator('.resource-preview-visual').boundingBox()
    const copy = await attachmentCard.locator('.resource-preview-copy').boundingBox()
    expect(copy.x).toBeGreaterThanOrEqual(visual.x + visual.width)
    expect(copy.y).toBeCloseTo(visual.y, 0)
  }
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('Control+End')
  if (directUpload) {
    await page.locator('.ck-editor__editable').evaluate(root => {
      const data = new DataTransfer()
      data.items.add(new File(['<html><body>Scene</body></html>'], 'scene.html', { type: 'text/html' }))
      root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
    })
    await expect.poll(() => uploaded).toBe(true)
  } else {
    await page.getByRole('button', { name: 'Attachments', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('scene.html')
    await page.locator('.q-dialog .document-attachments__item').hover()
    const insert = page.getByRole('button', { name: 'Insert into document', exact: true })
    await expect(insert.locator('.q-icon')).toHaveText('post_add')
    expect(await insert.innerText()).not.toContain('Insert into document')
    await insert.click()
  }
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable .galaris-link-card')).toContainText('scene.html')
  await expect(page.locator('.document-attachments')).not.toBeVisible()
  await expect.poll(() => current.payload.text).toContain(uri)
  await page.getByRole('button', { name: 'Attachments', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('scene.html')
  await expect(page.getByRole('button', { name: 'Insert into document', exact: true })).toHaveCount(0)
})

for (const mode of ['edit', 'read']) for (const kind of ['audio', 'video', 'pdf']) test(`${mode}: attachment ${kind} plays inline without persisting its player`, async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async ({ uri, kind, mode }) => {
    let blob
    if (kind === 'audio') {
      const samples = 2000, buffer = new ArrayBuffer(44 + samples * 2), view = new DataView(buffer)
      const text = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)))
      text(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true); text(8, 'WAVE'); text(12, 'fmt ')
      view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
      view.setUint32(24, 8000, true); view.setUint32(28, 16000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true)
      text(36, 'data'); view.setUint32(40, samples * 2, true)
      blob = new Blob([buffer], { type: 'audio/wav' })
    } else if (kind === 'pdf') {
      let pdf = '%PDF-1.4\n'
      const offsets = [0]
      const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 600] /Resources << >> /Contents 4 0 R >>', '<< /Length 0 >>\nstream\nendstream']
      objects.forEach((object, index) => { offsets.push(pdf.length); pdf += `${index + 1} 0 obj\n${object}\nendobj\n` })
      const xref = pdf.length
      pdf += 'xref\n0 5\n0000000000 65535 f \n' + offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
      pdf += `trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
      blob = new Blob([pdf], { type: 'application/pdf' })
    } else {
      const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 128
      canvas.getContext('2d').fillRect(0, 0, 64, 128)
      const stream = canvas.captureStream(10), recorder = new MediaRecorder(stream, { mimeType: 'video/webm' }), chunks = []
      recorder.ondataavailable = event => chunks.push(event.data)
      blob = await new Promise(resolve => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: 'video/webm' }))
        let frame = 0
        const animate = setInterval(() => {
          const context = canvas.getContext('2d')
          context.fillStyle = ++frame % 2 ? '#ed1010' : '#0866ed'
          context.fillRect(0, 0, 64, 128)
        }, 50)
        recorder.start(); setTimeout(() => { clearInterval(animate); recorder.stop() }, 1000)
      })
      stream.getTracks().forEach(track => track.stop())
    }
    const { documentResourceHtml } = await import('/core/util/documentResources.ts')
    const attachment = { uri, name: 'Recording', size: blob.size, mediaType: blob.type }
    const html = documentResourceHtml(attachment)
    window.mediaHtml = html; window.mediaLoads = []; window.revokedMediaUrls = []
    const revoke = URL.revokeObjectURL.bind(URL)
    URL.revokeObjectURL = url => { window.revokedMediaUrls.push(url); revoke(url) }
    await window.testApp.mount({ component: mode === 'edit' ? 'core/util/components/RichTextEditor.vue' : 'core/util/components/RichText.vue', props: {
      profile: 'document', [mode === 'edit' ? 'modelValue' : 'content']: html,
      ...(mode === 'edit' ? { attachments: [attachment] } : {}),
      resolveImage: async (...reference) => { window.mediaLoads.push(reference); return blob },
    } })
  }, { uri, kind, mode })
  const player = page.locator(`.galaris-media-player ${kind === 'pdf' ? 'iframe' : kind}`)
  await expect(player).toBeVisible()
  if (kind !== 'pdf') {
    await expect(player).toHaveJSProperty('controls', true)
    await expect.poll(() => player.evaluate(element => element.readyState)).toBeGreaterThanOrEqual(1)
    if (kind === 'video') {
      await expect(player).toHaveCSS('object-fit', 'contain')
      expect(await player.evaluate(element => element.videoHeight / element.videoWidth)).toBe(2)
    }
    await player.evaluate(async element => { element.muted = true; await element.play() })
    await expect.poll(() => player.evaluate(element => element.currentTime)).toBeGreaterThan(0)
  } else {
    await expect(player).toHaveAttribute('src', /#view=FitH$/)
    const width = await player.evaluate(element => element.getBoundingClientRect().width)
    expect(width).toBeCloseTo(await player.evaluate(element => element.parentElement.clientWidth), 0)
    const frame = await page.locator('.galaris-pdf-frame').boundingBox()
    expect(frame.width / frame.height).toBeCloseTo((1 + Math.sqrt(5)) / 2, 3)
    const expand = await page.getByRole('button', { name: 'Open PDF in fullscreen', exact: true }).boundingBox()
    const title = await page.locator('blockquote.galaris-link-card strong').boundingBox()
    expect(expand.x).toBeGreaterThan(title.x + title.width)
    expect(expand.y).toBeLessThan(title.y + title.height)
    expect(expand.y + expand.height).toBeGreaterThan(title.y)
    expect(expand.y + expand.height).toBeLessThan(frame.y)
    const before = await page.evaluate(() => window.mediaLoads.length)
    await page.getByRole('button', { name: 'Open PDF in fullscreen', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Recording', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('iframe')).toHaveAttribute('src', /^blob:.*#view=FitH$/)
    expect(await page.evaluate(() => window.mediaLoads.length)).toBe(before)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(player).toBeVisible()
  }
  const objectUrl = await player.getAttribute('src')
  expect(objectUrl).toMatch(/^blob:/)
  const loads = await page.evaluate(() => window.mediaLoads)
  expect(loads.length).toBeGreaterThan(0)
  for (const reference of loads) expect(reference).toEqual([documentId, attachmentId])
  if (mode === 'edit') {
    await page.locator('.ck-editor__editable strong').click()
    expect(await page.evaluate(() => window.mediaLoads.length)).toBe(loads.length)
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    const source = await page.locator('.ck-source-editing-area textarea').inputValue()
    expect(source).toContain(`galaris-media-${kind}`)
    expect(source).toContain(uri)
    expect(source).not.toMatch(/<(audio|video|iframe)|blob:/)
    await page.getByRole('button', { name: 'Source', exact: true }).click()
  }
  await page.emulateMedia({ media: 'print' })
  await expect(player).not.toBeVisible()
  await page.emulateMedia({ media: 'screen' })
  await page.evaluate(mode => window.testApp.setProps({ [mode === 'edit' ? 'modelValue' : 'content']: '<p>Removed</p>' }), mode)
  await expect(player).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => window.revokedMediaUrls)).toContain(objectUrl.split('#')[0])
})

for (const mode of ['edit', 'read']) test(`${mode}: failed attachment downloads can retry and late downloads are discarded`, async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async ({ mode, uri }) => {
    window.createdMediaUrls = []
    const create = URL.createObjectURL.bind(URL)
    URL.createObjectURL = blob => { const url = create(blob); window.createdMediaUrls.push(url); return url }
    let first = true
    await window.testApp.mount({ component: mode === 'edit' ? 'core/util/components/RichTextEditor.vue' : 'core/util/components/RichText.vue', props: {
      profile: 'document', [mode === 'edit' ? 'modelValue' : 'content']: `<blockquote class="galaris-link-card galaris-media-audio"><p><a href="${uri}">Recording</a></p></blockquote>`,
      resolveImage: () => {
        if (first) { first = false; return Promise.reject(new Error('Unavailable')) }
        return new Promise(resolve => { window.finishMediaDownload = resolve })
      },
    } })
  }, { mode, uri })
  // The editor may replace its initial view during startup; test the active view's download.
  const retry = page.getByRole('button', { name: 'Could not load the media. Retry' })
  if (await retry.count()) await retry.click()
  await expect.poll(() => page.evaluate(() => typeof window.finishMediaDownload)).toBe('function')
  await page.evaluate(mode => window.testApp.setProps({ [mode === 'edit' ? 'modelValue' : 'content']: '<p>Removed</p>' }), mode)
  await expect(page.locator('.galaris-media-player')).toHaveCount(0)
  await page.evaluate(async () => { window.finishMediaDownload(new Blob(['late'], { type: 'audio/wav' })); await Promise.resolve() })
  expect(await page.evaluate(() => window.createdMediaUrls)).toEqual([])
})

test('document link thumbnails survive saving, reopening and repeated conversions', async ({ page }) => {
  const url = 'https://example.org/news'
  const current = { ...documentFixture, id: documentId, media_type: 'text/html', content_profile: 'document', payload: { text: `<p><a href="${url}">${url}</a></p>` } }
  const attachment = { id: attachmentId, name: 'link-preview.jpg', media_type: 'image/jpeg', size_bytes: 100 }
  let cardCalls = 0, imageCalls = 0
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [])
  await jsonRoute(page, `**/api/memory/documents/${documentId}/attachments?*`, [attachment])
  await page.route(`**/api/memory/documents/${documentId}/link-card?*`, route => {
    cardCalls++
    expect(route.request().postDataJSON()).toEqual({ url })
    return route.fulfill({ json: { attachment, html: `<blockquote class="galaris-link-card"><figure class="image"><a href="${url}"><img src="${uri}" alt="News" width="320"></a></figure><p><a href="${url}"><strong>News</strong></a></p><p>Daily news</p><p><a href="${url}">Publisher</a></p></blockquote>` } })
  })
  await page.route(`**/api/memory/documents/${documentId}/attachments/${attachmentId}?*`, route => {
    imageCalls++
    return route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') })
  })
  await page.route(`**/api/memory/documents/${documentId}/attachments/${attachmentId}/thumbnail?*`, route => route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') }))
  await page.route(`**/api/memory/items/${documentId}?*`, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: current })
    Object.assign(current, route.request().postDataJSON(), { revision: current.revision + 1, lock_version: current.lock_version + 1 })
    return route.fulfill({ json: current })
  })
  const options = { props: { documentId, agentId: 7 }, privileges: ['MEMORY_EDIT'] }
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', options)
  await page.locator('.ck-editor__editable a').click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  const card = page.locator('.ck-editor__editable .galaris-link-card')
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  await expect.poll(() => current.payload.text).toContain(uri)
  expect(current.payload.text).not.toContain('blob:')
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', options)
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  for (let i = 0; i < 3; i++) {
    await card.locator('strong').click()
    await page.getByRole('button', { name: 'Show URL', exact: true }).click()
    await expect(card).toHaveCount(0)
    await page.locator('.ck-editor__editable a').click()
    await page.getByRole('button', { name: 'Show card', exact: true }).click()
    await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  }
  expect(imageCalls).toBe(2)
  expect(cardCalls).toBe(1)
  const savedContent = current.payload.text
  const savedRevision = current.revision
  for (let i = 0; i < 2; i++) {
    await card.locator('img').click()
    await page.getByRole('button', { name: 'View image in fullscreen', exact: true }).click()
    const preview = page.locator('.fullscreen-preview')
    await expect(preview.getByRole('img')).toHaveJSProperty('naturalWidth', 1)
    await preview.getByRole('button', { name: 'Show actual size (1:1)', exact: true }).click()
    await preview.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(preview).toHaveCount(0)
    await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  }
  expect(current.payload.text).toBe(savedContent)
  expect(current.revision).toBe(savedRevision)
  // An unavailable preview stays reversible without repetitive notifications.
  await jsonRoute(page, `**/api/memory/documents/${documentId}/link-card?*`, {
    attachment: null,
    html: `<blockquote class="galaris-link-card"><p><a href="${url}">example.org</a></p></blockquote>`,
  })
  current.payload = { text: `<p><a href="${url}">${url}</a></p>` }
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', options)
  for (let i = 0; i < 2; i++) {
    await page.locator('.ck-editor__editable a').click()
    await page.getByRole('button', { name: 'Show card', exact: true }).click()
    await expect(card).toContainText('example.org')
    await expect(page.locator('.q-notification')).toHaveCount(0)
    await card.locator('a').click()
    await page.getByRole('button', { name: 'Show URL', exact: true }).click()
    await expect(card).toHaveCount(0)
  }
})

test('attachment links in the text open their viewer', async ({ page }) => {
  await mount(page, component, { props: { profile: 'document', modelValue: `<p><a href="${uri}">Scene 3D</a></p>` } })
  const link = page.locator('.ck-editor__editable a')
  await expect(link).toHaveText('Scene 3D')
  await link.click({ modifiers: ['Control'] })
  await expect.poll(() => page.evaluate(() => window.testApp.events.find(event => event.name === 'open-attachment')?.args)).toEqual([documentId, attachmentId])
})

test('only attachments embedded as links or images disappear from the list below the document', async ({ page }) => {
  const secondId = '00000000-0000-0000-0000-000000000003'
  const secondUri = `document://${documentId}/attachments/${secondId}`
  const files = [
    { id: attachmentId, name: 'embedded.bin', media_type: 'application/octet-stream', size_bytes: 10 },
    { id: secondId, name: 'remaining.bin', media_type: 'application/octet-stream', size_bytes: 20 },
  ]
  await page.route(`**/api/memory/documents/${documentId}/attachments/${secondId}?*`, route => route.fulfill({ status: 204 }))
  await mount(page, 'app/memory/components/DocumentAttachments.vue', { props: {
    documentId, agentId: 7, editable: true, managerMode: true, attachments: files,
    content: `<p><a href="${uri}">Embedded</a></p><pre><code>${secondUri}</code></pre>`,
  } })
  const list = page.locator('.document-attachments')
  await expect(list).toBeVisible()
  await expect(list).toContainText('remaining.bin')
  await expect(list).not.toContainText('embedded.bin')
  await page.evaluate(() => window.testApp.setProps({ content: '<p>Removed the inline attachment</p>' }))
  await expect(list).toContainText('embedded.bin')
  await list.getByRole('button', { name: 'Remove remaining.bin', exact: true }).click({ force: true })
  await page.getByRole('button', { name: 'Remove', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'removed').map(event => event.value))).toEqual([secondId])
})

test('an image attachment displays with its canonical source', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async ({ uri, png }) => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: `<figure class="image"><img src="${uri}" alt="photo.png"></figure>`,
    resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
  } }), { uri, png })
  await expect(page.locator('.ck-editor__editable img')).toHaveJSProperty('naturalWidth', 1)
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  expect(await page.locator('.ck-source-editing-area textarea').inputValue()).toContain(uri)
})

test('a thumbnail download failure can recover on the next card conversion', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async ({ uri, png }) => {
    window.imageCalls = 0
    await window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
      profile: 'document', modelValue: `<blockquote class="galaris-link-card"><figure class="image"><img src="${uri}" alt="News"></figure><p><a href="https://example.org">News</a></p><p>Description</p></blockquote>`,
      createLinkCard: async () => { throw new Error('The existing card should be reused') },
      resolveImage: async () => {
        if (++window.imageCalls === 1) throw new Error('Temporary download failure')
        return new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' })
      },
    } })
  }, { uri, png })
  await expect.poll(() => page.evaluate(() => window.imageCalls)).toBe(1)
  const card = page.locator('.ck-editor__editable .galaris-link-card')
  await card.getByText('Description', { exact: true }).click()
  await page.getByRole('button', { name: 'Show URL', exact: true }).click()
  await page.locator('.ck-editor__editable a').click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  expect(await page.evaluate(() => window.imageCalls)).toBe(2)
})

test('pasting a URL inserts an inline address without a modal or a metadata request', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async () => {
    window.cardCalls = 0
    await window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
      profile: 'document', modelValue: '<p>Before after</p>',
      createLinkCard: async () => { window.cardCalls++; return '<p>Card</p>' },
    } })
  })
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('Control+Home')
  for (let i = 0; i < 7; i++) await page.keyboard.press('ArrowRight', { delay: 50 })
  const url = 'https://example.org/page?first=1&second=2'
  await paste(page, url)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable p')).toHaveText(`Before ${url}after`)
  await expect(page.locator('.ck-editor__editable a')).toHaveAttribute('href', url)
  expect(await page.evaluate(() => window.cardCalls)).toBe(0)
  await page.keyboard.press('Control+z')
  await expect(page.locator('.ck-editor__editable')).toHaveText('Before after')
})

test('editing away a link while its card loads discards the late card', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async () => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: '<p>Report</p>', createLinkCard: () => new Promise(resolve => { window.finishCard = resolve }),
  } }))
  await page.locator('.ck-editor__editable').click()
  await paste(page, 'https://example.org')
  await page.locator('.ck-editor__editable a').click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('Control+a')
  await page.keyboard.type('Changed content')
  await page.evaluate(() => window.finishCard('<blockquote class="galaris-link-card"><p>Late card</p></blockquote>'))
  await expect(page.locator('.ck-editor__editable')).toHaveText('Changed content')
})

test('a failed conversion preserves the URL and a document switch cancels pending conversion', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async () => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: '<p>Report</p>', createLinkCard: async () => { throw new Error('Unavailable') },
  } }))
  await page.locator('.ck-editor__editable').click()
  await paste(page, 'https://example.org')
  await page.locator('.ck-editor__editable a').click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.q-notification')).toContainText('Preview unavailable')
  await expect(page.locator('.ck-editor__editable a')).toHaveText('https://example.org')
  await page.evaluate(() => window.testApp.setProps({ createLinkCard: () => new Promise(resolve => { window.finishCard = resolve }) }))
  await page.locator('.ck-editor__editable a').click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Another document</p>' }))
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.evaluate(() => window.finishCard('<p>Obsolete card</p>'))
  await expect(page.locator('.ck-editor__editable')).toHaveText('Another document')
})

test('URLs pasted into code and text containing URLs do not prompt for cards', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async () => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: '<pre><code class="language-plaintext">code</code></pre>', createLinkCard: async () => '<p>Card</p>',
  } }))
  await page.locator('.ck-editor__editable code').click()
  await paste(page, 'https://example.org/code')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable code')).toContainText('https://example.org/code')
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Report</p>' }))
  await page.locator('.ck-editor__editable').click()
  await paste(page, 'Read https://example.org for details')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable')).toContainText('Read https://example.org for details')
})

test('a full HTML paste becomes editable styled content with owned images', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async uri => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: '<p>Report</p>',
    importImage: async url => { (window.importedImages ??= []).push(url); return uri },
    uploadImage: async file => { window.pastedImage = { type: file.type, size: file.size }; return uri },
    resolveImage: async () => new Blob([], { type: 'image/png' }),
  } }), uri)
  const html = `<!doctype html><html><head><style>.intro{color:#123456;font-size:20px;font-weight:bold}</style></head><body><main><h1>Page title</h1><p class="intro">Editable paragraph</p><table><tr><td>Cell content</td></tr></table><img src="https://example.org/picture.png"><img src="https://example.org/picture.png"><img src="data:image/png;base64,${png}"></main><script>window.ran=true</script></body></html>`
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('End'); await page.keyboard.press('Enter')
  await page.locator('.ck-editor__editable').evaluate((root, html) => {
    const data = new DataTransfer(); data.setData('text/plain', html)
    root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, html)
  await expect(page.locator('.ck-editor__editable h1')).toHaveText('Page title')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const paragraph = page.locator('.ck-editor__editable p').filter({ hasText: 'Editable paragraph' })
  await expect(paragraph.locator('strong')).toHaveText('Editable paragraph')
  await expect(paragraph.locator('strong')).toHaveCSS('color', 'rgb(18, 52, 86)')
  await expect(page.locator('.ck-editor__editable td')).toHaveText('Cell content')
  expect(await page.evaluate(() => window.importedImages)).toEqual(['https://example.org/picture.png'])
  expect(await page.evaluate(() => window.pastedImage)).toEqual({ type: 'image/png', size: Buffer.from(png, 'base64').length })
  await expect(page.getByRole('textbox', { name: 'Content', exact: true })).toContainText('Report')
  expect(await page.evaluate(() => window.ran)).toBeUndefined()
  await paragraph.click(); await page.keyboard.press('End'); await page.keyboard.type(' changed')
  const saved = await page.evaluate(() => window.testApp.events.filter(x => x.name === 'update:modelValue').at(-1)?.value)
  expect(saved).not.toMatch(/galaris-raw-html|<script|<style|class="intro"|https:\/\/example.org\/picture/)
  expect(saved.match(/document:\/\//g)).toHaveLength(3)
  await page.evaluate(content => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: { profile: 'document', modelValue: content } }), saved)
  await expect(page.getByRole('textbox', { name: 'Content', exact: true })).toContainText('Editable paragraph changed')
  await expect(page.locator('.ck-editor__editable p').filter({ hasText: 'Editable paragraph changed' }).locator('strong')).toHaveCSS('color', 'rgb(18, 52, 86)')
  await expect(page.locator('.ck-editor__editable td')).toHaveText('Cell content')
})

for (const format of ['HTML', 'Markdown']) test(`pasted ${format} document images are saved through the attachment API and reopen locally`, async ({ page }) => {
  const current = { ...documentFixture, id: documentId, media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Report</p>' } }
  const attachment = { id: attachmentId, name: 'pasted-image.png', media_type: 'image/png', size_bytes: 68 }
  let imported = false
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice' }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [])
  await page.route(`**/api/memory/documents/${documentId}/attachments?*`, route => route.fulfill({ json: imported ? [attachment] : [] }))
  await page.route(`**/api/memory/documents/${documentId}/import-image?*`, route => {
    expect(route.request().postDataJSON()).toEqual({ url: 'https://example.org/picture.png' })
    expect(new URL(route.request().url()).searchParams.get('actor_agent_id')).toBe('7')
    imported = true
    return route.fulfill({ json: attachment })
  })
  await page.route(`**/api/memory/documents/${documentId}/attachments/${attachmentId}?*`, route => route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') }))
  await page.route(`**/api/memory/documents/${documentId}/attachments/${attachmentId}/thumbnail?*`, route => route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') }))
  await page.route(`**/api/memory/items/${documentId}?*`, route => {
    if (route.request().method() !== 'GET') Object.assign(current, route.request().postDataJSON(), { revision: current.revision + 1, lock_version: current.lock_version + 1 })
    return route.fulfill({ json: current })
  })
  const options = { props: { documentId, agentId: 7 }, privileges: ['MEMORY_EDIT'] }
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', options)
  await page.locator('.ck-editor__editable').click()
  await paste(page, format === 'HTML' ? '<p>Illustration</p><p><img src="https://example.org/picture.png" alt="Diagram"></p>' : 'Illustration\n\n![Diagram](https://example.org/picture.png)')
  await expect(page.locator('.ck-editor__editable img')).toHaveJSProperty('naturalWidth', 1)
  await expect.poll(() => current.payload.text).toContain(uri)
  expect(current.payload.text).not.toMatch(/blob:|https:\/\/example.org\/picture/)
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', options)
  await expect(page.locator('.ck-editor__editable')).toContainText('Illustration')
  await expect(page.locator('.ck-editor__editable img')).toHaveJSProperty('naturalWidth', 1)
})

for (const action of ['cancel', 'switch', 'readonly']) test(`pending HTML paste discards late images after ${action}`, async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async uri => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: '<p>Keep this</p>',
    importImage: (_url, signal) => new Promise(resolve => {
      window.finishPaste = () => resolve(uri)
      signal.addEventListener('abort', () => { window.pasteAborted = true })
    }),
  } }), uri)
  await page.locator('.ck-editor__editable').click()
  await paste(page, '<p>Late content</p><img src="https://example.org/picture.png">')
  await expect.poll(() => page.evaluate(() => typeof window.finishPaste)).toBe('function')
  if (action === 'cancel') await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  else await page.evaluate(action => window.testApp.setProps(action === 'switch' ? { modelValue: '<p>New document</p>' } : { readonly: true }), action)
  await expect.poll(() => page.evaluate(() => window.pasteAborted)).toBe(true)
  await page.evaluate(() => window.finishPaste())
  await expect(page.getByRole('status')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable')).toHaveText(action === 'switch' ? 'New document' : 'Keep this')
})

test('HTML paste preserves typing during image download and remains one undo step', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async uri => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: '<p>Before</p>',
    importImage: () => new Promise(resolve => { window.finishPaste = () => resolve(uri) }),
  } }), uri)
  const editor = page.getByRole('textbox', { name: 'Content', exact: true })
  await editor.click(); await page.keyboard.press('End')
  await paste(page, '<div style="background-color:#123456;color:#ffffff"><p>Inserted</p></div><img src="https://example.org/picture.png">')
  await expect.poll(() => page.evaluate(() => typeof window.finishPaste)).toBe('function')
  await page.keyboard.type(' while waiting')
  await page.evaluate(() => window.finishPaste())
  await expect(editor).toContainText('Inserted')
  await expect(editor).toContainText('Before while waiting')
  await page.keyboard.press('Control+z')
  await expect(editor).toHaveText('Before while waiting')
})

test('HTML attachments show loading then run in their isolated viewer', async ({ page }) => {
  let finish
  await page.route('**/api/memory/documents/*/attachments/*/thumbnail?*', route => route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') }))
  await page.route(`**/api/memory/documents/${documentId}/attachments/${attachmentId}?*`, async route => {
    await new Promise(resolve => { finish = resolve })
    await route.fulfill({ contentType: 'text/html', body: '<html><body><button onclick="this.textContent=\'Clicked\'">Interact</button></body></html>' })
  })
  await mount(page, 'app/memory/components/DocumentAttachments.vue', { props: { documentId, agentId: 7, attachments: [{ id: attachmentId, name: 'scene.html', media_type: 'text/html', size_bytes: 200 }], editable: true, content: `<a href="${uri}">Scene</a>` } })
  await page.locator('.document-attachments .resource-preview-main').click()
  await expect(page.getByText('Loading content…')).toBeVisible()
  finish()
  await page.frameLocator('iframe').getByRole('button', { name: 'Interact' }).click()
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Clicked' })).toBeVisible()
  await expect(page.locator('iframe')).not.toHaveAttribute('sandbox', /allow-same-origin/)
})

test('dropping multiple files permits cancellation and explains removal of a used file', async ({ page }) => {
  let uploads = 0, finish
  await page.route(`**/api/memory/documents/${documentId}/attachments?*`, async route => {
    uploads++
    await new Promise(resolve => { finish = resolve })
    await route.fulfill({ json: { id: attachmentId, name: 'scene.html', media_type: 'text/html', size_bytes: 20 } }).catch(() => {})
  })
  await mount(page, 'app/memory/components/DocumentAttachments.vue', { props: { documentId, agentId: 7, editable: true, attachments: [] } })
  await page.locator('.document-attachments').evaluate(root => {
    const data = new DataTransfer()
    data.items.add(new File(['<html>Scene</html>'], 'scene.html', { type: 'text/html' }))
    data.items.add(new File(['Second'], 'second.txt', { type: 'text/plain' }))
    root.dispatchEvent(new DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true }))
  })
  await expect.poll(() => uploads).toBe(1)
  await expect(page.getByText(/scene.html ·/)).toBeVisible()
  await page.getByRole('button', { name: 'Cancel upload', exact: true }).click()
  finish()
  await expect(page.getByRole('button', { name: 'Cancel upload', exact: true })).toHaveCount(0)
  expect(uploads).toBe(1)
  await page.evaluate(({ attachmentId, uri }) => window.testApp.setProps({ attachments: [{ id: attachmentId, name: 'data.bin', media_type: 'application/octet-stream', size_bytes: 20 }], content: `<p><a href="${uri}">Data</a></p>` }), { attachmentId, uri })
  await page.locator('.document-attachments__item').hover()
  await page.getByRole('button', { name: /Remove data.bin/ }).click()
  await expect(page.getByText('This file is still used in the text.', { exact: false })).toBeVisible()
  await expect(page.getByText(/The file remains available for the text and history/)).toBeVisible()
})

test('PDF exports only the document body without an attachment inventory', async ({ page }) => {
  await mount(page, component)
  await page.evaluate(async uri => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: '<p>Report</p>', attachments: [{ uri, name: 'scene.html', size: 850305 }],
    exportPdf: async html => { window.pdfSnapshot = html; return new Blob(['%PDF-1.7 fixture'], { type: 'application/pdf' }) },
  } }), uri)
  await expect(page.getByRole('button', { name: 'Export and print options', exact: true })).toHaveCount(0)
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export as PDF', exact: true }).click()
  await downloaded
  const snapshot = await page.evaluate(() => window.pdfSnapshot)
  expect(snapshot).not.toContain('Attachments')
  expect(snapshot).not.toContain('scene.html')
  expect(snapshot).not.toContain('document://')
})

test('HTML pasted inside a code block stays literal code without an import dialog', async ({ page }) => {
  await mount(page, component, { props: { profile: 'document', modelValue: '<pre><code class="language-html">Example</code></pre>' } })
  const code = page.locator('.ck-editor__editable pre')
  await code.click()
  await page.keyboard.press('End')
  await code.evaluate(root => {
    const data = new DataTransfer(); data.setData('text/plain', '<script>window.codeRan=true</script>')
    root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  })
  await expect(code).toContainText('<script>window.codeRan=true</script>')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await page.evaluate(() => window.codeRan)).toBeUndefined()
})
