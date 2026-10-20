import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'

test('clicking elsewhere in the same editor closes a right-click menu and its submenu', async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<h2>Synthetic heading</h2><p>Outside target</p>' } })
  const editor = page.locator('[data-editor-surface]')
  await editor.locator('h2').click({ button: 'right' })
  const menu = page.getByRole('menu', { name: 'Content', exact: true })
  await menu.getByRole('menuitem', { name: 'Style', exact: true }).hover()
  await expect(page.getByRole('menuitemradio', { name: 'Heading 2', exact: true })).toBeVisible()
  await editor.locator('p').click({ position: { x: 10, y: 10 } })
  await expect(menu).toBeHidden()
  await expect(page.getByRole('menuitemradio', { name: 'Heading 2', exact: true })).toBeHidden()
  await page.keyboard.type('Usable ')
  await expect(editor.locator('p')).toContainText('Usable ')
})

for (const width of [1440, 390]) test(`text context menu preserves the selection and changes heading styles (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: {
    profile: 'document', modelValue: '<h2>Synthetic heading</h2><p>Selected words stay here</p><p>Untouched paragraph</p>',
  } })
  const editor = page.locator('[data-editor-surface]'), paragraph = editor.locator('p').first()
  const menu = page.getByRole('menu', { name: 'Content', exact: true })
  await paragraph.click()
  await page.keyboard.press('Home')
  await page.keyboard.press('Control+Shift+ArrowRight')
  await page.keyboard.press('Control+Shift+ArrowRight')
  const selected = await page.evaluate(() => window.getSelection().toString())
  expect(selected.trim()).toBe('Selected words')
  await paragraph.click({ button: 'right', position: { x: 25, y: 10 } })
  await expect(menu).toBeVisible()
  await menu.getByRole('menuitemcheckbox', { name: 'Bold', exact: true }).click()
  await expect(paragraph.locator('strong')).toHaveText(selected)
  await expect(editor.locator('p').last()).toHaveText('Untouched paragraph')
  await editor.locator('h2').click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Style', exact: true }).hover()
  await expect(page.getByRole('menuitemradio', { name: 'Heading 2', exact: true })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByRole('menuitemradio', { name: 'Heading 3', exact: true })).toBeInViewport()
  await page.screenshot({ path: testInfo.outputPath('text-context-styles.png') })
  await page.getByRole('menuitemradio', { name: 'Heading 3', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(editor.locator('h3')).toHaveText('Synthetic heading')
  await editor.locator('h3').click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Style', exact: true }).click()
  await page.getByRole('menuitemradio', { name: 'Normal text', exact: true }).click()
  await expect(editor.locator('h3')).toHaveCount(0)
  await expect(editor.locator('p').first()).toHaveText('Synthetic heading')
  await paragraph.click({ button: 'right' })
  await page.keyboard.press('Escape')
  await expect(menu).toBeHidden()
  await editor.locator('p').last().click({ button: 'right' })
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Replacement document</p>' }))
  await expect(menu).toBeHidden()
  await expect(editor).toHaveText('Replacement document')
})

test('text context menus target lists and retain link and table actions', async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue:
    '<p>First paragraph</p><ul><li><p>List item</p></li></ul><p><a href="https://example.org">Linked words</a></p><table><tbody><tr><td>Cell words</td></tr></tbody></table>',
  } })
  const editor = page.locator('[data-editor-surface]')
  await editor.locator('p').first().click()
  await editor.locator('li p').click({ button: 'right' })
  await page.getByRole('menu', { name: 'Content', exact: true }).getByRole('menuitem', { name: 'Paragraph', exact: true }).click()
  const bullet = page.getByRole('menuitemcheckbox', { name: 'Bullet list', exact: true })
  await expect(bullet).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByRole('menuitem', { name: 'List properties', exact: true })).toBeVisible()
  await bullet.click()
  await expect(editor.locator('ul')).toHaveCount(0)
  await expect(editor.locator('p').first()).toHaveText('First paragraph')
  for (const [selector, label, command] of [['a', 'Insert a link or file', 'Insert or edit link'], ['td p', 'Table', 'Add row']]) {
    const target = editor.locator(selector)
    await target.click()
    await page.keyboard.press('Home')
    await page.keyboard.press('Shift+End')
    await target.click({ button: 'right', position: { x: 10, y: 10 } })
    const menu = page.getByRole('menu', { name: label, exact: true })
    await expect(menu.getByRole('menuitem', { name: command, exact: true })).toBeVisible()
    await menu.getByRole('menuitemcheckbox', { name: 'Italic', exact: true }).click()
    await expect(target.locator('em')).toHaveText(selector === 'a' ? 'Linked words' : 'Cell words')
  }
})

test('text clipboard menus preserve rich content and refuse failed or stale cuts', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<p><strong>Clipboard</strong> text</p>' } })
  const editor = page.locator('[data-editor-surface]'), menu = page.getByRole('menu', { name: 'Content', exact: true })
  await editor.locator('p').click()
  await page.keyboard.press('Control+a')
  await editor.locator('p').click({ button: 'right', position: { x: 20, y: 10 } })
  await menu.getByRole('menuitem', { name: 'Copy', exact: true }).click()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('Clipboard text')
  await editor.locator('p').click({ button: 'right', position: { x: 20, y: 10 } })
  await menu.getByRole('menuitem', { name: 'Cut', exact: true }).click()
  await expect(editor).toHaveText('')
  await editor.locator('p').click({ button: 'right', position: { x: 5, y: 10 } })
  await menu.getByRole('menuitem', { name: 'Paste', exact: true }).click()
  await expect(editor).toHaveText('Clipboard text')
  await expect(editor.locator('strong')).toHaveText('Clipboard')
  await page.evaluate(() => { navigator.clipboard.write = async () => { throw new Error('denied') } })
  await editor.locator('p').click()
  await page.keyboard.press('Control+a')
  await editor.locator('p').click({ button: 'right', position: { x: 20, y: 10 } })
  await menu.getByRole('menuitem', { name: 'Cut', exact: true }).click()
  await expect(page.getByText('Clipboard access denied. Use keyboard shortcuts to copy, cut or paste.')).toBeVisible()
  await expect(editor).toHaveText('Clipboard text')
  await page.evaluate(() => { navigator.clipboard.write = () => new Promise(resolve => { window.finishClipboard = resolve }) })
  await editor.locator('p').click({ button: 'right', position: { x: 20, y: 10 } })
  await menu.getByRole('menuitem', { name: 'Cut', exact: true }).click()
  await page.waitForFunction(() => Boolean(window.finishClipboard))
  await page.evaluate(() => { window.testApp.setProps({ modelValue: '<p>Replacement</p>' }); window.finishClipboard() })
  await expect(editor).toHaveText('Replacement')
  await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  expect(await editor.locator('p').evaluate(element => {
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    element.dispatchEvent(event)
    return event.defaultPrevented
  })).toBe(true)
  await expect(menu).toBeHidden()
})

const attachment = 'document://00000000-0000-4000-8000-000000000001/attachments/00000000-0000-4000-8000-000000000002'
const contextCases = [
  ['code', '<pre><code class="language-javascript">const answer = 42;</code></pre>', 'pre code', 'Code block options'],
  ['table', '<table><tbody><tr><td>Selected cell</td><td>Other cell</td></tr></tbody></table>', 'td p', 'Table'],
  ['link', '<p><a href="https://example.org/guide">Synthetic link</a></p>', 'a', 'Insert a link or file'],
  ['image', `<figure class="image"><img src="${attachment}" width="120" height="80" alt="Synthetic image"></figure>`, 'img', 'Insert a link or file'],
  ['card', '<blockquote class="galaris-link-card"><p><a href="https://example.org/guide">Synthetic guide</a></p></blockquote>', 'blockquote a', 'Insert a link or file'],
  ['agent', '<blockquote class="galaris-link-card galaris-agent-card"><p><a href="galaris://agent/7">Synthetic agent</a></p></blockquote>', '.agent-citation-avatar', 'Insert a link or file'],
  ['process', '<blockquote class="galaris-link-card galaris-process-diagram"><p><a href="galaris://processes/synthetic_context">Synthetic process</a></p></blockquote>', '.process-preview--inline', 'Insert a link or file'],
  ['object', '<section><details><summary>Synthetic object</summary>Preserved content</details></section>', '.embedded-code-widget', 'Embedded application'],
]

for (const mode of ['read', 'readonly']) for (const width of [1440, 390]) test(`document ${mode} suppresses all context menus and opens cards with a left click (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const html = '<p>Ordinary text</p>' + contextCases.filter(([kind]) => !['agent', 'process', 'object'].includes(kind)).map(([, html]) => html).join('')
  await mount(page, `core/util/components/${mode === 'read' ? 'RichText' : 'RichTextEditor'}.vue`, {
    props: { profile: 'document', ...(mode === 'read' ? { content: html } : { modelValue: html, readonly: true }) },
  })
  await page.context().route('https://example.org/guide', route => route.fulfill({ body: 'Synthetic external page' }))
  const content = page.locator(mode === 'read' ? '.rich-content-reader > .rich-content' : '[data-editor-surface]')
  for (const selector of ['p', 'pre code', 'td', 'a', 'img', 'blockquote']) {
    const target = content.locator(selector).first()
    expect(await target.evaluate(element => {
      const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
      element.dispatchEvent(event)
      return event.defaultPrevented
    })).toBe(true)
    await target.click({ button: 'right' })
    await expect(page.getByRole('menu')).toBeHidden()
    await expect(page.locator('.editorial-context')).toHaveCount(0)
  }
  await content.locator('pre code').click()
  await expect(page.getByRole('toolbar', { name: 'Code block options', exact: true })).toBeHidden()
  for (const click of [() => content.locator('a').first().click(), () => content.locator('blockquote').click({ position: { x: 4, y: 4 } })]) {
    const [popup] = await Promise.all([page.waitForEvent('popup'), click()])
    await expect(popup).toHaveURL('https://example.org/guide')
    await popup.close()
  }
  await page.screenshot({ path: testInfo.outputPath('document-reading.png') })
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})

