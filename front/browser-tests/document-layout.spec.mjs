import { test, expect, mount } from './fixtures.mjs'

const rows = Array.from({ length: 5 }, (_, index) => `<tr><td>Row ${index + 1}</td><td>Middle</td><td>Right edge</td></tr>`).join('')
const table = `<figure class="table" style="width:100%"><table><tbody>${rows}</tbody></table></figure>`

test('print preserves both outside table borders and fits tables on the page', async ({ page, context }, testInfo) => {
  await page.addInitScript(() => { window.print = () => { window.printCalls = 1 } })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<h2>Full-width table</h2>' + table + '<h2>Resized table</h2>' + table.replace('width:100%', 'width:65%') } })
  await page.getByRole('button', { name: 'Print', exact: true }).click()
  await expect.poll(() => page.evaluate(() => document.querySelector('.document-print-frame')?.contentWindow?.printCalls)).toBe(1)
  const html = await page.locator('.document-print-frame').getAttribute('srcdoc')
  const printPage = await context.newPage()
  await printPage.setContent(html)
  const printableSize = { width: Math.round(190 * 96 / 25.4), height: Math.round(277 * 96 / 25.4) }
  await printPage.setViewportSize(printableSize)
  await printPage.emulateMedia({ media: 'print' })
  for (const table of await printPage.locator('table').all()) {
    await expect(table).toHaveCSS('border-left-style', 'solid')
    await expect(table).toHaveCSS('border-right-style', 'solid')
    const rect = await table.boundingBox()
    expect(rect.x).toBeGreaterThanOrEqual(1)
    expect(rect.x + rect.width).toBeLessThanOrEqual(printableSize.width - 1)
  }
  const widths = await printPage.locator('table').evaluateAll(tables => tables.map(table => table.getBoundingClientRect().width))
  expect(widths[1] / widths[0]).toBeCloseTo(.65, 2)
  await printPage.pdf({ path: testInfo.outputPath('table-borders.pdf'), format: 'A4', printBackground: true, preferCSSPageSize: true })
  await printPage.screenshot({ path: testInfo.outputPath('table-borders.png'), fullPage: true })
  await testInfo.attach('table-layout', { body: JSON.stringify(await printPage.locator('table').evaluateAll(tables => tables.map(table => ({
    table: table.getBoundingClientRect().toJSON(),
    wrapper: table.parentElement.getBoundingClientRect().toJSON(),
    display: getComputedStyle(table.parentElement).display,
    border: getComputedStyle(table).border,
    cells: [...table.rows[0].cells].map(cell => ({ rect: cell.getBoundingClientRect().toJSON(), left: getComputedStyle(cell).borderLeft, right: getComputedStyle(cell).borderRight })),
  }))), null, 2), contentType: 'application/json' })
  await printPage.close()
})

test('changing document layout and editing mode preserves the authored content', async ({ page }, testInfo) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<h2>Document title</h2><p>Keep this content</p>' + table } })
  const editor = page.getByRole('textbox', { name: 'Content', exact: true, includeHidden: true })
  const layout = page.getByRole('button', { name: 'Full width', exact: true })
  await expect(layout).toHaveCount(1)
  await expect(layout).toHaveAttribute('aria-pressed', 'false')
  const width = async () => (await editor.boundingBox()).width
  await expect(editor).toBeVisible()
  const initialWidth = await width()
  // Compare authored content, not CKEditor's transient widget DOM and styles.
  const content = () => editor.locator('h2, p, td').allTextContents()
  const snapshot = await content()
  expect(snapshot).toEqual(['Document title', 'Keep this content', ...Array.from({ length: 5 }, (_, index) => [`Row ${index + 1}`, 'Middle', 'Right edge']).flat()])
  await layout.click()
  await expect(layout).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(width).toBeGreaterThan(initialWidth)
  expect(await content()).toEqual(snapshot)
  await page.getByRole('button', { name: /Enter fullscreen mode/ }).click()
  expect(await content()).toEqual(snapshot)
  await layout.click()
  await expect(layout).toHaveAttribute('aria-pressed', 'false')
  expect(await content()).toEqual(snapshot)
  await page.screenshot({ path: testInfo.outputPath('fixed-width-fullscreen.png') })
  await page.getByRole('button', { name: /Leave fullscreen mode/ }).click()
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(page.locator('.ck-source-editing-area textarea')).toHaveValue(/Keep this content/)
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  const constrain = async width => page.locator('.ck-galaris-editor').evaluate((element, width) => {
    element.style.width = `${width}px`
    element.style.maxWidth = '100%'
  }, width)
  // A narrow document column must adapt even on a wide desktop viewport.
  await constrain(560)
  await expect(editor).toHaveAttribute('data-document-layout', 'full')
  await expect(layout).toHaveAttribute('aria-pressed', 'true')
  expect(await content()).toEqual(snapshot)
  await page.getByRole('button', { name: /Enter fullscreen mode/ }).click()
  await expect(editor).toHaveAttribute('data-document-layout', 'fixed')
  await page.getByRole('button', { name: /Leave fullscreen mode/ }).click()
  await expect(editor).toHaveAttribute('data-document-layout', 'full')
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await constrain(1100)
  await expect(editor).toHaveAttribute('data-document-layout', 'fixed')
  await expect(page.locator('.ck-source-editing-area textarea')).toHaveValue(/Keep this content/)
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  // Explicit full width remains selected after a narrow/wide round trip.
  await layout.click()
  await constrain(560)
  await expect(editor).toHaveAttribute('data-document-layout', 'full')
  await constrain(1100)
  await expect(editor).toHaveAttribute('data-document-layout', 'full')
  await layout.click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(editor).toHaveAttribute('data-document-layout', 'full')
  await expect(editor.getByRole('heading', { name: 'Document title' })).toBeVisible()
  expect(await content()).toEqual(snapshot)
  await page.screenshot({ path: testInfo.outputPath('fixed-width-mobile.png') })
  await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  await expect(editor).toHaveAttribute('contenteditable', 'false')
  await page.setViewportSize({ width: 1280, height: 900 })
  await expect(editor).toHaveAttribute('data-document-layout', 'fixed')
  await constrain(560)
  await expect(editor).toHaveAttribute('data-document-layout', 'full')
  await expect(editor).toHaveAttribute('contenteditable', 'false')
  await editor.press('x')
  expect(await content()).toEqual(snapshot)
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})
