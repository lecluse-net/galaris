import { writeFile } from 'node:fs/promises'
import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

const uri = 'document://00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002'
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII='

test('PDF preserves process diagrams and agent portraits without clickable objects', async ({ page, context }, testInfo) => {
  const documentId = '00000000-0000-0000-0000-000000000245'
  await jsonRoute(page, `**/api/documents/${documentId}`, { item: { ...documentFixture, id: documentId, media_type: 'text/html', payload: { text: '<h1>Synthetic preview</h1>' } }, agent_id: null })
  await page.route(`**/api/documents/${documentId}/thumbnail*`, route => route.fulfill({ contentType: 'image/webp', body: Buffer.from('UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA=', 'base64') }))
  const processUri = 'galaris://processes/synthetic_pdf_review'
  const graph = { schema_version: 'galaris.bpmn/v1', input_schema: {}, output_schema: {}, files: {}, actors: [{ id: 'reviewers', name: 'Document review team', kind: 'agent', agent_id: 7, user_id: null }], nodes: [
    { id: 'start', kind: 'start', title: 'Start', config: {}, x: 0, y: 0, body: null },
    { id: 'review', kind: 'task', title: 'Synthetic PDF review', config: { actor: 'reviewers' }, x: 0, y: 0, body: null },
    { id: 'end', kind: 'end', title: 'Complete', config: {}, x: 0, y: 0, body: null },
  ], flows: [{ id: 'one', source: 'start', target: 'review' }, { id: 'two', source: 'review', target: 'end' }] }
  await jsonRoute(page, '**/api/processes/internal/resource-preview?*', { uri: processUri, kind: 'process', id: 'synthetic_pdf_review', title: 'Synthetic PDF process', description: 'An invented review workflow.', revision: 1, graph, process_uri: processUri })
  await mount(page, 'core/util/components/RichTextEditor.vue')
  const portrait = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 128; canvas.height = 128
    const ctx = canvas.getContext('2d'); ctx.fillStyle = '#087FF5'; ctx.fillRect(0, 0, 128, 128)
    ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(64, 43, 22, 0, 2 * Math.PI); ctx.fill()
    ctx.beginPath(); ctx.roundRect(25, 76, 78, 60, 30); ctx.fill()
    return canvas.toDataURL('image/png').split(',')[1]
  })
  await page.route('**/api/agents/7/avatar?*', route => route.fulfill({ contentType: 'image/png', body: Buffer.from(portrait, 'base64') }))
  await page.evaluate(async ({ uri, png, processUri, documentId }) => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: `<h1>Illustrated PDF</h1><blockquote class="galaris-link-card galaris-agent-card"><p><a href="galaris://agent/7"><strong>Synthetic PDF agent</strong></a></p><p>Document reviewer</p></blockquote><blockquote class="galaris-link-card galaris-process-diagram"><p><a href="${processUri}"><strong>Synthetic PDF process</strong></a></p></blockquote><figure class="image" style="width:120px"><a href="${uri}"><img alt="Synthetic illustration" src="${uri}"></a></figure><p><a href="https://example.org/manual">Ordinary text link</a></p><blockquote class="galaris-link-card"><p><a href="document://${documentId}"><strong>Synthetic cited document</strong></a></p><p>${documentId}</p></blockquote>`,
    resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
    exportPdf: async html => { window.objectPdfSnapshot = html; return new Blob(['%PDF-1.7 fixture'], { type: 'application/pdf' }) },
  } }), { uri, png: portrait, processUri, documentId })
  const editor = page.locator('[data-editor-surface]')
  await expect(editor.locator('.galaris-agent-card img')).toHaveJSProperty('naturalWidth', 128)
  await editor.locator('.galaris-document-card').scrollIntoViewIfNeeded()
  await expect(editor.locator('.galaris-document-card img')).toHaveJSProperty('naturalWidth', 1)
  await expect(editor.getByRole('button', { name: 'Synthetic PDF review · review', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Export as PDF', exact: true }).click()
  await expect.poll(() => page.evaluate(() => typeof window.objectPdfSnapshot)).toBe('string')
  const snapshot = await page.evaluate(() => window.objectPdfSnapshot)
  await writeFile(testInfo.outputPath('objects-snapshot.html'), snapshot)
  const printed = await context.newPage()
  await printed.setContent(snapshot)
  await printed.evaluate(() => Promise.all([...document.images].map(image => image.decode())))
  await expect(printed.locator('.galaris-process-diagram')).toContainText('Synthetic PDF review')
  await expect(printed.locator('.galaris-process-diagram svg')).toHaveCount(1)
  await expect(printed.locator('.galaris-agent-card img')).toHaveJSProperty('naturalWidth', 128)
  await expect(printed.locator('.galaris-document-card img')).toHaveJSProperty('naturalWidth', 1)
  await expect(printed.locator('.galaris-document-card > p').last()).toHaveText(documentId)
  await expect(printed.locator('.galaris-process-diagram')).toContainText('Document review team')
  await expect(printed.locator('.galaris-link-card a[href], a[href]:has(img), button, iframe')).toHaveCount(0)
  await expect(printed.getByRole('link', { name: 'Ordinary text link' })).toHaveAttribute('href', 'https://example.org/manual')
  await printed.pdf({ path: testInfo.outputPath('objects.pdf'), printBackground: true, preferCSSPageSize: true })
  await printed.screenshot({ path: testInfo.outputPath('objects.png'), fullPage: true })
  await printed.close()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})

test('a document downloads its current content as a named PDF and remains editable after an export failure', async ({ page }, testInfo) => {
  let current = { ...documentFixture, title: 'Rapport été', media_type: 'text/html', content_profile: 'document',
    payload: { text: '<h1>Rapport été</h1><p>Current content</p><table><tbody><tr><th>Élément</th><th>Valeur</th></tr><tr><td>Mesure</td><td>42</td></tr></tbody></table>' } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/folders?*', [{ path: 'Reports', kind: 'custom', shared: false }])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await page.route(/\/api\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() !== 'GET') current = { ...current, ...route.request().postDataJSON(), revision: current.revision + 1 }
    return route.fulfill({ json: route.request().method() === 'GET' ? { item: current, agent_id: 7 } : current })
  })
  let snapshot
  let fail = true
  await page.route('**/api/documents/doc-a/export-pdf', route => {
    snapshot = route.request().postDataJSON().html
    return fail ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
      : route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.7\nfixture' })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7, editable: true }, privileges: ['DOCUMENT_EDIT'] })
  const editor = page.getByRole('textbox', { name: 'Content', exact: true })
  await editor.locator('p').first().click()
  await page.keyboard.press('End')
  await page.keyboard.insertText(' unsaved')
  const button = page.getByRole('button', { name: 'Export as PDF', exact: true })
  await button.click()
  await expect(page.getByText('Unable to export the document as PDF. Check its images and try again.')).toBeVisible()
  await expect(button).toBeEnabled()
  fail = false
  const downloaded = page.waitForEvent('download')
  await button.click()
  const download = await downloaded
  expect(download.suggestedFilename()).toBe('Rapport été.pdf')
  expect(snapshot).toContain('Current content unsaved')
  expect(snapshot).toContain('<title>Rapport été</title>')
  expect(snapshot).not.toMatch(/<script|contenteditable|<button/)
  await expect(editor).toContainText('Current content unsaved')
  await expect(button).toBeEnabled()
  await writeFile(testInfo.outputPath('pdf-snapshot.html'), snapshot)
})

test('PDF export embeds authorized images and cancels a stale download when the document changes', async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue')
  await page.evaluate(async ({ uri, png }) => {
    window.pdfSnapshots = []
    await window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
      profile: 'document', documentTitle: 'Images', modelValue: `<p>First</p><img src="${uri}" alt="Example">`,
      resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
      exportPdf: (html, signal) => new Promise((resolve, reject) => {
        window.pdfSnapshots.push(html)
        window.finishPdf = () => resolve(new Blob(['%PDF-1.7\nfixture'], { type: 'application/pdf' }))
        signal.addEventListener('abort', () => reject(signal.reason), { once: true })
      }),
    } })
  }, { uri, png })
  let downloads = 0
  page.on('download', () => downloads++)
  const button = page.getByRole('button', { name: 'Export as PDF', exact: true })
  await button.click()
  await expect.poll(() => page.evaluate(() => window.pdfSnapshots.length)).toBe(1)
  const snapshot = await page.evaluate(() => window.pdfSnapshots[0])
  expect(snapshot).toContain(`src="data:image/png;base64,${png}"`)
  expect(snapshot).not.toContain('document://')
  await expect(button).toBeDisabled()
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Second</p>' }))
  await page.evaluate(() => window.finishPdf())
  await expect(button).toBeEnabled()
  expect(downloads).toBe(0)
  await expect(page.locator('[data-editor-surface]')).toHaveText('Second')
})