for (const width of [1440, 390]) for (const [kind, html, selector, label] of contextCases) {
  test(`right-click ${kind} offers the same commands and hides the quick toolbar (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.route('**/api/agents/7/avatar?*', route => route.fulfill({ status: 404 }))
    await jsonRoute(page, '**/api/processes/internal/resource-preview?*', {
      uri: 'galaris://processes/synthetic_context', kind: 'process', id: 'synthetic_context', title: 'Synthetic process', description: '', revision: 1,
      graph: { schema_version: 'galaris.bpmn/v1', input_schema: {}, output_schema: {}, files: {}, actors: [],
        nodes: [{ id: 'start', kind: 'start', title: 'Start', config: {}, x: 0, y: 0, body: null }, { id: 'end', kind: 'end', title: 'End', config: {}, x: 320, y: 0, body: null }],
        flows: [{ id: 'done', source: 'start', target: 'end' }] },
    })
    await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<p>Before</p>' + html + '<p>After</p>' } })
    const editor = page.locator('[data-editor-surface]'), target = editor.locator(selector).first()
    const menu = page.getByRole('menu', { name: label, exact: true })
    const toolbar = page.getByRole('toolbar', { name: label, exact: true })
    await target.click({ button: 'right' })
    await expect(menu).toBeVisible()
    await expect(toolbar).toBeHidden()
    await page.keyboard.press('Escape')
    await expect(menu).toBeHidden()
    await expect(toolbar).toBeVisible()
    const buttons = await toolbar.getByRole('button').evaluateAll(buttons => buttons.map(button => ({
      name: button.getAttribute('aria-label'), icon: button.querySelector('.q-icon')?.innerHTML, disabled: button.disabled,
    })))
    await target.click({ button: 'right' })
    await expect(menu).toBeVisible()
    await expect(toolbar).toBeHidden()
    for (const button of buttons) {
      const { name } = button
      const item = menu.getByRole('menuitem', { name, exact: true })
      await expect(item).toBeVisible()
      expect(await item.locator('.q-icon').first().innerHTML()).toBe(button.icon)
      if (button.disabled) await expect(item).toHaveAttribute('aria-disabled', 'true')
    }
    expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
    await page.screenshot({ path: testInfo.outputPath(`${kind}-right-click.png`) })
    await page.keyboard.press('Escape')
    await expect(menu).toBeHidden()
    await expect(toolbar).toBeVisible()
    await target.click({ button: 'right' })
    if (kind === 'link') {
      await menu.getByRole('menuitem', { name: 'Insert or edit link', exact: true }).click()
      await expect(page.getByRole('dialog').getByRole('textbox', { name: 'URL or Galaris reference', exact: true })).toHaveValue('https://example.org/guide')
    } else {
      await menu.getByRole('menuitem', { name: 'Insert paragraph after block', exact: true }).click()
      await page.keyboard.type('Inserted paragraph')
      expect(await editorHtml(page)).toContain('Inserted paragraph')
      expect(await editorHtml(page)).toContain('After')
    }
  })
}

test('right-click targets another table, preserves selected cells and closes stale menus on document changes', async ({ page }) => {
  const table = text => `<table><tbody><tr><td>${text}</td><td>Second cell</td></tr></tbody></table>`
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: table('First table') + '<p>Between</p>' + table('Second table') } })
  const tables = page.locator('[data-editor-surface] table'), menu = page.getByRole('menu', { name: 'Table', exact: true })
  await tables.first().locator('td').first().click()
  await tables.last().locator('td').first().click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Add row', exact: true }).click()
  await expect(tables.first().locator('tr')).toHaveCount(1)
  await expect(tables.last().locator('tr')).toHaveCount(2)
  const cells = tables.last().locator('td')
  await cells.first().click()
  await cells.nth(1).click({ modifiers: ['Shift'] })
  await cells.first().click({ button: 'right' })
  await expect(menu.getByRole('menuitem', { name: 'Merge cells', exact: true })).not.toHaveAttribute('aria-disabled', 'true')
  await menu.getByRole('menuitem', { name: 'Merge cells', exact: true }).click()
  await expect(cells.first()).toHaveAttribute('colspan', '2')
  await cells.first().click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Split cell', exact: true }).click()
  await expect(cells).toHaveCount(4)
  await cells.first().click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Table styles', exact: true }).hover()
  await page.getByRole('button', { name: 'Ocean', exact: true }).click()
  await expect(tables.last()).toHaveClass(/galaris-table-blue/)
  await cells.first().click({ button: 'right' })
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>New document</p>' }))
  await expect(menu).toBeHidden()
  await expect(page.locator('[data-editor-surface]')).toHaveText('New document')
})

test('right-click code menus keep language controls and close when editing rights are removed', async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<pre><code class="language-javascript">const answer = 42;</code></pre>' } })
  const code = page.locator('[data-editor-surface] pre code'), menu = page.getByRole('menu', { name: 'Code block options', exact: true })
  await code.click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Block language', exact: true }).hover()
  await page.getByRole('menuitemradio', { name: 'Python', exact: true }).click()
  expect(await editorHtml(page)).toContain('language-python')
  await code.click({ button: 'right' })
  await expect(menu).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  await expect(menu).toBeHidden()
  const saved = await editorHtml(page)
  await code.click({ button: 'right' })
  await expect(menu).toBeHidden()
  await expect(page.getByRole('toolbar', { name: 'Code block options', exact: true })).toBeHidden()
  expect(await editorHtml(page)).toBe(saved)
})

for (const width of [1440, 390]) for (const [kind, html, selector, label] of [
  ['code', '<pre><code class="language-javascript">const answer = 42;</code></pre>', 'pre code', 'Code block options'],
  ['table', '<table><tbody><tr><td><p>Selected cell</p></td><td><p>Other cell</p></td></tr></tbody></table>', 'td p', 'Table'],
  ['card', '<blockquote class="galaris-link-card"><p><a href="https://example.org/guide"><strong>Synthetic guide</strong></a></p><p>Preserved description</p></blockquote>', 'blockquote strong', 'Insert a link or file'],
  ['link', '<p><a href="https://example.org/guide">Synthetic link</a></p>', 'a', 'Insert a link or file'],
  ['image', '<figure class="image"><img src="document://00000000-0000-4000-8000-000000000001/attachments/00000000-0000-4000-8000-000000000002" width="120" height="80" alt="Synthetic image"></figure>', 'img', 'Insert a link or file'],
]) test(`contextual ${kind} actions stay next to their target through scrolling and reopening (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: {
    profile: 'document', modelValue: '<p>First paragraph</p><p>Second paragraph</p>' + html + '<p>Following paragraph</p>'.repeat(30),
    maxHeight: '420px',
  } })
  const editor = page.locator('[data-editor-surface]')
  const target = editor.locator(selector).first()
  const toolbar = page.getByRole('toolbar', { name: label, exact: true })
  const nearTarget = async () => {
    const object = await target.boundingBox(), menu = await toolbar.boundingBox()
    if (!object || !menu) return false
    const verticalGap = Math.max(object.y - menu.y - menu.height, menu.y - object.y - object.height, 0)
    return verticalGap < 65 && menu.x >= 0 && menu.x + menu.width <= width
  }
  await target.click()
  await expect(toolbar).toBeInViewport()
  await expect.poll(nearTarget).toBe(true)
  await editor.evaluate(element => { element.scrollTop += 20 })
  await expect.poll(nearTarget).toBe(true)
  await page.screenshot({ path: testInfo.outputPath(`${kind}-context.png`) })
  if (kind === 'code' && width === 1440) {
    const scroll = await editor.evaluate(element => element.scrollTop)
    await editor.evaluate(element => { element.scrollTop = element.scrollHeight })
    await expect(toolbar).toBeHidden()
    await editor.evaluate((element, scroll) => { element.scrollTop = scroll }, scroll)
    await expect(toolbar).toBeInViewport()
  }
  await page.keyboard.press('Escape')
  await expect(toolbar).toBeHidden()
  await target.click()
  await expect(toolbar).toBeInViewport()
  await expect.poll(nearTarget).toBe(true)
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})

