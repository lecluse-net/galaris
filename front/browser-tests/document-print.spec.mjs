import { writeFile } from 'node:fs/promises'
import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

const uri = 'document://00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002'
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII='

test('a document downloads its current content as a named PDF and remains editable after an export failure', async ({ page }, testInfo) => {
  let current = { ...documentFixture, title: 'Rapport été', media_type: 'text/html', content_profile: 'document',
    payload: { text: '<h1>Rapport été</h1><p>Current content</p><table><tbody><tr><th>Élément</th><th>Valeur</th></tr><tr><td>Mesure</td><td>42</td></tr></tbody></table>' } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [{ path: 'Reports', kind: 'custom', shared: false }])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() !== 'GET') current = { ...current, ...route.request().postDataJSON(), revision: current.revision + 1 }
    return route.fulfill({ json: current })
  })
  let snapshot
  let fail = true
  await page.route('**/api/memory/documents/doc-a/export-pdf', route => {
    snapshot = route.request().postDataJSON().html
    return fail ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
      : route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.7\nfixture' })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7, editable: true }, privileges: ['MEMORY_EDIT'] })
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
  await expect(page.locator('.ck-editor__editable')).toHaveText('Second')
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
  const editor = page.locator('.ck-editor__editable')
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
  await expect(page.locator('.ck-editor__editable img')).toBeVisible()
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
