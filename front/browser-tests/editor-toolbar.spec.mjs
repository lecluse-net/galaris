import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'

for (const width of [390, 1440]) test(`select all restores document focus and replaces the complete content (${width}px)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: {
    profile: 'document', modelValue: '<h2>First heading</h2><p>Second paragraph</p><table><tbody><tr><td>Final cell</td></tr></tbody></table>',
  } })
  const editor = page.locator('[data-editor-surface]')
  await page.getByRole('button', { name: 'Find', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Find', exact: true })).toBeFocused()
  const selectAll = page.getByRole('button', { name: 'Select all', exact: true })
  if (!await selectAll.isVisible()) await page.getByRole('button', { name: 'More tools', exact: true }).click()
  await selectAll.click()
  await expect(editor).toBeFocused()
  await expect.poll(() => page.evaluate(() => window.getSelection().toString())).toContain('Final cell')
  await page.keyboard.insertText('Replacement document')
  await expect(editor).toHaveText('Replacement document')
  await expect(editor.locator('table')).toHaveCount(0)
  await page.keyboard.press('Control+z')
  await expect(editor.locator('h2')).toHaveText('First heading')
  await expect(editor.locator('td')).toHaveText('Final cell')
})

for (const width of [390, 1440]) test(`simple fields preserve rich content and support code, checklists, tables and links (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const content = '<p>Editable paragraph</p><p><a href="galaris://goal/00000000-0000-4000-8000-000000000123">Existing reference</a></p>'
    + '<table><tbody><tr><td>Preserved cell</td></tr></tbody></table><p data-math="block">x^2</p>'
    + '<p>Inline sample</p><p>Block sample</p><p>Checklist sample</p><p>Insertion point</p><p>Plain context target</p>'
  await mount(page, 'app/memory/components/MemoryItemForm.vue', { props: {
    draft: { content, nodeKind: 'memory', mediaType: 'text/html', contentType: 'text', keywords: [], revision: 1 },
    editingId: null, sharingEditable: false,
  } })
  const editor = page.locator('[data-editor-surface]'), toolbar = page.locator('.editorial-toolbar')
  await page.evaluate(() => document.fonts.ready)
  await editor.locator('p').first().click()
  await page.keyboard.press('Home')
  await page.keyboard.press('Shift+End')
  await expect.poll(() => page.evaluate(() => window.getSelection().toString())).toBe('Editable paragraph')
  await toolbar.getByRole('button', { name: 'Bold', exact: true }).click()
  await expect(editor.locator('p strong').first()).toHaveText('Editable paragraph')
  await toolbar.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(editor.locator('strong')).toHaveCount(0)
  await toolbar.getByRole('button', { name: 'Insert or edit link', exact: true }).click()
  await page.getByRole('dialog').getByLabel('URL or Galaris reference', { exact: true }).fill('https://example.org')
  await page.getByRole('dialog').getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(editor.locator('a[href="https://example.org"]')).toHaveText('Editable paragraph')
  await expect(editor.getByRole('link', { name: 'Existing reference', exact: true })).toBeVisible()
  await expect(editor.locator('td')).toHaveText('Preserved cell')
  const saved = await editorHtml(page)
  expect(saved).toContain('href="galaris://goal/00000000-0000-4000-8000-000000000123"')
  expect(saved).toContain('x^2')
  for (const name of ['Fullscreen', 'Insert attachment', 'Inline equation', 'Block equation']) {
    await expect(toolbar.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  await editor.getByText('Plain context target', { exact: true }).click({ button: 'right' })
  const menu = page.getByRole('menu', { name: 'Content', exact: true })
  await menu.getByRole('menuitem', { name: 'Insert', exact: true }).hover()
  await expect(page.getByRole('menuitem', { name: 'Insert or edit link', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'Galaris link', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'Insert table', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  async function selectParagraph(text) {
    await editor.getByText(text, { exact: true }).click()
    await page.keyboard.press('Home')
    await page.keyboard.press('Shift+End')
    await expect.poll(() => page.evaluate(() => window.getSelection().toString())).toBe(text)
  }
  await selectParagraph('Inline sample')
  await toolbar.getByRole('button', { name: 'Inline code', exact: true }).click()
  await expect(editor.locator('p code')).toHaveText('Inline sample')
  await selectParagraph('Block sample')
  await toolbar.getByRole('button', { name: 'Code block', exact: true }).click()
  await expect(editor.locator('pre code')).toHaveText('Block sample')
  await selectParagraph('Checklist sample')
  await toolbar.getByRole('button', { name: 'Checklist', exact: true }).click()
  await editor.getByRole('checkbox', { name: 'Checklist sample', exact: true }).check()
  await editor.getByText('Insertion point', { exact: true }).click()
  await page.keyboard.press('End')
  await toolbar.getByRole('button', { name: 'Separator', exact: true }).click()
  await toolbar.getByRole('button', { name: 'Insert table', exact: true }).click()
  await expect(editor.locator('hr')).toHaveCount(1)
  await expect(editor.locator('table')).toHaveCount(2)
  const persisted = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:draft').at(-1).value.content)
  expect(persisted).toContain('data-checked="true"')
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { toolbarMode: 'simple', modelValue: persisted } })
  await expect(editor.getByRole('checkbox', { name: 'Checklist sample', exact: true })).toBeChecked()
  await expect(editor.locator('p code')).toHaveText('Inline sample')
  await expect(editor.locator('pre code')).toHaveText('Block sample')
  await expect(editor.locator('table')).toHaveCount(2)
  await toolbar.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  await page.screenshot({ path: testInfo.outputPath('simple-field.png') })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('simple-field-dark.png') })
  await mount(page, 'core/util/components/RichText.vue', { props: { content: persisted } })
  await expect(page.locator('li[data-checked="true"]')).toHaveText('Checklist sample')
})

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

// Mobile documents use the cursor toolbar; its selection/actions are exercised
// in mobile-editor-toolbar.spec.mjs rather than requiring a right-click there.
for (const width of [1440]) test(`text context menu preserves the selection and changes heading styles (${width}px)`, async ({ page }, testInfo) => {
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

for (const mode of ['read', 'readonly']) for (const width of [1440, 390]) test(`document ${mode} preserves native mobile selection and opens cards with a left click (${width}px)`, async ({ page }, testInfo) => {
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
    })).toBe(width >= 1024)
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

for (const width of [1440]) for (const [kind, html, selector, label] of contextCases) {
  test(`right-click ${kind} preserves content and exposes its editing commands (${width}px)`, async ({ page }, testInfo) => {
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
    await page.keyboard.press(width === 390 ? 'ContextMenu' : 'Shift+F10')
    await expect(menu.getByRole('menuitem').first()).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(menu).toBeHidden()
    await target.click({ button: 'right' })
    await expect(menu).toBeVisible()
    await expect(toolbar).toBeHidden()
    expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
    await page.screenshot({ path: testInfo.outputPath(`${kind}-right-click.png`) })
    await page.keyboard.press('Escape')
    await expect(menu).toBeHidden()
    await expect(toolbar).toBeHidden()
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

// Floating-toolbar placement is retired; pointer and keyboard menu actions are covered above.

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
  const content = '<h2 style="color: #ff0000; text-align: center"><strong>Formatted heading</strong></h2>'
    + '<blockquote class="galaris-callout galaris-callout-info" style="color: #ff0000"><p><em>Callout</em></p></blockquote>'
    + '<ol start="3" style="color: #ff0000"><li><p><span style="font-family: Georgia; font-size: 24px; color: #ff0000; background-color: #ffff00">List item</span></p></li></ol>'
    + '<p><a href="https://example.org"><u>Linked text</u></a></p>'
    + '<table><tbody><tr><td colspan="2" style="background-color: #ffff00"><p><mark style="background-color: #ffff00">Cell</mark></p></td></tr></tbody></table>'
  await mount(page, 'core/util/components/RichTextEditor.vue', {
    props: { profile: 'document', modelValue: content, ariaLabel: 'Document' },
  })
  const toolbar = page.getByRole('toolbar', { name: 'Content', exact: true }).and(page.locator('.editorial-toolbar'))
  const editor = page.getByRole('textbox', { name: 'Document', exact: true })
  await editor.locator('strong').click()
  const original = await editorHtml(page)
  const removeFormat = toolbar.getByRole('button', { name: 'Remove format', exact: true })
  await page.keyboard.press('Control+a')
  await expect(removeFormat).toBeEnabled()
  await removeFormat.focus()
  await page.keyboard.press('Enter')
  await expect(editor.locator('strong, em, u, mark')).toHaveCount(0)
  await expect(editor.locator('h2')).toHaveText('Formatted heading')
  await expect(editor.locator('blockquote.galaris-callout-info')).toHaveText('Callout')
  await expect(editor.locator('ol[start="3"] li')).toHaveText('List item')
  await expect(editor.locator('a')).toHaveAttribute('href', 'https://example.org')
  await expect(editor.locator('td[colspan="2"]')).toHaveText('Cell')
  const cleaned = await editorHtml(page)
  expect(cleaned).not.toContain('style=')
  await page.setViewportSize({ width: 1920, height: 1000 })
  await toolbar.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await toolbar.getByRole('button', { name: 'Undo', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect.poll(() => editorHtml(page)).toBe(original)
  await toolbar.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => editorHtml(page)).toBe(original)
  await page.evaluate(value => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: { profile: 'document', modelValue: value } }), cleaned)
  await expect.poll(() => editorHtml(page)).toBe(cleaned)
})
