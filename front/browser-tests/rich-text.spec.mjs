import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'

const corpus = '<h2>Été</h2><p><u>Underlined</u> <mark data-color="#fff59d" style="background-color: #fff59d">highlight</mark></p><ol start="3"><li><p>First</p><ul><li><p>Nested</p></li></ul></li></ol><table><tbody><tr><th colspan="2" colwidth="120,180"><p>Header</p></th></tr><tr><td><p>Left</p></td><td><p>Right</p></td></tr></tbody></table><pre><code class="language-html">  &lt;p&gt;\n    a  b\n</code></pre>'
const lastValue = page => page.evaluate(() => window.testApp.events.filter(value => value.name === 'update:modelValue').at(-1)?.value)

test('rich corpus survives actual editing, reopening and reading', async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: corpus, ariaLabel: 'Editorial content' } })
  const editor = page.getByRole('textbox', { name: 'Editorial content' })
  await expect(editor.locator('u')).toHaveText('Underlined')
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  await expect(editor.locator('ol')).toHaveAttribute('start', '3')
  await editor.locator('h2').click()
  await page.keyboard.press('End')
  await page.keyboard.type('!')
  const saved = await lastValue(page)
  expect(saved).toContain('<u>Underlined</u>')
  expect(saved).toContain('colspan="2"')
  expect(saved).toContain('  &lt;p&gt;\n    a  b\n')
  await page.evaluate(value => window.testApp.setProps({ modelValue: value }), saved)
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  await page.evaluate(value => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content: value } }), saved)
  await expect(page.locator('.rich-content u')).toHaveText('Underlined')
  await page.evaluate(value => { window.richSaved = value }, saved)
})

test('reader rejects active HTML, remote images and unsafe links', async ({ page }) => {
  await mount(page, 'core/util/components/RichText.vue', { props: { profile: 'rich-text', content: '<script>window.xss = true</script><p onclick="window.xss = true">Safe</p><a href="javascript:alert(1)">Bad</a><img src="https://example.invalid/tracker.png">' } })
  await expect(page.locator('.rich-content')).toContainText('Safe')
  await expect(page.locator('.rich-content script,.rich-content img')).toHaveCount(0)
  await expect(page.locator('.rich-content a')).not.toHaveAttribute('href')
  expect(await page.evaluate(() => window.xss)).toBeUndefined()
})


const uri = 'document://00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002'
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII='
async function command(page, name) {
  const button = page.getByRole('button', { name, exact: typeof name === 'string' }).first()
  const overflow = page.viewportSize().width < 1024 && !await button.isVisible()
  if (overflow) await page.getByRole('button', { name: 'More tools', exact: true }).click()
  await button.click()
  if (overflow) await expect(page.locator('.editorial-toolbar-overflow')).toBeHidden()
}
async function imageEditor(page) {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '', profile: 'document', ariaLabel: 'Editorial content' } })
  await expect(page.locator('[data-editor-surface]')).toBeVisible()
  await page.evaluate(({uri,png}) => window.testApp.setProps({
    resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
    modelValue: '<p>Before picture</p><figure class="image"><img width="200" alt="Example image" src="'+uri+'"></figure><p>After picture</p>',
  }), {uri,png})
  await expect(page.locator('[data-editor-surface] img')).toHaveAttribute('src', /^blob:/)
  await expect(page.locator('[data-editor-surface] img')).toHaveJSProperty('complete', true)
  await page.locator('[data-editor-surface] img').click()
}

async function reopenImage(page, html, readingWidth) {
  await page.evaluate(async ({ html, png, readingWidth }) => window.testApp.mount({
    component: readingWidth ? 'core/util/components/RichText.vue' : 'core/util/components/RichTextEditor.vue',
    props: { profile: 'document', ...(readingWidth ? { content: html } : { modelValue: html }),
      resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
    },
    ...(readingWidth ? { containerStyle: { width: `${readingWidth}px`, marginInline: 'auto' } } : {}),
  }), { html, png, readingWidth })
  await expect(page.locator('.rich-content img')).toHaveJSProperty('naturalWidth', 1)
}