test('Print uses current document content and loaded images on a light page without editor controls', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.print = () => { window.printCalls = (window.printCalls ?? 0) + 1 }
  })
  await mount(page, 'core/util/components/RichTextEditor.vue', { dark: true, props: {
    profile: 'document', modelValue: '<p>Initial content</p>',
  } })
  await page.evaluate(({ uri, png }) => window.testApp.setProps({
    resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
    modelValue: `<blockquote class="galaris-callout galaris-callout-warning"><p>Important</p></blockquote><figure class="image"><img src="${uri}" alt="Example"></figure><p>Edit me</p><script>window.printScriptRan = true</script>`,
  }), { uri, png })
  const editor = page.locator('[data-editor-surface]')
  await expect(editor.locator('img')).toHaveAttribute('src', /^blob:/)
  await editor.locator('p').last().click()
  await page.keyboard.press('End')
  await page.keyboard.type(' unsaved')
  await expect(page.getByRole('button', { name: 'Document preview', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Print', exact: true }).click()
  await expect.poll(() => page.evaluate(() => document.querySelector('.document-print-frame')?.contentWindow?.printCalls)).toBe(1)
  const frame = page.frameLocator('.document-print-frame')
  await expect(frame.locator('main')).toContainText('Edit me unsaved')
  await expect(frame.locator('main')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(frame.locator('blockquote')).toHaveText('Important')
  await expect(frame.locator('img')).toHaveJSProperty('naturalWidth', 1)
  await expect(frame.locator('script,button,.ck-toolbar,[contenteditable]')).toHaveCount(0)
  expect(await page.evaluate(() => window.printScriptRan)).toBeUndefined()
  expect(await page.evaluate(() => document.querySelector('.document-print-frame').contentWindow.printScriptRan)).toBeUndefined()
  const printed = page.frames().find(frame => frame.url() === 'about:srcdoc')
  await printed.page().emulateMedia({ media: 'print' })
  await page.locator('.document-print-frame').evaluate(frame => { frame.style.cssText = 'position:fixed;inset:0;width:210mm;height:297mm;border:0;z-index:99999;background:white' })
  await printed.locator('main').screenshot({ path: testInfo.outputPath('printed-document.png') })
  const url = await frame.locator('img').getAttribute('src')
  await page.evaluate(() => {
    const target = document.querySelector('.document-print-frame').contentWindow
    target.dispatchEvent(new target.Event('afterprint'))
  })
  await expect(page.locator('.document-print-frame')).toHaveCount(0)
  expect(await page.evaluate(async url => { try { await fetch(url); return true } catch { return false } }, url)).toBe(false)
  await expect(editor).toContainText('Edit me unsaved')
})

test('a missing attachment reports a print error and removes temporary content', async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: {
    profile: 'document', modelValue: `<p>Missing picture</p><img src="${uri}" alt="Missing">`,
  } })
  await page.getByRole('button', { name: 'Print', exact: true }).click()
  await expect(page.getByText('Unable to prepare the document for printing. Please try again.')).toBeVisible()
  await expect(page.locator('.document-print-frame')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Print', exact: true })).toBeEnabled()
})

