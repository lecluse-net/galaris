import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { devices } from '@playwright/test'

const component = 'core/util/components/RichTextEditor.vue'
const documentUrl = 'https://galaris.example/documents?document_id=00000000-0000-0000-0000-000000000001'

test.describe('document cursor toolbar', () => {
  test.use({ hasTouch: true, isMobile: true, userAgent: devices['Pixel 7'].userAgent, viewport: { width: 390, height: 844 } })
  test('touch actions follow text, table, image and code selections while long press stays native', async ({ page }, testInfo) => {
    await mount(page, component, { props: { profile: 'document', modelValue:
      '<p>Selected words</p><table><tbody><tr><td>First cell</td><td>Other cell</td></tr></tbody></table>'
      + '<figure class="image"><img src="document://00000000-0000-4000-8000-000000000001/attachments/00000000-0000-4000-8000-000000000002" alt="Synthetic image" width="120" height="80"></figure>'
      + '<pre><code class="language-javascript">const answer = 42;</code></pre><p>Preserved ending</p>',
    } })
    const editor = page.locator('[data-editor-surface]'), toolbar = page.getByRole('toolbar', { name: 'Contextual actions', exact: true })
    await editor.locator('p').first().tap()
    await editor.locator('p').first().evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element)
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
      document.dispatchEvent(new Event('selectionchange'))
    })
    expect(await editor.locator('p').first().evaluate(element => {
      const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
      element.dispatchEvent(event)
      return event.defaultPrevented
    })).toBe(false)
    await expect(page.getByRole('menu')).toHaveCount(0)
    expect(await page.evaluate(() => window.getSelection().toString())).toBe('Selected words')
    await page.getByRole('button', { name: 'Bold', exact: true }).tap()
    await expect(editor.locator('p strong').first()).toHaveText('Selected words')
    await page.getByRole('button', { name: 'More tools', exact: true }).tap()
    await page.getByRole('button', { name: 'Strike', exact: true }).tap()
    await expect(editor.locator('p s').first()).toHaveText('Selected words')
    await expect(page.getByRole('menu')).toHaveCount(0)

    await editor.locator('td p').first().tap({ position: { x: 10, y: 10 } })
    await expect(toolbar.getByRole('button', { name: 'Add row', exact: true })).toBeVisible()
    await toolbar.getByRole('button', { name: 'Add row', exact: true }).tap()
    await expect(editor.locator('tr')).toHaveCount(2)
    await toolbar.getByRole('button', { name: 'Table styles', exact: true }).tap()
    await page.getByRole('button', { name: 'Ocean', exact: true }).tap()
    await expect(editor.locator('table')).toHaveClass(/galaris-table-blue/)
    await expect(page.getByRole('button', { name: 'Ocean', exact: true })).toBeHidden()
    await page.screenshot({ path: testInfo.outputPath('mobile-table-context.png'), fullPage: true })

    await editor.locator('img').tap()
    await expect(toolbar.getByRole('button', { name: 'Add row', exact: true })).toHaveCount(0)
    await toolbar.getByRole('button', { name: 'Image properties', exact: true }).tap()
    await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Alternative text', exact: true })).toHaveValue('Synthetic image')
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).tap()
    await editor.locator('pre code').tap({ position: { x: 10, y: 10 } })
    await toolbar.getByRole('button', { name: 'Block language', exact: true }).tap()
    await page.getByRole('menuitemradio', { name: 'Python', exact: true }).tap()
    await expect(editor.locator('pre code')).toHaveClass(/language-python/)
    await toolbar.getByRole('button', { name: 'Insert paragraph after block', exact: true }).tap()
    await page.keyboard.insertText('Inserted on mobile')
    await expect(editor).toContainText('Inserted on mobile')
    await expect(editor).toContainText('Preserved ending')
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('mobile-context-dark.png'), fullPage: true })
    await page.setViewportSize({ width: 1024, height: 900 })
    await editor.locator('td p').first().click()
    await expect(toolbar.getByRole('button', { name: 'Add row', exact: true })).toBeVisible()
    await editor.locator('td p').first().click({ button: 'right' })
    await expect(page.getByRole('menu', { name: 'Table', exact: true })).toBeHidden()
    await page.keyboard.press('Escape')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.testApp.setProps({ readonly: true }))
    await expect(toolbar).toHaveCount(0)
    await expect(editor).toContainText('Inserted on mobile')
  })

  test('other rich text fields retain their context menu on mobile', async ({ page }) => {
    await mount(page, component, { props: { profile: 'rich-text', modelValue: '<table><tbody><tr><td>Unchanged field</td></tr></tbody></table>' } })
    await expect(page.getByRole('toolbar', { name: 'Contextual actions', exact: true })).toHaveCount(0)
    await page.locator('[data-editor-surface] td p').click({ button: 'right' })
    await page.getByRole('menu', { name: 'Table', exact: true }).getByRole('menuitem', { name: 'Add row', exact: true }).click()
    await expect(page.locator('[data-editor-surface] tr')).toHaveCount(2)
  })
})