for (const width of [1440, 390]) test(`image alignment moves the image and survives properties, reopening and reading at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await imageEditor(page)
  await page.evaluate(modelValue => window.testApp.setProps({ modelValue }), `<p>Before picture</p><figure class="image image_resized" style="width: 35%"><a href="https://example.org"><img alt="Example image" src="${uri}"></a><figcaption>Preserved caption</figcaption></figure><p>After picture</p>`)
  const picture = page.locator('.rich-content img')
  async function expectAlignment(alignment) {
    await expect.poll(() => picture.evaluate((image, alignment) => {
      const container = image.closest('.galaris-image-object')?.parentElement ?? image.closest('figure').parentElement
      const bounds = container.getBoundingClientRect(), style = getComputedStyle(container), box = image.getBoundingClientRect()
      const left = box.left - bounds.left - container.clientLeft - parseFloat(style.paddingLeft)
      const right = bounds.left + container.clientLeft + container.clientWidth - parseFloat(style.paddingRight) - box.right
      return Math.abs(alignment === 'left' ? left : alignment === 'right' ? right : left - right)
    }, alignment)).toBeLessThan(2)
  }
  for (const alignment of ['left', 'center', 'right']) {
    await picture.click({ button: 'right' })
    await page.keyboard.press('Escape')
    await command(page, alignment === 'left' ? 'Align left' : alignment === 'right' ? 'Align right' : 'Center')
    await expectAlignment(alignment)
  }
  await picture.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Image properties', exact: true }).click()
  await page.getByRole('textbox', { name: 'Alternative text', exact: true }).fill('Aligned illustration')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expectAlignment('right')
  const saved = await lastValue(page)
  expect(saved).toContain(uri)
  expect(saved).toContain('https://example.org')
  const readingWidth = await page.locator('[data-editor-surface]').evaluate(element => element.clientWidth - parseFloat(getComputedStyle(element).paddingLeft) - parseFloat(getComputedStyle(element).paddingRight))
  await reopenImage(page, saved)
  await expectAlignment('right')
  await expect(page.locator('figcaption')).toHaveText('Preserved caption')
  await page.screenshot({ path: testInfo.outputPath('image-alignment.png'), animations: 'disabled' })
  await reopenImage(page, saved, readingWidth)
  await expectAlignment('right')
})

for (const variant of ['block', 'inline', 'wrapped-inline', 'cell']) for (const delta of [-80, 80]) {
test(`image resizing survives a fresh editor and reader (${variant}, ${delta}px)`, async ({ page }) => {
  await imageEditor(page)
  const image = `<img width="200" alt="Example image" src="${uri}">`
  const figure = `<figure class="image">${image}<figcaption>Preserved caption</figcaption></figure>`
  const html = variant === 'block' ? figure : variant === 'inline' ? `<p>Before ${image} after</p>`
    : variant === 'wrapped-inline' ? `<p>Before <span class="image-inline">${image}</span> after</p>`
    : `<table><tbody><tr><td>${figure}</td><td><p>Reference cell</p></td></tr></tbody></table>`
  await page.evaluate(modelValue => window.testApp.setProps({ modelValue }), html)
  const picture = page.locator('[data-editor-surface] img')
  await expect(picture).toHaveJSProperty('naturalWidth', 1)
  await picture.click()
  const handle = await page.locator('.galaris-image-resize').boundingBox()
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2 + delta, handle.y + handle.height / 2, { steps: 8 })
  const resizedWidth = (await picture.boundingBox()).width
  await page.mouse.up()
  let saved = await lastValue(page)
  expect(saved).toContain(uri)
  expect(saved).not.toMatch(/blob:|galaris-image-resize|contenteditable/)
  await expect.poll(async () => (await picture.boundingBox()).width).toBeCloseTo(resizedWidth, 0)
  const writingWidth = await page.locator('[data-editor-surface]').evaluate(element => {
    const style = getComputedStyle(element)
    return element.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
  })
  await reopenImage(page, saved)
  await expect.poll(async () => (await picture.boundingBox()).width).toBeCloseTo(resizedWidth, 0)
  await picture.click()
  await page.keyboard.press('Shift+F10')
  await page.getByRole('menuitem', { name: 'Image properties', exact: true }).click()
  await page.getByRole('textbox', { name: 'Alternative text', exact: true }).fill('Updated description')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  saved = await lastValue(page)
  expect(saved).toContain('alt="Updated description"')
  await expect.poll(async () => (await picture.boundingBox()).width).toBeCloseTo(resizedWidth, 0)
  await reopenImage(page, saved, writingWidth)
  await expect.poll(async () => (await page.locator('.rich-content img').boundingBox()).width).toBeCloseTo(resizedWidth, 0)
  if (variant === 'block' || variant === 'cell') await expect(page.locator('figcaption')).toHaveText('Preserved caption')
})
}

test('native image handles resize, undo, captions and reopening retain the attachment', async ({ page }, testInfo) => {
  await imageEditor(page)
  const knob = page.locator('.galaris-image-resize')
  await expect(knob).toBeVisible()
  const before = await page.locator('[data-editor-surface] img').boundingBox()
  const box = await knob.boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 80, { steps: 8 })
  const draggedWidth = (await page.locator('[data-editor-surface] img').boundingBox()).width
  await page.mouse.up()
  // Finishing the gesture must keep the displayed size, before any reload.
  await expect.poll(async () => (await page.locator('[data-editor-surface] img').boundingBox()).width).toBeCloseTo(draggedWidth, 0)
  const resized = await lastValue(page)
  expect(resized).toMatch(/width: [0-9.]+%/)
  expect(resized).toContain(uri)
  expect(resized).not.toMatch(/blob:|data:image|contenteditable|ck-widget/)
  await command(page, 'Undo')
  await expect.poll(async () => (await page.locator('[data-editor-surface] img').boundingBox()).width).toBeCloseTo(before.width, 0)
  await command(page, 'Redo')
  await expect.poll(async () => (await page.locator('[data-editor-surface] img').boundingBox()).width).toBeCloseTo(draggedWidth, 0)
  await page.locator('[data-editor-surface] img').click()
  await page.keyboard.press('Shift+F10')
  await page.getByRole('menuitem', { name: 'Image properties', exact: true }).click()
  await page.getByRole('textbox', { name: 'Caption', exact: true }).fill('Figure one')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  const saved = await lastValue(page)
  expect(saved).toContain('<figcaption>Figure one</figcaption>')
  await reopenImage(page, saved)
  await expect.poll(async () => (await page.locator('[data-editor-surface] img').boundingBox()).width).toBeCloseTo(draggedWidth, 0)
  await expect(page.locator('[data-editor-surface] figcaption')).toHaveText('Figure one')
  await page.screenshot({ path: testInfo.outputPath('native-image-controls.png') })
})

test('native image drag moves a single attachment without duplicating it', async ({ page }) => {
  await imageEditor(page)
  await page.locator('[data-editor-surface] figure.image').dragTo(page.getByText('After picture', { exact: true }), { targetPosition: { x: 90, y: 22 } })
  await expect.poll(() => lastValue(page)).toContain(uri)
  const saved = await lastValue(page)
  expect(saved.match(/<img/g)).toHaveLength(1)
  expect(saved.indexOf('<img')).toBeGreaterThan(saved.indexOf('After picture'))
})

test('native upload emits canonical HTML when the upload finishes and supports alternative text', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p>Illustrated document</p>', profile: 'document', ariaLabel: 'Editorial content' } })
  await expect(page.locator('[data-editor-surface]')).toBeVisible()
  await page.evaluate(({uri,png}) => window.testApp.setProps({
    uploadImage: async (file, signal, progress) => { window.imageUpload = { type: file.type, size: file.size }; progress(1); return uri },
    resolveImage: async () => new Blob([Uint8Array.from(atob(png), x => x.charCodeAt(0))], { type: 'image/png' }),
  }), {uri,png})
  await page.locator('[data-editor-surface]').click()
  const chooser = page.waitForEvent('filechooser')
  await command(page, 'Insert attachment')
  await (await chooser).setFiles({ name: 'blue.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') })
  await expect.poll(() => lastValue(page)).toContain(uri)
  await page.locator('[data-editor-surface] img').click()
  await page.keyboard.press('Shift+F10')
  await page.getByRole('menuitem', { name: 'Image properties', exact: true }).click()
  await page.getByRole('textbox', { name: 'Alternative text', exact: true }).fill('A blue square')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  expect(await lastValue(page)).toContain('alt="A blue square"')
  expect(await lastValue(page)).not.toMatch(/blob:|data:image/)
  expect(await page.evaluate(() => window.imageUpload.type)).toBe('image/png')
})

for (const width of [1440, 390]) test(`table presets preserve editable structure, undo, reopening and print at ${width}px`, async ({ page, context }, testInfo) => {
  await page.setViewportSize({ width, height: 950 })
  const source = '<p>Before the table</p><figure class="table" style="width: 90%"><table><tbody><tr><th colspan="2" colwidth="120,180"><p>Synthetic summary</p></th></tr><tr><td><p>One</p></td><td><p>Two</p></td></tr><tr><td><p>Three</p></td><td><p>Four</p></td></tr></tbody></table><figcaption>Synthetic caption</figcaption></figure>'
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: source, ariaLabel: 'Editorial content' } })
  const surface = page.locator('[data-editor-surface]'), table = surface.locator('table')
  const tools = page.getByRole('menu', { name: 'Table', exact: true })
  const openStyles = async () => { await surface.getByText('One', { exact: true }).click({ button: 'right' }); await tools.getByRole('menuitem', { name: 'Table styles', exact: true }).hover() }
  await openStyles()
  await expect(page.getByRole('group', { name: 'Color palettes' })).toBeVisible()
  await page.locator('.editorial-table-gallery').screenshot({ path: testInfo.outputPath('table-style-gallery.png'), animations: 'disabled' })
  await page.getByRole('button', { name: 'Ocean', exact: true }).click()
  await expect(table).toHaveClass(/galaris-table-blue/)
  await expect(table).toHaveClass(/galaris-table-contrast/)
  await command(page, 'Undo')
  await expect(table).not.toHaveClass(/galaris-table-/)
  await command(page, 'Redo')
  await expect(table).toHaveClass(/galaris-table-contrast/)
  await openStyles()
  await expect(page.getByRole('button', { name: 'Ocean', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('tab', { name: 'Minimal', exact: true }).click()
  // Browsing is inert until a palette is chosen.
  await expect(table).toHaveClass(/galaris-table-contrast/)
  await page.getByRole('button', { name: 'Amber', exact: true }).click()
  await expect(table).toHaveClass(/galaris-table-minimal/)
  await openStyles()
  await page.getByRole('tab', { name: 'Banded', exact: true }).click()
  await page.getByRole('button', { name: 'Forest', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(table).toHaveClass(/galaris-table-green/)
  await expect(table).not.toHaveClass(/galaris-table-(blue|orange|minimal|contrast)/)
  await surface.getByText('Four', { exact: true }).click()
  await page.keyboard.press('Shift+F10')
  await tools.getByRole('menuitem', { name: 'Add row', exact: true }).click()
  await expect(table.locator('tr')).toHaveCount(4)
  await expect(table.locator('th')).toHaveAttribute('colspan', '2')
  await expect(table.locator('th')).toHaveAttribute('colwidth', '120,180')
  await expect(surface.locator('figcaption')).toHaveText('Synthetic caption')
  const saved = await lastValue(page)
  const rendering = cell => cell.evaluate(element => { const style = getComputedStyle(element); return { background: style.backgroundColor, color: style.color, border: style.borderBottomColor } })
  const appearance = await rendering(table.locator('tr').nth(3).locator('td').first())
  const editCount = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').length)
  await page.evaluate(() => window.testApp.dark(true))
  const darkAppearance = await rendering(table.locator('tr').nth(3).locator('td').first())
  expect(darkAppearance.background).not.toBe(appearance.background)
  expect(darkAppearance.color).not.toBe(appearance.color)
  await page.screenshot({ path: testInfo.outputPath('styled-table-dark.png') })
  await openStyles()
  await page.locator('.editorial-table-gallery').screenshot({ path: testInfo.outputPath('table-style-gallery-dark.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await page.evaluate(() => window.testApp.dark(false))
  expect(await rendering(table.locator('tr').nth(3).locator('td').first())).toEqual(appearance)
  await page.evaluate(() => window.testApp.dark(true))
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').length)).toBe(editCount)
  expect(await lastValue(page)).toBe(saved)
  await page.evaluate(modelValue => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', dark: true, props: { profile: 'document', modelValue } }), saved)
  await expect(table.locator('tr')).toHaveCount(4)
  expect(await rendering(table.locator('tr').nth(3).locator('td').first())).toEqual(darkAppearance)
  await page.evaluate(content => window.testApp.mount({ component: 'core/util/components/RichText.vue', dark: true, props: { profile: 'document', content } }), saved)
  const reader = page.locator('.rich-content table')
  await expect(reader.locator('th')).toHaveText('Synthetic summary')
  expect(await rendering(reader.locator('tr').nth(3).locator('td').first())).toEqual(darkAppearance)
  // Printing from a dark screen still uses the light document palette.
  await page.emulateMedia({ media: 'print' })
  expect(await rendering(reader.locator('tr').nth(3).locator('td').first())).toEqual(appearance)
  await page.emulateMedia({ media: 'screen' })
  const snapshot = await page.evaluate(async content => {
    const { preparePortableDocumentSnapshot } = await import('/core/util/documentSnapshot.ts')
    return preparePortableDocumentSnapshot(content, 'Synthetic styled table', new AbortController().signal)
  }, saved)
  const printed = await context.newPage()
  await printed.setContent(snapshot)
  await printed.emulateMedia({ media: 'print' })
  expect(await rendering(printed.locator('tr').nth(3).locator('td').first())).toEqual(appearance)
  await printed.pdf({ path: testInfo.outputPath('styled-table.pdf'), printBackground: true, preferCSSPageSize: true })
  await printed.screenshot({ path: testInfo.outputPath('styled-table-print.png'), fullPage: true })
  await printed.close()
  await page.evaluate(modelValue => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: { profile: 'document', modelValue } }), saved)
  await openStyles()
  await page.getByRole('button', { name: 'Remove preset style', exact: true }).click()
  await expect(table).not.toHaveClass(/galaris-table-/)
  await expect(table.locator('th')).toHaveAttribute('colwidth', '120,180')
  await expect(surface.locator('figcaption')).toHaveText('Synthetic caption')
})

test('native tables allow rows, merge/split, properties and column resizing', async ({ page }, testInfo) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<table><tbody><tr><td>One</td><td>Two</td></tr><tr><td>Three</td><td>Four</td></tr></tbody></table>', ariaLabel: 'Editorial content' } })
  const cells = page.locator('[data-editor-surface] td')
  await cells.first().click()
  const tools = page.getByRole('menu', { name: 'Table', exact: true })
  await page.keyboard.press('Shift+F10')
  await expect(tools).toBeVisible()
  await expect(tools.getByRole('menuitem', { name: 'Merge cells', exact: true })).toHaveAttribute('aria-disabled', 'true')
  await expect(tools.getByRole('menuitem', { name: 'Split cell', exact: true })).toHaveAttribute('aria-disabled', 'true')
  await tools.getByRole('menuitem', { name: 'Add row', exact: true }).click()
  await expect(page.locator('[data-editor-surface] tr')).toHaveCount(3)
  await page.keyboard.press('Shift+F10')
  await tools.getByRole('menuitem', { name: 'Delete row', exact: true }).click()
  await expect(page.locator('[data-editor-surface] tr')).toHaveCount(2)
  await cells.first().click()
  await cells.nth(1).click({ modifiers: ['Shift'] })
  await page.keyboard.press('Shift+F10')
  await expect(tools.getByRole('menuitem', { name: 'Merge cells', exact: true })).not.toHaveAttribute('aria-disabled', 'true')
  await tools.getByRole('menuitem', { name: 'Merge cells', exact: true }).click()
  await expect(cells.first()).toHaveAttribute('colspan','2')
  await page.keyboard.press('Shift+F10')
  await expect(tools.getByRole('menuitem', { name: 'Split cell', exact: true })).not.toHaveAttribute('aria-disabled', 'true')
  await tools.getByRole('menuitem', { name: 'Split cell', exact: true }).click()
  await expect(cells).toHaveCount(4)
  await page.keyboard.press('Shift+F10')
  await expect(tools.getByRole('menuitem', { name: 'Split cell', exact: true })).toHaveAttribute('aria-disabled', 'true')
  await page.keyboard.press('Escape')
  const cellBox = await cells.first().boundingBox()
  await page.mouse.move(cellBox.x + cellBox.width - 1, cellBox.y + 10)
  const grip = page.locator('.column-resize-handle').first()
  const box = await grip.boundingBox()
  await page.mouse.move(box.x + box.width/2, box.y + 10)
  await page.mouse.down()
  await page.mouse.move(box.x + 65, box.y + 10, {steps: 8})
  await page.mouse.up()
  const saved = await lastValue(page)
  expect(saved).toContain('<colgroup>')
  expect(saved).toMatch(/colwidth="[0-9,]+"/)
  await page.evaluate(value => window.testApp.setProps({modelValue:value}), saved)
  await expect(page.locator('[data-editor-surface] col')).toHaveCount(2)
  await cells.first().click()
  await page.keyboard.press('Shift+F10')
  await tools.getByRole('menuitem', { name: 'Cell properties', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Width in pixels', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await cells.first().click()
  await page.keyboard.press('Shift+F10')
  await tools.getByRole('menuitem', { name: 'Insert row above', exact: true }).click()
  await expect(page.locator('[data-editor-surface] tr')).toHaveCount(3)
  await page.keyboard.press('Shift+F10')
  await tools.getByRole('menuitem', { name: 'Delete row', exact: true }).click()
  await expect(page.locator('[data-editor-surface] tr')).toHaveCount(2)
  await page.keyboard.press('Shift+F10')
  await tools.getByRole('menuitem', { name: 'Table properties', exact: true }).click()
  await page.getByRole('textbox', { name: 'Caption', exact: true }).fill('Synthetic table caption')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(page.locator('[data-editor-surface] figcaption')).toHaveText('Synthetic table caption')
  await cells.first().click()
  await page.keyboard.press('Shift+F10')
  await tools.getByRole('menuitem', { name: 'Table properties', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Caption', exact: true })).toHaveValue('Synthetic table caption')
  await page.getByRole('textbox', { name: 'Caption', exact: true }).fill('')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(page.locator('[data-editor-surface] figcaption')).toHaveCount(0)
  await page.screenshot({path:testInfo.outputPath('native-table-controls.png')})
})

for (const profile of ['rich-text', 'document']) test(`fullscreen and read-only mode preserve ${profile} content; Source is limited to rich-text`, async ({page}) => {
  await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile,modelValue:'<p>Original</p>',ariaLabel:'Editorial content'}})
  const reading = page.getByRole('group', { name: 'Reading', exact: true })
  await expect(reading.getByRole('button', { name: 'Full width', exact: true })).toHaveCount(profile === 'document' ? 1 : 0)
  if (profile === 'document') {
    await expect(page.getByRole('button', { name: 'Source', exact: true })).toHaveCount(0)
    await page.locator('[data-editor-surface] p').fill('Edited document')
  } else {
  await command(page, 'Source')
  await page.locator('.galaris-source-editing-area textarea').fill('<h3>Edited source</h3><p><sup>2</sup></p>')
  await command(page, 'Source')
  await expect(page.locator('[data-editor-surface] h3')).toHaveText('Edited source')
  expect(await lastValue(page)).toContain('<sup>2</sup>')
  }
  const saved = await lastValue(page)
  await reading.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Editorial content' })).toContainText(profile === 'document' ? 'Edited document' : 'Edited source')
  await page.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  expect(await lastValue(page)).toBe(saved)
  await page.evaluate(()=>window.testApp.setProps({readonly:true}))
  await expect(page.locator('[data-editor-surface]')).toHaveAttribute('contenteditable','false')
  await expect(page.getByRole('button',{name:'Bold',exact:true})).toBeDisabled()
  if (profile === 'rich-text') await expect(reading.getByRole('button', { name: 'Source', exact: true })).toBeEnabled()
  else await expect(reading.getByRole('button', { name: 'Source', exact: true })).toHaveCount(0)
  await reading.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Editorial content' })).toHaveAttribute('contenteditable', 'false')
  expect(await lastValue(page)).toBe(saved)
})

test('pasted active HTML and external images cannot execute or fetch before saving', async ({page}) => {
  let fetched = false
  await page.route('https://example.invalid/**', route => { fetched=true; return route.abort() })
  await mount(page,'core/util/components/RichTextEditor.vue',{props:{modelValue:'<p>Before</p>',profile:'document',ariaLabel:'Editorial content'}})
  await page.locator('[data-editor-surface]').click()
  await page.locator('[data-editor-surface]').evaluate(root=>{
    const transfer = new DataTransfer()
    transfer.setData('text/html','<style>@import url("https://example.invalid/tracker.css"); p{background-image:url("https://example.invalid/bg.png")}</style><p onclick="window.xss=true">Pasted</p><img src="https://example.invalid/tracker.png" alt="Missing illustration"><script>window.xss=true</script>')
    root.dispatchEvent(new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true}))
  })
  await expect(page.locator('[data-editor-surface]')).toContainText('Pasted')
  await expect(page.locator('[data-editor-surface]')).toContainText('Missing illustration')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('The content was pasted, but some images could not be imported.', { exact: false })).toBeVisible()
  expect(await lastValue(page)).not.toMatch(/onclick|<img/)
  expect(fetched).toBe(false)
  expect(await page.evaluate(()=>window.xss)).toBeUndefined()
})
test('internal links have native application hrefs but persist canonical identities', async ({ page }) => {
  const uri = 'galaris://goal/00000000-0000-0000-0000-000000000123'
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: `<p><a href="${uri}">My goal</a> remains here.</p>`, ariaLabel: 'Editorial content' } })
  const editor = page.getByRole('textbox', { name: 'Editorial content' })
  await expect(editor.locator('a')).toHaveAttribute('href', '/goal?goal_id=00000000-0000-0000-0000-000000000123')
  await editor.click()
  await page.keyboard.press('End')
  await page.keyboard.type('!')
  const saved = await lastValue(page)
  expect(saved).toContain(`href="${uri}"`)
  expect(saved).not.toContain('data-rich-reference')
  await page.evaluate(value => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content: value } }), saved)
  await expect(page.locator('.rich-content a')).toHaveAttribute('href', '/goal?goal_id=00000000-0000-0000-0000-000000000123')
})

test('large documents remain editable in dark mobile and light desktop layouts', async ({ page }) => {
  const body = Array.from({ length: 1200 }, (_, index) => `<p>Section ${index}: Écrire et conserver les caractères accentués.</p>`).join('')
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: body, ariaLabel: 'Editorial content' }, dark: true })
  const editor = page.getByRole('textbox', { name: 'Editorial content' })
  await expect(editor.locator('p')).toHaveCount(1200)
  await editor.locator('p').first().click()
  await page.keyboard.press('Home')
  await page.keyboard.type('Checked ')
  expect((await lastValue(page)).length).toBeGreaterThan(70000)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(editor).toBeEditable()
  await expect(editor.locator('p')).toHaveCount(1200)
  await editor.locator('p').first().click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type('Mobile ')
  expect(await lastValue(page)).toContain('Mobile Checked Section 0')
  await page.setViewportSize({ width: 1280, height: 900 })
  await command(page, 'Fullscreen'); await expect(page.locator('.tiptap-galaris-editor')).toHaveClass(/editorial-fullscreen/)
})

for (const editing of [false, true]) {
  test(`${editing ? 'editor' : 'reader'} keeps readable HTML contrast when the application theme changes`, async ({ page }) => {
    const content = `${corpus}<p><a href="https://example.com">A link</a> and <code>inline code</code>.</p><blockquote><p>Quotation</p></blockquote><p><span style="background-color: #90caf9"><strong>Highlighted text</strong></span></p>`
    await mount(page, editing ? 'core/util/components/RichTextEditor.vue' : 'core/util/components/EditorialContent.vue', {
      props: editing ? { profile: 'document', modelValue: content, ariaLabel: 'Editorial content' } : { content, mediaType: 'text/html' },
    })
    // Quasar's dark-page token exists even in light mode; hosts may set their own ink.
    await page.evaluate(() => {
      document.body.style.setProperty('--q-dark-page', '#000000')
      document.querySelector('.rich-content').parentElement.style.color = '#000000'
    })
    for (const dark of [false, true, false]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await expect(page.locator('body')).toHaveClass(dark ? /body--dark/ : /body--light/)
      if (editing) await command(page, 'Fullscreen')
      const results = await page.locator('.rich-content').evaluate(root => {
        const rgb = color => color.match(/[\d.]+/g).slice(0, 3).map(Number)
        const luminance = color => rgb(color).map(value => {
          const channel = value / 255
          return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
        }).reduce((sum, channel, index) => sum + channel * [.2126, .7152, .0722][index], 0)
        const background = element => {
          if (!element) return 'rgb(255, 255, 255)'
          const color = getComputedStyle(element).backgroundColor
          const channels = color.match(/[\d.]+/g).map(Number)
          const alpha = channels[3] ?? 1
          if (alpha === 1) return color
          const behind = rgb(background(element.parentElement))
          return 'rgb(' + channels.slice(0,3).map((value,index) => value * alpha + behind[index] * (1-alpha)).join(',') + ')'
        }
        const nodes = [...root.querySelectorAll('h2,p,li,a,th,td,pre,code,mark,span,strong,blockquote')]
        const toolbar = document.querySelector('.editorial-toolbar')
        if (toolbar) nodes.push(toolbar)
        return {
          background: luminance(background(root)),
          contrasts: nodes.map(node => {
            const foreground = luminance(getComputedStyle(node).color)
            const backdrop = luminance(background(node))
            return { tag: node.outerHTML, ratio: (Math.max(foreground, backdrop) + .05) / (Math.min(foreground, backdrop) + .05) }
          }),
        }
      })
      expect(results.background)[dark ? 'toBeLessThan' : 'toBeGreaterThan'](dark ? .05 : .9)
      for (const { tag, ratio } of results.contrasts) expect(ratio, `${tag} in ${dark ? 'dark' : 'light'} mode`).toBeGreaterThanOrEqual(4.5)
      if (editing) await command(page, 'Fullscreen')
    }
    if (editing) expect(await lastValue(page)).toBeUndefined()
  })
}

for (const mode of ['reader', 'editor', 'document editor']) {
  const editing = mode !== 'reader'
  const profile = mode === 'document editor' ? 'document' : 'rich-text'
  // Internal citations use the resource-detail contract covered by galaris-links and process-references.
  test(`${mode} opens external links in a new tab`, async ({ page, context }) => {
    const html = '<p><a target="_blank" href="https://example.com">External</a></p>'
    await mount(page, editing ? 'core/util/components/RichTextEditor.vue' : 'core/util/components/RichText.vue', { props: { profile, ...(editing ? { modelValue: html } : { content: html }) } })
    const origin = await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)
    await context.route('https://example.com/**', route => route.fulfill({ contentType: 'text/html', body: 'External' }))
    for (const name of ['External']) {
      const link = page.getByRole('link', { name, exact: true })
      await expect(link).toHaveAttribute('target', '_blank')
      if (mode === 'editor') {
        await link.click()
        expect(context.pages()).toHaveLength(1)
        expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(origin)
      }
      const opened = context.waitForEvent('page')
      await link.click(mode === 'editor' ? { modifiers: ['Control'] } : {})
      const tab = await opened
      await expect.poll(() => tab.url()).toContain('https://example.com')
      expect(await tab.evaluate(() => window.opener)).toBeNull()
      await tab.close()
      expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(origin)
    }
    if (editing) {
      await page.getByRole('link', { name: 'External', exact: true }).click({ button: 'right' })
      const opened = context.waitForEvent('page')
      await page.getByRole('menuitem', { name: 'Open', exact: true }).click()
      const tab = await opened
      await expect.poll(() => tab.url()).toContain('https://example.com')
      await tab.close()
      expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(origin)
    }
  })
}


for (const profile of ['document', 'rich-text']) for (const readonly of [false, true]) for (const width of [1440, 390]) for (const autoGrow of [false, true]) test(`search highlights results and cycles without editing for ${profile} at ${width}px (autoGrow=${autoGrow}, readonly=${readonly})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 844 })
  const middle = Array.from({ length: 40 }, (_, index) => `<p>Filler paragraph ${index}</p>`).join('')
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: {
    profile, readonly, autoGrow, modelValue: '<p>First <strong>needle</strong></p>' + middle + '<p>Second needle</p>', ariaLabel: 'Document',
  }, containerStyle: { height: '700px', overflow: 'auto' } })
  const editor = page.locator('[data-editor-surface]')
  const original = await editorHtml(page)
  await editor.locator('p').first().click({ position: { x: 1, y: 1 } })
  await page.keyboard.press('Control+Home')
  await command(page, 'Find')
  const search = page.getByRole('search', { name: 'Find', exact: true })
  const input = search.getByRole('textbox', { name: 'Find', exact: true })
  await expect(input).toBeFocused()
  await expect(page.getByRole('dialog', { name: 'Find', exact: true })).toHaveCount(0)
  if (readonly) {
    await expect(search.getByRole('textbox', { name: 'Replace', exact: true })).toBeDisabled()
    await expect(search.getByRole('button', { name: 'Replace', exact: true })).toBeDisabled()
    await expect(search.getByRole('button', { name: 'Replace all', exact: true })).toBeDisabled()
  }
  await input.fill('needle')
  await expect(editor.locator('mark[data-search-match]')).toHaveText(['needle', 'needle'])
  await input.press('Enter')
  await expect(input).toBeFocused()
  await expect(editor.locator('p').first().locator('[data-search-current]')).toHaveText('needle')
  expect(await editorHtml(page)).toBe(original)
  await page.screenshot({ path: testInfo.outputPath('search-results.png') })
  await input.press('Enter')
  await expect(input).toBeFocused()
  await expect(editor.locator('p').last().locator('[data-search-current]')).toHaveText('needle')
  await expect(editor.locator('p').last().locator('[data-search-current]')).toBeInViewport({ ratio: 1 })
  await expect(input).toBeInViewport({ ratio: 1 })
  await search.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(editor.locator('p').first().locator('[data-search-current]')).toHaveText('needle')
  await expect(editor.locator('p').first().locator('[data-search-current]')).toBeInViewport({ ratio: 1 })
  await search.getByRole('button', { name: 'Next', exact: true }).click()
  const current = editor.locator('p').last().locator('[data-search-current]')
  await expect(current).toBeInViewport({ ratio: 1 })
  await expect.poll(() => current.evaluate(mark => {
    const root = mark.closest('.tiptap-galaris-editor')
    const toolbar = root.querySelector('.editorial-toolbar').getBoundingClientRect()
    const search = root.querySelector('.editorial-search-bar').getBoundingClientRect()
    return mark.getBoundingClientRect().top - Math.max(toolbar.bottom, search.bottom)
  })).toBeGreaterThanOrEqual(0)
  await page.screenshot({ path: testInfo.outputPath('search-scrolled.png') })
  await input.fill('missing')
  await expect(search.getByRole('status')).toHaveText('0')
  await expect(editor.locator('[data-search-match]')).toHaveCount(0)
  await expect(search.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
  await command(page, 'Find')
  await expect(search).toBeHidden()
  await expect(editor).toBeFocused()
  await command(page, 'Find')
  await expect(input).toHaveValue('missing')
  await editor.focus()
  await editor.press('Control+f')
  await expect(input).toBeFocused()
  await input.fill('needle')
  await expect(editor.locator('[data-search-match]')).toHaveCount(2)
  await command(page, 'Find')
  await expect(search).toBeHidden()
  await expect(editor.locator('[data-search-match]')).toHaveCount(0)
  await command(page, 'Fullscreen')
  await command(page, 'Find')
  await expect(input).toHaveValue('needle')
  await input.press('Enter')
  await expect(editor.locator('[data-search-current]')).toBeInViewport({ ratio: 1 })
  await input.press('Escape')
  await expect(search).toBeHidden()
  await expect(editor).toBeFocused()
  await expect(page.locator('.editorial-fullscreen')).toHaveCount(1)
  await editor.press('Escape')
  await expect(page.locator('.editorial-fullscreen')).toHaveCount(0)
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})