for (const profile of ['document', 'rich-text']) test(`${profile} toolbar stays pinned after clicking the background and stops at the document boundary`, async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', {
    props: { profile, modelValue: '<p>Document paragraph</p>'.repeat(60), autoGrow: true, ariaLabel: 'Document' },
  })
  const editor = page.getByRole('textbox', { name: 'Document', exact: true })
  const toolbar = page.getByRole('toolbar', { name: 'Content', exact: true }).and(page.locator('.editorial-toolbar'))
  await expect(editor).toBeVisible()
  await page.evaluate(() => {
    const host = document.querySelector('.tiptap-galaris-editor')
    host.style.width = 'calc(100% - 80px)'
    host.style.marginInline = '40px'
    const footer = document.createElement('div')
    footer.style.height = '1500px'
    host.after(footer)
  })
  await editor.locator('p').first().click()
  await page.evaluate(() => window.scrollTo(0, 500))
  await expect(toolbar).toBeInViewport()
  await page.mouse.click(10, 400)
  await expect(editor).not.toBeFocused()
  await expect(toolbar).toBeInViewport()
  await page.evaluate(() => window.scrollBy(0, 300))
  await expect(toolbar).toBeInViewport({ ratio: 1 })
  // Resizing the document pane must resize the pinned toolbar without another scroll.
  for (const width of [560, 1100, 720]) {
    await page.locator('.tiptap-galaris-editor').evaluate((host, width) => {
      host.style.width = `${width}px`
      host.style.marginInline = 'auto'
    }, width)
    await expect.poll(() => toolbar.evaluate(element => {
      const toolbar = element.getBoundingClientRect()
      const editor = element.closest('.tiptap-galaris-editor').getBoundingClientRect()
      return Math.max(Math.abs(toolbar.left - editor.left), Math.abs(toolbar.right - editor.right))
    })).toBeLessThanOrEqual(1)
    await expect(toolbar).toBeInViewport({ ratio: 1 })
  }
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect(toolbar).not.toBeInViewport()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})

test('formatting can be removed and restored by keyboard across editor resizing', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, 'core/util/components/RichTextEditor.vue', {
    props: { profile: 'document', modelValue: '<p><strong>Formatted text</strong></p>', ariaLabel: 'Document' },
  })
  const toolbar = page.getByRole('toolbar', { name: 'Content', exact: true }).and(page.locator('.editorial-toolbar'))
  const editor = page.getByRole('textbox', { name: 'Document', exact: true })
  await editor.locator('strong').click()
  const removeFormat = toolbar.getByRole('button', { name: 'Remove format', exact: true })
  await page.keyboard.press('Control+a')
  await expect(removeFormat).toBeEnabled()
  await removeFormat.focus()
  await page.keyboard.press('Enter')
  await expect(editor.locator('strong')).toHaveCount(0)
  await expect(editor).toHaveText('Formatted text')
  await page.setViewportSize({ width: 1920, height: 1000 })
  await toolbar.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await toolbar.getByRole('button', { name: 'Undo', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(editor.locator('strong')).toHaveText('Formatted text')
  await toolbar.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(editor.locator('strong')).toHaveText('Formatted text')
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toBe('<p><strong>Formatted text</strong></p>')
})