test('switching documents while images load cancels stale printing and allows the next print', async ({ page }) => {
  await page.addInitScript(() => { window.print = () => { window.printCalls = 1 } })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<p>First document</p>' } })
  await page.evaluate(({ uri }) => {
    window.pendingImages = []
    window.testApp.setProps({
      resolveImage: () => new Promise(resolve => window.pendingImages.push(resolve)),
      modelValue: `<p>First document</p><img src="${uri}" alt="Loading">`,
    })
  }, { uri })
  await expect(page.locator('[data-editor-surface] img:not(.ProseMirror-separator)')).toBeVisible()
  const button = page.getByRole('button', { name: 'Print', exact: true })
  await button.click()
  await expect(button).toBeDisabled()
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Second document</p>' }))
  await page.evaluate(png => {
    const blob = new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' })
    window.pendingImages.forEach(resolve => resolve(blob))
  }, png)
  await expect(button).toBeEnabled()
  await expect(page.locator('.document-print-frame')).toHaveCount(0)
  await button.click()
  await expect.poll(() => page.evaluate(() => document.querySelector('.document-print-frame')?.contentWindow?.printCalls)).toBe(1)
  await expect(page.frameLocator('.document-print-frame').locator('main')).toHaveText('Second document')
  await page.evaluate(() => window.testApp.unmount())
  await expect(page.locator('.document-print-frame')).toHaveCount(0)
})