for (const [profile, width] of [['rich-text', 1024], ['rich-text', 390], ['document', 1024], ['document', 390]]) {
test(`native find and replace remains usable for ${profile} at ${width}px`, async ({page}, testInfo)=>{
  await page.setViewportSize({width,height:844})
  await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile,modelValue:'<p>Find <strong>me</strong></p>',ariaLabel:'Editorial content'},dark:true})
  await page.locator('[data-editor-surface]').click()
  await page.keyboard.press('Control+f')
  await expect(page.getByRole('search', { name: 'Find', exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', {name:'Find',exact:true})).toBeFocused()
  await page.getByRole('textbox', {name:'Find',exact:true}).fill('Find')
  await page.getByRole('textbox', {name:'Find',exact:true}).press('Enter')
  await page.getByRole('textbox', {name:'Replace',exact:true}).fill('Found')
  await page.getByRole('button', {name:'Replace',exact:true}).click()
  await expect(page.locator('[data-editor-surface]')).toContainText('Found me')
  expect(await lastValue(page)).toBe('<p>Found <strong>me</strong></p>')
  await page.getByRole('textbox', {name:'Find',exact:true}).fill('Found me')
  await page.getByRole('button', {name:'Next',exact:true}).click()
  await page.getByRole('textbox', {name:'Replace',exact:true}).fill('Whole match')
  await page.getByRole('button', {name:'Replace',exact:true}).click()
  expect(await lastValue(page)).toBe('<p>Whole match</p>')
  await page.getByRole('textbox', {name:'Find',exact:true}).press('Control+f')
  await expect(page.getByRole('textbox', {name:'Find',exact:true})).toBeFocused()
  await page.getByRole('textbox', {name:'Find',exact:true}).press('Escape')
  await expect(page.locator('[data-editor-surface]')).toBeFocused()
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Blue blue blueberry <strong>BLUE</strong></p>' }))
  await command(page,'Find')
  await page.getByRole('textbox', {name:'Find',exact:true}).fill('blue')
  await page.getByRole('checkbox', {name:'Match case',exact:true}).check()
  await page.getByRole('checkbox', {name:'Whole words only',exact:true}).check()
  await page.getByRole('textbox', {name:'Replace',exact:true}).fill('green')
  await page.getByRole('button', {name:'Replace all',exact:true}).click()
  expect(await lastValue(page)).toBe('<p>Blue green blueberry <strong>BLUE</strong></p>')
  await page.getByRole('checkbox', {name:'Match case',exact:true}).uncheck()
  await page.getByRole('button', {name:'Replace all',exact:true}).click()
  await expect(page.locator('[data-editor-surface]')).toHaveText('green green blueberry green')
  await page.screenshot({path:testInfo.outputPath('native-search.png')})
  await page.getByRole('button', {name:'Close',exact:true}).click()
  await expect(page.locator('[data-editor-surface]')).toBeFocused()
  await command(page,'Find')
  await expect(page.getByRole('textbox', {name:'Find',exact:true})).toHaveValue('blue')
})
}

