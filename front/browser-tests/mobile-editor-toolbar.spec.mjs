import { test, expect, mount } from './fixtures.mjs'

const component = 'core/util/components/RichTextEditor.vue'
const documentUrl = 'https://galaris.example/memory/documents?document_id=00000000-0000-0000-0000-000000000001'

async function command(page, name) {
  const button = page.getByRole('button', { name, exact: typeof name === 'string' }).first()
  if (!await button.isVisible()) await page.getByRole('button', { name: 'Show more items', exact: true }).click()
  await button.click()
}

for (const profile of ['document', 'rich-text']) {
  test(`mobile ${profile} formatting remains usable across desktop transitions`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: profile === 'document' ? 320 : 390, height: 844 })
    await mount(page, component, { props: { profile, manageAttachments: true, modelValue: '<p>Keep this text</p>' } })
    const editor = page.locator('.ck-editor__editable')
    await editor.click()
    await page.keyboard.press('End')
    await page.keyboard.insertText(' on mobile')
    await command(page, 'Bulleted List')
    await expect(editor.locator('ul li')).toContainText('Keep this text on mobile')
    await command(page, 'Numbered List')
    await expect(editor.locator('ol li')).toContainText('Keep this text on mobile')
    await command(page, 'Numbered List')
    await command(page, /, Heading$/)
    await page.getByRole('menuitemradio', { name: 'Heading 2', exact: true }).click()
    await expect(editor.locator('h2')).toContainText('Keep this text on mobile')
    await command(page, 'Styles')
    await expect(page.getByRole('option', { name: 'Question', exact: true })).toBeInViewport()
    await page.screenshot({ path: testInfo.outputPath('mobile-block-styles.png') })
    await page.getByRole('option', { name: 'Question', exact: true }).click()
    await expect(editor.locator('blockquote')).toContainText('Keep this text on mobile')
    if (profile === 'document') {
      await command(page, 'Attachments')
      await expect.poll(() => page.evaluate(() => window.testApp.events.some(event => event.name === 'manage-attachments'))).toBe(true)
    }
    await page.screenshot({ path: testInfo.outputPath('mobile-toolbar.png') })
    await page.setViewportSize({ width: 1024, height: 900 })
    await command(page, 'Bold')
    await page.keyboard.insertText(' desktop')
    await expect(editor.locator('strong')).toContainText('desktop')
    await page.setViewportSize({ width: 1023, height: 900 })
    await expect(editor).toContainText('Keep this text on mobile')
    await expect(editor.locator('strong')).toContainText('desktop')
    await command(page, 'Galaris link')
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(editor).toContainText('Keep this text on mobile')
  })
}

for (const support of ['combined', 'text', 'files', 'none']) {
  test(`mobile PDF sharing preserves current content and adapts to ${support} support`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await mount(page, component)
    await page.evaluate(async ({ component, documentUrl, support }) => {
      window.shared = []; window.pdfSnapshots = []; window.failPdf = support === 'combined'
      Object.defineProperty(navigator, 'canShare', { configurable: true, value: data => support !== 'none' && Boolean(data.files?.length) && (support === 'combined' || support === 'text' && !data.url || !data.url && !data.text) })
      Object.defineProperty(navigator, 'share', { configurable: true, value: async data => {
        if (window.cancelShare) { window.cancelShare = false; throw new DOMException('Cancelled', 'AbortError') }
        window.shared.push({ title: data.title, url: data.url, text: data.text, name: data.files[0].name, type: data.files[0].type, content: await data.files[0].text() })
      } })
      await window.testApp.mount({ component, props: {
        profile: 'document', documentTitle: 'Mobile document', documentUrl, modelValue: '<p>Current text</p>',
        exportPdf: async html => {
          window.pdfSnapshots.push(html)
          if (window.failPdf) throw new Error('Unavailable')
          return new Blob(['%PDF-1.7\nfixture'], { type: 'application/pdf' })
        },
      } })
    }, { component, documentUrl, support })
    const editor = page.locator('.ck-editor__editable')
    await editor.click(); await page.keyboard.press('End'); await page.keyboard.insertText(' unsaved')
    await command(page, 'Share')
    const dialog = page.getByRole('dialog')
    if (support === 'combined') {
      await expect(dialog.getByRole('alert')).toContainText('Unable to export')
      await page.evaluate(() => { window.failPdf = false })
      await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
    }
    if (support === 'none') {
      const download = page.waitForEvent('download')
      await dialog.getByRole('button', { name: 'Save PDF', exact: true }).click()
      expect((await download).suggestedFilename()).toBe('Mobile document.pdf')
    } else {
      if (support === 'combined') {
        await page.evaluate(() => { window.cancelShare = true })
        await dialog.getByRole('button', { name: 'Share', exact: true }).click()
        await expect(dialog).toBeVisible()
        await expect(dialog.getByRole('alert')).toHaveCount(0)
      }
      await dialog.getByRole('button', { name: 'Share', exact: true }).click()
      await expect.poll(() => page.evaluate(() => window.shared.length)).toBe(1)
      const shared = await page.evaluate(() => window.shared[0])
      expect(shared).toMatchObject({ name: 'Mobile document.pdf', type: 'application/pdf', content: '%PDF-1.7\nfixture' })
      if (support === 'combined') expect(shared).toMatchObject({ url: documentUrl })
      else if (support === 'text') expect(shared).toMatchObject({ text: documentUrl })
      else expect(shared.url).toBeUndefined()
    }
    const snapshot = await page.evaluate(() => window.pdfSnapshots.at(-1))
    expect(snapshot).toContain('Current text unsaved')
    expect(snapshot).not.toContain(documentUrl)
    await expect(dialog).toHaveCount(0)
    await expect(editor).toContainText('Current text unsaved')
    await expect(editor).toBeEditable()
  })
}

test('mobile sharing cancels stale PDF preparation when the document changes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, component)
  await page.evaluate(async component => {
    window.pdfStarted = false
    await window.testApp.mount({ component, props: {
      profile: 'document', modelValue: '<p>First document</p>',
      exportPdf: (_html, signal) => new Promise(resolve => {
        window.pdfStarted = true; window.pdfSignal = signal
        window.finishPdf = () => resolve(new Blob(['%PDF-1.7\nold'], { type: 'application/pdf' }))
      }),
    } })
  }, component)
  await expect(page.locator('.ck-editor__editable')).toContainText('First document')
  await command(page, 'Share')
  await expect.poll(() => page.evaluate(() => window.pdfStarted)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Second document</p>' }))
  await expect.poll(() => page.evaluate(() => window.pdfSignal.aborted)).toBe(true)
  await page.evaluate(() => window.finishPdf())
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable')).toContainText('Second document')
})