test('native repeated deletion keeps the edited text while the mobile keyboard is composing', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, component, { props: { profile: 'document', modelValue: '<p>Keep deleting characters</p>' } })
  const editor = page.locator('[data-editor-surface]')
  await editor.click()
  await page.keyboard.press('End')
  await editor.dispatchEvent('compositionstart', { data: '' })
  for (let count = 0; count < 5; count++) {
    await editor.evaluate(element => {
      // A virtual keyboard edits the DOM; ProseMirror consumes its input events.
      element.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, inputType: 'deleteContentBackward' }))
      document.execCommand('delete')
      document.dispatchEvent(new Event('selectionchange'))
    })
  }
  await editor.dispatchEvent('compositionend', { data: '' })
  await expect(editor).toHaveText('Keep deleting chara')
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toBe('<p>Keep deleting chara</p>')
  await page.keyboard.insertText('!')
  await expect(editor).toHaveText('Keep deleting chara!')
})

test('virtual keyboard input does not restore a deletion awaiting DOM observation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, component, { props: { profile: 'document', modelValue: '<p>Keep deleting characters</p>' } })
  const editor = page.locator('[data-editor-surface]')
  await editor.click()
  await page.keyboard.press('End')
  for (let count = 0; count < 5; count++) {
    await editor.evaluate(element => {
      const text = element.querySelector('p').firstChild
      text.deleteData(text.length - 1, 1)
      window.getSelection().collapse(text, text.length)
      // Android keyboards can report 229 without compositionstart. The next
      // input may arrive before the preceding DOM mutation has been consumed.
      element.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Unidentified', keyCode: 229 }))
      element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }))
    })
  }
  await expect(editor).toHaveText('Keep deleting chara')
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toBe('<p>Keep deleting chara</p>')
})

async function command(page, name) {
  const button = page.getByRole('button', { name, exact: typeof name === 'string' }).first()
  if (!await button.isVisible()) await page.getByRole('button', { name: 'More tools', exact: true }).click()
  await button.click()
}

for (const profile of ['document', 'rich-text']) {
  test(`mobile ${profile} formatting remains usable across desktop transitions`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: profile === 'document' ? 320 : 390, height: 844 })
    await jsonRoute(page, '**/api/file-share/browser/schemes?*', [])
    await mount(page, component, { props: { profile, modelValue: '<p>Keep this text</p>' } })
    if (profile === 'document') await page.evaluate(async component => window.testApp.mount({ component, props: {
      profile: 'document', modelValue: '<p>Keep this text</p>', uploadFile: async () => 'document://00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002',
    } }), component)
    if (profile === 'document') {
      await expect(page.getByRole('button', { name: 'Share', exact: true })).toBeVisible()
      await page.getByRole('button', { name: 'More tools', exact: true }).click()
      await expect(page.getByRole('button', { name: 'Print', exact: true })).toHaveCount(0)
      await page.keyboard.press('Escape')
    }
    const editor = page.locator('[data-editor-surface]')
    await editor.click()
    await page.keyboard.press('End')
    await page.keyboard.insertText(' on mobile')
    await command(page, 'Bullet list')
    await expect(editor.locator('ul li')).toContainText('Keep this text on mobile')
    await command(page, 'Ordered list')
    await expect(editor.locator('ol li')).toContainText('Keep this text on mobile')
    await command(page, 'Ordered list')
    await command(page, profile === 'document' ? 'Style' : 'Heading')
    await page.getByRole('menuitemradio', { name: 'Heading 2', exact: true }).click()
    await expect(editor.locator('h2')).toContainText('Keep this text on mobile')
    await command(page, profile === 'document' ? 'Style' : 'Styles')
    await expect(page.getByRole('menuitemradio', { name: 'Question', exact: true })).toBeInViewport()
    await page.screenshot({ path: testInfo.outputPath('mobile-block-styles.png') })
    await page.getByRole('menuitemradio', { name: 'Question', exact: true }).click()
    await expect(editor.locator('blockquote')).toContainText('Keep this text on mobile')
    if (profile === 'document') {
      const picker = page.waitForEvent('filechooser')

      await command(page, 'Insert attachment')
      await (await picker).setFiles([])
      await expect(page.getByRole('dialog')).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath('mobile-toolbar.png') })
    await page.setViewportSize({ width: 1024, height: 900 })
    if (profile === 'document') {
      await expect(page.getByRole('button', { name: 'Print', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Share', exact: true })).toHaveCount(0)
    }
    await command(page, 'Bold')
    await page.keyboard.insertText(' desktop')
    await expect(editor.locator('strong')).toContainText('desktop')
    await page.setViewportSize({ width: 1023, height: 900 })
    if (profile === 'document') {
      await expect(page.getByRole('button', { name: 'Share', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Print', exact: true })).toHaveCount(0)
    }
    await expect(editor).toContainText('Keep this text on mobile')
    await expect(editor.locator('strong')).toContainText('desktop')

    await page.getByRole('button', { name: 'Galaris link', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
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
    const editor = page.locator('[data-editor-surface]')
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
  await expect(page.locator('[data-editor-surface]')).toContainText('First document')
  await command(page, 'Share')
  await expect.poll(() => page.evaluate(() => window.pdfStarted)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Second document</p>' }))
  await expect.poll(() => page.evaluate(() => window.pdfSignal.aborted)).toBe(true)
  await page.evaluate(() => window.finishPdf())
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('[data-editor-surface]')).toContainText('Second document')
})
