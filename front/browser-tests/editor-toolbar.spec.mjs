import { test, expect, mount } from './fixtures.mjs'

for (const profile of ['document', 'rich-text']) test(`${profile} toolbar stays pinned after clicking the background and stops at the document boundary`, async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', {
    props: { profile, modelValue: '<p>Document paragraph</p>'.repeat(60), autoGrow: true, ariaLabel: 'Document' },
  })
  const editor = page.getByRole('textbox', { name: 'Document', exact: true })
  const toolbar = page.getByRole('toolbar', { name: 'Editor toolbar', exact: true }).and(page.locator('.galaris-toolbar'))
  await expect(editor).toBeVisible()
  await page.evaluate(() => {
    const host = document.querySelector('.ck-galaris-editor')
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
    await page.locator('.ck-galaris-editor').evaluate((host, width) => {
      host.style.width = `${width}px`
      host.style.marginInline = 'auto'
    }, width)
    await expect.poll(() => toolbar.evaluate(element => {
      const toolbar = element.getBoundingClientRect()
      const editor = element.closest('.ck-editor').getBoundingClientRect()
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
  const toolbar = page.getByRole('toolbar', { name: 'Editor toolbar', exact: true }).and(page.locator('.galaris-toolbar'))
  const editor = page.getByRole('textbox', { name: 'Document', exact: true })
  await editor.locator('strong').click()
  const removeFormat = toolbar.getByRole('button', { name: 'Remove Format', exact: true })
  await page.keyboard.press('Control+a')
  await expect(removeFormat).toBeEnabled()
  await removeFormat.focus()
  await page.keyboard.press('Enter')
  await expect(editor.locator('strong')).toHaveCount(0)
  await expect(editor).toHaveText('Formatted text')
  await page.setViewportSize({ width: 1920, height: 1000 })
  await toolbar.getByRole('button', { name: /Enter fullscreen mode/ }).click()
  await toolbar.getByRole('button', { name: 'Undo', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(editor.locator('strong')).toHaveText('Formatted text')
  await toolbar.getByRole('button', { name: /Leave fullscreen mode/ }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(editor.locator('strong')).toHaveText('Formatted text')
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toBe('<p><strong>Formatted text</strong></p>')
})
