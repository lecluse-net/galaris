import { test, expect, mount } from './fixtures.mjs'

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