test('native link form accepts focus inside a Quasar dialog and the backdrop stays dismissible', async ({page}) => {
  await jsonRoute(page, '**/api/agents**', [])
  await mount(page, 'app/task/components/TaskFormDialog.vue', {props:{modelValue:true}, privileges:['TASK_EDIT']})
  const editable = page.locator('[data-editor-surface]')
  await editable.fill('Example')
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Control+k')
  const input = page.getByRole('textbox', {name:'URL or Galaris reference',exact:true})
  await input.fill('https://example.com')
  await expect(input).toBeFocused()
  await page.getByRole('button', {name:'Apply',exact:true}).click()
  await expect(editable.locator('a')).toHaveAttribute('href','https://example.com')
  await page.locator('.q-dialog__backdrop').first().click({position:{x:3,y:3}})
  await expect.poll(()=>lastValue(page)).toBe(false)
})

for (const width of [1440, 390]) test(`changing profile reserves Source for rich-text and document tools for documents at ${width}px`, async ({page}) => {
  await page.setViewportSize({ width, height: 900 })
  await mount(page, 'core/util/components/RichTextEditor.vue', {props:{modelValue:'<p>Text remains</p>',profile:'document'}})
  await expect(page.locator('[data-editor-surface]')).toBeVisible()
  await expect(page.locator('input[type=file]').first()).toBeAttached()
  await expect(page.getByRole('button', {name:'Galaris link',exact:true})).toBeVisible()
  await expect(page.getByRole('button', {name:'Source',exact:true})).toHaveCount(0)
  await page.evaluate(()=>window.testApp.setProps({profile:'rich-text'}))
  await expect(page.locator('input[type=file]')).toHaveCount(0)
  await expect(page.locator('[data-editor-surface]')).toHaveText('Text remains')
  await expect(page.getByRole('button', {name:'Insert attachment',exact:true})).toHaveCount(0)
  if (width >= 1024) {
    await expect(page.getByRole('button', {name:'Source',exact:true})).toBeVisible()
    await expect(page.getByRole('button', {name:'Fullscreen', exact:true})).toBeVisible()
  }
  await expect(page.getByRole('button', {name:'Full width',exact:true})).toHaveCount(0)
  await expect(page.getByRole('button', {name:'Document images',exact:true})).toHaveCount(0)
  await command(page, 'Source')
  await expect(page.locator('.galaris-source-editing-area textarea')).toBeVisible()
  await page.evaluate(()=>window.testApp.setProps({profile:'document'}))
  await expect(page.getByRole('button', {name:'Source',exact:true})).toHaveCount(0)
  await expect(page.locator('.galaris-source-editing-area')).toHaveCount(0)
  await expect(page.locator('[data-editor-surface]')).toBeVisible()
  await expect(page.locator('[data-editor-surface]')).toHaveText('Text remains')
})
