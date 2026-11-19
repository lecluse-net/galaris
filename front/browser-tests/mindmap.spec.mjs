import { readFile } from 'node:fs/promises'
import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as fixture } from './data.mjs'

const mapEditor = 'app/document/mindmap/MindMapEditor.vue'
const savedMap = page => page.evaluate(() => JSON.parse(window.testApp.events.findLast(event => event.name === 'update:modelValue').value))

test('global replace preserves rich markup and undo restores the complete operation across folded branches', async ({ page }) => {
  const nodes = [
    { id: 'root', parent: null, title: 'Field survey' },
    { id: 'observations', parent: 'root', title: 'Observations' },
    { id: 'sample', parent: 'observations', title: 'Sample', note: 'Field station',
      body_html: '<p><strong>Field</strong> station near a <a href="https://example.org/field">field</a> site.</p>' },
  ]
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify({ version: 1, nodes }) } })
  const tree = page.getByRole('tree')
  const root = tree.getByRole('treeitem', { name: 'Field survey', exact: true })
  const sample = tree.getByRole('treeitem', { name: 'Sample', exact: true })
  await tree.getByRole('button', { name: 'Collapse Observations', exact: true }).click()
  await root.press('Control+a')
  await expect(page.getByText('3 nodes selected')).toBeVisible()
  await expect(sample).toHaveCount(0)
  await root.press('Control+f')
  const search = page.getByRole('search', { name: 'Find', exact: true })
  await search.getByRole('textbox', { name: 'Find', exact: true }).fill('field station')
  await expect(search.getByRole('status')).toHaveText('2')
  await search.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(sample).toHaveAttribute('aria-selected', 'true')
  await search.getByRole('textbox', { name: 'Replace', exact: true }).fill('Research base')
  await search.getByRole('button', { name: 'Replace all', exact: true }).click()
  const replaced = (await savedMap(page)).nodes[2]
  expect(replaced.note).toBe('Research base')
  expect(replaced.body_html).toBe('<p><strong>Research base</strong> near a <a href="https://example.org/field">field</a> site.</p>')
  await search.getByRole('button', { name: 'Close', exact: true }).click()
  await sample.press('Control+z')
  expect((await savedMap(page)).nodes).toEqual(nodes)
  await sample.press('Control+Shift+z')
  expect((await savedMap(page)).nodes[2]).toEqual(replaced)
  await sample.press('Delete')
  await page.getByRole('alert').getByRole('button', { name: 'Delete branch', exact: true }).click()
  await expect(sample).toHaveCount(0)
  const editing = page.getByRole('group', { name: 'Editing', exact: true })
  await editing.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(sample).toBeVisible()
  expect((await savedMap(page)).nodes[2]).toEqual(replaced)
})

test('image export and print include a folded branch and its attachment without opening it', async ({ page, browserName }, testInfo) => {
  await page.addInitScript(() => { window.print = () => { window.printCalls = (window.printCalls ?? 0) + 1 } })
  const title = 'Expedition'
  const uri = 'document://00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002'
  const modelValue = JSON.stringify({ version: 1, nodes: [
    { id: 'root', parent: null, title },
    { id: 'survey', parent: 'root', title: 'Survey' },
    { id: 'sample', parent: 'survey', title: '', checked: true, note: 'Folded branch notes', body_html: `<figure class="image"><img src="${uri}" alt="Field sample" width="24" height="24"></figure>` },
  ] })
  await mount(page, mapEditor, { props: { modelValue, documentTitle: title, readonly: true } })
  await page.evaluate(() => window.testApp.setProps({
    resolveImage: () => new Promise(resolve => {
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = 24
      const surface = canvas.getContext('2d')
      surface.fillStyle = '#e619bc'
      surface.fillRect(0, 0, 24, 24)
      canvas.toBlob(resolve, 'image/png')
    }),
  }))
  const survey = page.getByRole('treeitem', { name: 'Survey', exact: true })
  await survey.getByRole('button', { name: 'Collapse Survey', exact: true }).click()
  const tools = page.getByRole('group', { name: 'Export', exact: true })
  const download = page.waitForEvent('download', { timeout: 12_000 })
  await tools.getByRole('button', { name: 'Export as PNG', exact: true }).click()
  const image = await download
  expect(image.suggestedFilename()).toBe(`${title}.png`)
  const path = testInfo.outputPath('mindmap.png')
  await image.saveAs(path)
  const png = await readFile(path)
  expect(png.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
  expect(await page.evaluate(async data => {
    const image = new Image()
    image.src = 'data:image/png;base64,' + data
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight
    const surface = canvas.getContext('2d')
    surface.drawImage(image, 0, 0)
    const { data: pixels } = surface.getImageData(0, 0, canvas.width, canvas.height)
    return pixels.some((red, index) => index % 4 === 0 && red === 230 && pixels[index + 1] === 25 && pixels[index + 2] === 188)
  }, png.toString('base64'))).toBe(true)

  await tools.getByRole('button', { name: 'Print', exact: true }).click()
  const printed = page.frameLocator('.document-print-frame')
  await expect.poll(() => page.evaluate(() => document.querySelector('.document-print-frame')?.contentWindow?.printCalls)).toBe(1)
  await expect(printed.locator('body')).toContainText('Folded branch notes')
  await expect(printed.locator('body')).toContainText('☑')
  await expect(printed.getByAltText('Field sample')).toHaveJSProperty('naturalWidth', 24)
  await expect(printed.locator('button, iframe, [contenteditable]')).toHaveCount(0)
  if (browserName === 'webkit') await tools.getByText('Export', { exact: true }).click()
  else await page.locator('.document-print-frame').evaluate(frame => frame.contentWindow.dispatchEvent(new Event('afterprint')))
  await expect(page.locator('.document-print-frame')).toHaveCount(0)
  await expect(tools.getByRole('button', { name: 'Print', exact: true })).toBeEnabled()
  await expect(survey).toHaveAttribute('aria-expanded', 'false')
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})

test('a map theme and background can be previewed, saved and reopened with the same branches', async ({ page }) => {
  const nodes = [
    { id: 'root', parent: null, title: 'Outline' },
    { id: 'survey', parent: 'root', title: 'Survey', checked: true, body_html: '<p>Field notes</p>' },
  ]
  const modelValue = JSON.stringify({ version: 1, nodes, theme: { id: 'future-palette', version: 2 } })
  await mount(page, mapEditor, { props: { modelValue } })
  const appearance = page.getByRole('group', { name: 'Appearance', exact: true })
  const open = appearance.getByRole('button', { name: 'Map themes', exact: true })
  const dialog = page.getByRole('dialog', { name: 'Map themes', exact: true })
  const colorButton = appearance.getByRole('button', { name: 'Background color', exact: true })
  const colorDialog = page.getByRole('dialog', { name: 'Background color', exact: true })
  const colorInput = colorDialog.getByRole('textbox')
  const chooseBackground = async hex => {
    await colorButton.click()
    await colorInput.fill(hex)
    await colorInput.press('Tab')
  }
  await open.click()
  await expect(dialog.getByRole('radio', { name: 'Solaire', checked: true })).toBeVisible()
  await dialog.getByRole('radio', { name: 'Forest' }).click()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toBeHidden()
  await chooseBackground('#14392a')
  await colorDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(colorDialog).toBeHidden()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])

  await chooseBackground('#264851')
  await colorDialog.getByRole('button', { name: 'Apply', exact: true }).click()
  expect(await savedMap(page)).toEqual({ version: 1, nodes, theme: { id: 'future-palette', version: 2 }, background_color: '#264851' })
  await open.click()
  await dialog.getByRole('radio', { name: 'Ocean' }).click()
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  const saved = await savedMap(page)
  expect(saved).toEqual({ version: 1, nodes, theme: { id: 'ocean', version: 1 }, background_color: '#264851' })
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify(saved) } })
  await open.click()
  await expect(dialog.getByRole('radio', { name: 'Ocean', checked: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await colorButton.click()
  await expect(colorInput).toHaveValue('#264851')
  await colorDialog.getByRole('button', { name: 'Default background', exact: true }).click()
  await colorDialog.getByRole('button', { name: 'Apply', exact: true }).click()
  expect(await savedMap(page)).toEqual({ version: 1, nodes, theme: { id: 'ocean', version: 1 } })
})

test('fullscreen keeps the map and its controls usable without changing its source', async ({ page }) => {
  const modelValue = JSON.stringify({ version: 1, nodes: [
    { id: 'root', parent: null, title: 'Outline' },
    { id: 'survey', parent: 'root', title: 'Survey', checked: true },
  ] })
  await mount(page, mapEditor, { props: { modelValue } })
  const view = page.getByRole('group', { name: 'View', exact: true })
  const enter = view.getByRole('button', { name: 'Enter fullscreen', exact: true })
  const exit = view.getByRole('button', { name: 'Exit fullscreen', exact: true })
  await enter.click()
  await expect(exit).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('checkbox', { name: 'Checkbox for Survey' })).toBeChecked()
  await view.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect(view.getByRole('button', { name: 'Reset to 100%', exact: true })).toHaveText('120%')
  await page.getByRole('treeitem', { name: 'Survey', exact: true }).press('Escape')
  await expect(enter).toHaveAttribute('aria-pressed', 'false')
  await expect(view.getByRole('button', { name: 'Reset to 100%', exact: true })).toHaveText('120%')
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
})

test('checkbox state persists and only a new sibling inherits an empty box', async ({ page }) => {
  const modelValue = JSON.stringify({ version: 1, nodes: [
    { id: 'root', parent: null, title: 'Outline' },
    { id: 'survey', parent: 'root', title: 'Survey' },
  ] })
  await mount(page, mapEditor, { props: { modelValue } })
  const survey = page.getByRole('treeitem', { name: 'Survey', exact: true })
  const label = page.getByRole('textbox', { name: 'Branch title' })
  const box = name => page.getByRole('checkbox', { name: `Checkbox for ${name}`, exact: true })
  await survey.focus()
  await page.getByRole('button', { name: 'Add checkbox', exact: true }).click()
  await expect(box('Survey')).not.toBeChecked()
  await box('Survey').click()
  await expect(box('Survey')).toBeChecked()
  await survey.press('Space')
  await expect(box('Survey')).not.toBeChecked()

  await survey.press('Enter')
  await label.press('End')
  await label.press('Space')
  await page.keyboard.insertText('today')
  await label.press('Enter')
  const renamed = page.getByRole('treeitem', { name: 'Survey today', exact: true })
  await expect(renamed).toBeFocused()
  await expect(box('Survey today')).not.toBeChecked()
  await renamed.press('Space')
  await renamed.press('Shift+Enter')
  await expect(label).toBeFocused()
  await page.keyboard.insertText('Review')
  await label.press('Enter')
  await expect(box('Review')).not.toBeChecked()

  await renamed.press('Tab')
  await expect(label).toBeFocused()
  await page.keyboard.insertText('Sample')
  await label.press('Enter')
  await expect(box('Sample')).toHaveCount(0)
  await page.getByRole('button', { name: 'Add sibling branch', exact: true }).click()
  await expect(label).toBeFocused()
  await page.keyboard.insertText('Report')
  await label.press('Enter')
  await expect(box('Report')).toHaveCount(0)

  await page.getByRole('treeitem', { name: 'Review', exact: true }).press('Alt+Enter')
  const content = page.getByRole('textbox', { name: 'Edit node content' })
  await expect(content).toBeFocused()
  await content.press('Space')
  await page.keyboard.insertText('notes')
  await expect(content).toHaveText('Review notes')
  await content.press('Escape')
  await expect(box('Review')).not.toBeChecked()

  const saved = await savedMap(page)
  expect(saved.nodes.filter(node => node.parent === 'root').map(({ title, checked }) => [title, checked])).toEqual([
    ['Survey today', true], ['Review', false],
  ])
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify(saved), readonly: true } })
  await expect(box('Survey today')).toBeChecked()
  await expect(box('Review')).not.toBeChecked()
  await expect(box('Review')).toBeDisabled()
  await expect(box('Sample')).toHaveCount(0)
})

test('a keyboard selection supports batch changes and keeps descendants with their branch', async ({ page }) => {
  const modelValue = JSON.stringify({ version: 1, nodes: [
    { id: 'root', parent: null, title: 'Outline' },
    { id: 'collect', parent: 'root', title: 'Collect' },
    { id: 'sample', parent: 'collect', title: 'Sample' },
    { id: 'review', parent: 'root', title: 'Review', checked: true },
    { id: 'destination', parent: 'root', title: 'Destination' },
  ] })
  await mount(page, mapEditor, { props: { modelValue } })
  const branch = name => page.getByRole('treeitem', { name, exact: true })
  const destination = branch('Destination')
  const button = name => page.getByRole('button', { name, exact: true })
  const mapHelp = page.getByRole('dialog', { name: 'Mind map shortcuts' })
  await button('Keyboard help').click()
  await expect(mapHelp.getByText('Check or uncheck outside editing')).toBeVisible()
  await expect(mapHelp.getByText('Extend or shrink the selection')).toBeVisible()
  await mapHelp.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(mapHelp).toBeHidden()

  await branch('Collect').press('Shift+ArrowDown')
  await branch('Sample').press('Shift+ArrowDown')
  await expect(page.getByRole('treeitem', { selected: true })).toHaveCount(3)
  await branch('Review').press('Shift+ArrowUp')
  await expect(page.getByRole('treeitem', { selected: true })).toHaveCount(2)
  await branch('Sample').press('Shift+ArrowDown')
  await button('Add checkbox').click()
  await expect(page.getByRole('checkbox')).toHaveCount(3)
  await expect(page.getByRole('checkbox', { name: 'Checkbox for Review' })).toBeChecked()
  await button('Remove checkbox').click()
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await button('Add checkbox').click()
  await branch('Review').press('Control+c')
  await destination.press('Control+v')
  const copied = (await savedMap(page)).nodes.filter(node => node.parent === 'destination')
  expect(copied.map(({ title, checked }) => [title, checked])).toEqual([['Collect', false], ['Review', false]])
  const copiedChild = (await savedMap(page)).nodes.filter(node => node.parent === copied[0].id)
  expect(copiedChild.map(node => node.title)).toEqual(['Sample'])

  await destination.getByRole('treeitem', { name: 'Review', exact: true }).press('Control+x')
  expect((await savedMap(page)).nodes.filter(node => node.parent === 'destination')).toHaveLength(2)
  await branch('Outline').press('Control+v')
  expect((await savedMap(page)).nodes.filter(node => node.parent === 'destination')).toHaveLength(0)
  await button('Move branch up').click()
  expect((await savedMap(page)).nodes.filter(node => node.parent === 'root').map(node => node.id)).toEqual([
    'collect', 'review', copied[0].id, copied[1].id, 'destination',
  ])
  await button('Change parent branch').click()
  await page.getByRole('combobox', { name: 'Parent branch', exact: true }).click()
  await page.getByRole('option', { name: 'Destination', exact: true }).click()
  expect((await savedMap(page)).nodes.filter(node => node.parent === 'destination').map(node => node.id)).toEqual(copied.map(node => node.id))

  await button('Delete selected branches').click()
  await page.getByRole('alert').getByRole('button', { name: 'Delete selected branches' }).click()
  expect((await savedMap(page)).nodes.map(node => node.id).sort()).toEqual(['collect', 'destination', 'review', 'root', 'sample'])
})

test('modifier clicks select ranges or individual nodes and leave text selection to editing', async ({ page }) => {
  const nodes = [
    { id: 'root', parent: null, title: 'Outline' },
    { id: 'collect', parent: 'root', title: 'Collect' },
    { id: 'sample', parent: 'collect', title: 'Sample' },
    { id: 'review', parent: 'root', title: 'Review', body_html: '<p>Review the samples</p>' },
    { id: 'destination', parent: 'root', title: 'Destination' },
  ]
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify({ version: 1, nodes }) } })
  const branch = name => page.getByRole('treeitem', { name, exact: true })
  const text = (name, label = name) => branch(name).getByText(label, { exact: true })
  const selected = () => page.getByRole('treeitem', { selected: true }).evaluateAll(items => items.map(item => item.getAttribute('aria-label')))
  const dragAcrossText = async (locator) => {
    const box = await locator.boundingBox()
    const y = box.y + box.height / 2
    await page.mouse.move(box.x + 8, y)
    await page.mouse.down()
    await page.mouse.move(box.x + Math.min(box.width - 4, 88), y, { steps: 8 })
    await page.mouse.up()
  }

  await text('Collect').click()
  await text('Review', 'Review the samples').click({ modifiers: ['Shift'] })
  await expect.poll(selected).toEqual(['Collect', 'Sample', 'Review'])
  await text('Sample').click({ modifiers: ['Control'] })
  await expect.poll(selected).toEqual(['Collect', 'Review'])
  await text('Destination').click({ modifiers: ['Meta'] })
  await expect.poll(selected).toEqual(['Collect', 'Review', 'Destination'])
  await text('Destination').click({ modifiers: ['Control'] })
  await expect.poll(selected).toEqual(['Collect', 'Review'])
  await text('Collect').click()
  await expect.poll(selected).toEqual(['Collect'])
  await expect(page.getByRole('textbox', { name: 'Branch title' })).toHaveCount(0)

  const reviewText = text('Review', 'Review the samples')
  await dragAcrossText(reviewText)
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe('')
  await branch('Review').press('Alt+Enter')
  const editor = page.getByRole('textbox', { name: 'Edit node content', exact: true })
  await expect(editor).toBeFocused()
  await dragAcrossText(editor.getByText('Review the samples', { exact: true }))
  expect(await page.evaluate(() => window.getSelection()?.toString())).toContain('the')

  await mount(page, mapEditor, { props: { modelValue: JSON.stringify({ version: 1, nodes }), readonly: true } })
  await dragAcrossText(reviewText)
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe('')
})

test('dragging a selection reorders and reparents its branches as one edit', async ({ page }) => {
  const nodes = [
    { id: 'root', parent: null, title: 'Outline' },
    { id: 'collect', parent: 'root', title: 'Collect' },
    { id: 'sample', parent: 'collect', title: 'Sample', checked: true },
    { id: 'review', parent: 'root', title: 'Review', note: 'Review the samples' },
    { id: 'destination', parent: 'root', title: 'Destination' },
    { id: 'inbox', parent: 'destination', title: 'Inbox' },
    { id: 'archive', parent: 'root', title: 'Archive' },
  ]
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify({ version: 1, nodes }) } })
  const branch = name => page.getByRole('treeitem', { name, exact: true })
  const title = name => branch(name).getByText(name, { exact: true })
  const order = async parent => (await savedMap(page)).nodes.filter(node => node.parent === parent).map(node => node.id)
  await title('Collect').click()
  await title('Review').click({ modifiers: ['Shift'] })
  await title('Sample').click({ modifiers: ['Control'] })
  await expect(branch('Collect')).toHaveAttribute('aria-selected', 'true')
  await expect(branch('Sample')).toHaveAttribute('aria-selected', 'false')
  await expect(branch('Review')).toHaveAttribute('aria-selected', 'true')

  const archive = branch('Archive').locator(':scope > .mindmap-node')
  await title('Collect').dragTo(archive, { targetPosition: { x: 15, y: (await archive.boundingBox()).height - 3 } })
  expect(await order('root')).toEqual(['destination', 'archive', 'collect', 'review'])
  expect(await order('collect')).toEqual(['sample'])
  await expect(branch('Collect')).toHaveAttribute('aria-selected', 'true')
  await expect(branch('Review')).toHaveAttribute('aria-selected', 'true')
  await expect(branch('Sample')).toHaveAttribute('aria-selected', 'false')
  await title('Collect').dragTo(title('Sample'))
  expect(await order('root')).toEqual(['destination', 'archive', 'collect', 'review'])
  expect(await order('collect')).toEqual(['sample'])

  await title('Collect').dragTo(title('Destination'))
  expect(await order('destination')).toEqual(['inbox', 'collect', 'review'])
  expect((await savedMap(page)).nodes.find(node => node.id === 'sample')).toEqual(nodes[2])
  expect((await savedMap(page)).nodes.find(node => node.id === 'review')).toEqual({ ...nodes[3], parent: 'destination' })
  await page.keyboard.press('Control+z')
  expect(await order('root')).toEqual(['destination', 'archive', 'collect', 'review'])
  expect(await order('destination')).toEqual(['inbox'])
  await page.keyboard.press('Control+Shift+z')
  expect(await order('destination')).toEqual(['inbox', 'collect', 'review'])

  const inbox = branch('Inbox').locator(':scope > .mindmap-node')
  await title('Archive').dragTo(inbox, { targetPosition: { x: 15, y: 3 } })
  expect(await order('destination')).toEqual(['archive', 'inbox', 'collect', 'review'])
  const persisted = await savedMap(page)
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify(persisted), readonly: true } })
  const directChildren = branch('Destination').getByRole('group').first().locator(':scope > [role="treeitem"]')
  await expect(directChildren).toHaveCount(4)
  expect(await directChildren.evaluateAll(items => items.map(item => item.getAttribute('aria-label'))))
    .toEqual(['Archive', 'Inbox', 'Collect', 'Review'])
})

test('clipboard text and links create children outside editing and stay inline while editing', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  const nodes = [
    { id: 'root', parent: null, title: 'Outline' },
    { id: 'draft', parent: 'root', title: 'Draft', body_html: '<p>Context</p>' },
  ]
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify({ version: 1, nodes }) } })
  const writeClipboard = value => page.evaluate(text => navigator.clipboard.writeText(text), value)
  const branch = page.getByRole('treeitem', { name: 'Draft', exact: true })
  const children = async () => (await savedMap(page)).nodes.filter(node => node.parent === 'draft')
  await branch.press('Control+c')
  const url = 'https://example.org/report'
  await writeClipboard(`Measure\r\n\r\n${url}\nReview`)
  await branch.press('Control+v')
  expect((await children()).map(node => node.title)).toEqual(['Measure', '', url, 'Review'])
  await expect(branch.getByRole('link', { name: url })).toHaveAttribute('href', url)

  await writeClipboard('Send results')
  await page.getByRole('group', { name: 'Editing', exact: true }).getByRole('button', { name: 'Paste', exact: true }).click()
  await expect.poll(async () => (await children()).at(-1)?.title).toBe('Send results')
  await branch.press('Control+k')
  const linkDialog = page.getByRole('dialog', { name: 'Link', exact: true })
  await linkDialog.getByRole('textbox', { name: 'URL or Galaris reference' }).fill('www.example.org/appendix')
  await linkDialog.getByRole('textbox', { name: 'Link text' }).fill('Appendix')
  await linkDialog.getByRole('button', { name: 'Link', exact: true }).click()
  expect((await children()).at(-1)?.title).toBe('Appendix')
  await expect(branch.getByRole('link', { name: 'Appendix' })).toHaveAttribute('href', 'https://www.example.org/appendix')

  await branch.press('Alt+Enter')
  const editor = page.locator('[data-editor-surface]')
  await expect(editor).toBeFocused()
  await writeClipboard('Notes\nNext step')
  await editor.press('Control+v')
  await expect(editor).toContainText('Next step')
  expect(await children()).toHaveLength(6)
  expect((await savedMap(page)).nodes.find(node => node.id === 'draft').body_html).toContain('Next step')
})

test('an embedded process scrolls independently and keeps its preview when selected', async ({ page }) => {
  const uri = 'galaris://processes/synthetic_review'
  const title = 'Field review'
  let previewRequests = 0
  await page.route('**/api/processes/internal/resource-preview?*', route => {
    previewRequests++
    return route.fulfill({ json: { uri, process_uri: uri, kind: 'process', id: 'synthetic_review', title, description: '', revision: 1,
      graph: { schema_version: 'galaris.bpmn/v1', input_schema: {}, output_schema: {}, files: {}, actors: [], nodes: [
        { id: 'start', kind: 'start', title: 'Start', config: {}, x: 0, y: 0, body: null },
        { id: 'end', kind: 'end', title: 'Complete', config: {}, x: 1100, y: 2200, body: null },
      ], flows: [{ id: 'done', source: 'start', target: 'end' }] },
    } })
  })
  const modelValue = JSON.stringify({ version: 1, nodes: [
    { id: 'root', parent: null, title: 'Roadmap' },
    { id: 'review', parent: 'root', title, body_html: `<blockquote class="galaris-link-card" data-resource-mode="embed"><p><a href="${uri}">${title}</a></p></blockquote>` },
  ] })
  await mount(page, 'app/document/mindmap/MindMapEditor.vue', { props: { modelValue } })
  const diagram = page.getByRole('region', { name: 'BPMN process diagram' })
  await expect(diagram).toBeVisible()
  const viewport = diagram.locator('.bpmn-scroll')
  await expect.poll(() => viewport.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(0)
  await viewport.hover()
  await page.mouse.wheel(0, 170)
  await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeGreaterThan(0)
  await diagram.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect.poll(() => viewport.evaluate(el => el.scrollWidth - el.clientWidth)).toBeGreaterThan(0)
  await viewport.press('ArrowRight')
  await expect.poll(() => viewport.evaluate(el => el.scrollLeft)).toBeGreaterThan(0)
  await page.getByRole('link', { name: title, exact: true }).click()
  const toolbar = page.getByRole('toolbar', { name: 'Contextual actions' })
  await expect(toolbar.getByRole('button', { name: 'Fit the diagram', exact: true })).toBeVisible()
  await expect(toolbar.getByRole('button', { name: /Insert paragraph (before|after) block/ })).toHaveCount(0)
  await toolbar.getByRole('button', { name: 'Fit the diagram', exact: true }).click()
  await expect(diagram).toBeVisible()
  expect(previewRequests).toBe(1)
  const handle = page.getByRole('button', { name: 'Resize embedded content', exact: true })
  const original = await viewport.boundingBox()
  await handle.press('ArrowRight')
  await handle.press('ArrowDown')
  await expect.poll(async () => (await viewport.boundingBox()).width).toBeGreaterThan(original.width)
  await expect.poll(async () => (await viewport.boundingBox()).height).toBeGreaterThan(original.height)
  const body = async () => (await savedMap(page)).nodes[1].body_html
  const size = (await body()).match(/data-resource-size="(\d+x\d+)"/)[1]
  expect(previewRequests).toBe(1)
  await toolbar.getByRole('button', { name: 'Show card', exact: true }).click()
  await expect(diagram).toHaveCount(0)
  await toolbar.getByRole('button', { name: 'Show URL', exact: true }).click()
  await expect.poll(async () => (await savedMap(page)).nodes[1].body_html).toMatch(/^<p><a /)
  await expect(toolbar.getByRole('button', { name: 'Show card', exact: true })).toBeVisible()
  await toolbar.getByRole('button', { name: 'Show embedded content', exact: true }).click()
  await expect(diagram).toBeVisible()
  expect(await body()).toContain(`data-resource-size="${size}"`)
})

test('a mind map saves and restores the size of an embedded Text document', async ({ page }, testInfo) => {
  const id = '00000000-0000-4000-8000-000000000311'
  const title = 'Field handbook'
  const text = Array.from({ length: 56 }, (_, index) => `<p>Field instruction ${index + 1}</p>`).join('')
  await jsonRoute(page, new RegExp(`/api/documents/${id}(?:\\?|$)`), { item: {
    ...fixture, id, title, media_type: 'text/html', content_profile: 'document', format_version: 1, payload: { text },
  }, agent_id: 7 })
  const modelValue = JSON.stringify({ version: 1, nodes: [
    { id: 'root', parent: null, title: 'Manuals' },
    { id: 'handbook', parent: 'root', title, body_html: `<blockquote class="galaris-link-card" data-resource-mode="embed"><p><a href="document://${id}">${title}</a></p></blockquote>` },
  ] })
  await mount(page, mapEditor, { props: { modelValue } })
  const viewport = page.getByRole('region', { name: title, exact: true })
  await expect(viewport).toContainText('Field instruction 56')
  await expect.poll(() => viewport.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(0)
  await viewport.hover()
  await page.mouse.wheel(0, 170)
  await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeGreaterThan(0)

  const handle = page.getByRole('button', { name: 'Resize embedded content', exact: true })
  const initial = await viewport.boundingBox()
  await handle.press('ArrowLeft')
  await expect.poll(async () => (await viewport.boundingBox()).width).toBeLessThan(initial.width)
  await handle.press('ArrowRight')
  await expect.poll(async () => (await viewport.boundingBox()).width).toBeCloseTo(initial.width, 0)
  const bounds = await handle.boundingBox()
  const x = bounds.x + bounds.width / 2, y = bounds.y + bounds.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 160, y - 50, { steps: 5 })
  await page.mouse.up()
  await expect.poll(async () => (await viewport.boundingBox()).height).toBeLessThan(initial.height)
  await expect.poll(async () => (await viewport.boundingBox()).width).toBeCloseTo(initial.width + 160, 0)
  const resized = await viewport.boundingBox()
  const persisted = await savedMap(page)
  expect(persisted.nodes[1].body_html).toMatch(/data-resource-size="[1-9]\d*x[1-9]\d*"/)
  await page.screenshot({ path: testInfo.outputPath('embedded-text-resized.png') })
  await mount(page, mapEditor, { props: { modelValue: JSON.stringify(persisted), readonly: true } })
  await expect.poll(async () => (await viewport.boundingBox()).width).toBeCloseTo(resized.width, 0)
  await expect.poll(async () => (await viewport.boundingBox()).height).toBeCloseTo(resized.height, 0)
  await expect(handle).toHaveCount(0)
})

test('two embedded references to a mind map keep independent dimensions', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000313'
  const title = 'Survey diagram'
  const modelValue = JSON.stringify({ version: 1, nodes: [{ id: 'root', parent: null, title: 'Survey' }] })
  await jsonRoute(page, `**/api/documents/${id}`, { item: {
    ...fixture, id, title, document_format: 'mindmap', format_version: 1,
    media_type: 'application/vnd.galaris.mindmap+json', payload: { text: modelValue },
  }, agent_id: null })
  const reference = `<blockquote class="galaris-link-card" data-resource-mode="embed"><p><a href="document://${id}">${title}</a></p></blockquote>`
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: reference + reference } })
  const readers = page.getByRole('tree')
  await expect(readers).toHaveCount(2)
  const handle = page.getByRole('button', { name: 'Resize embedded content', exact: true }).first()
  await handle.press('ArrowLeft')
  await expect.poll(() => page.evaluate(() => {
    const saved = window.testApp.events.findLast(event => event.name === 'update:modelValue')?.value ?? ''
    const html = new DOMParser().parseFromString(saved, 'text/html')
    return [...html.querySelectorAll('blockquote')].map(card => Boolean(card.dataset.resourceSize))
  })).toEqual([true, false])
  await expect(readers).toHaveCount(2)
})

test('create a branch with the keyboard, reopen the saved map and export it', async ({ page, browserName }, testInfo) => {
  const mediaType = 'application/vnd.galaris.mindmap+json'
  const documentId = '00000000-0000-4000-8000-000000000301'
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=', 'base64')
  const widePng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAEklEQVR4AQEHAPj/ABRaeBRaeAWJAc2zhUtGAAAAAElFTkSuQmCC', 'base64')
  const attachment = { id: '00000000-0000-4000-8000-000000000302', name: 'sample.png', media_type: 'image/png', size_bytes: png.length }
  const local = { ...attachment, id: '00000000-0000-4000-8000-000000000303', name: 'survey.png' }
  const portraitUri = 'file://00000000-0000-4000-8000-000000000304'
  const webUrl = 'https://example.org/field-notes'
  const content = { version: 1, nodes: [
    { id: 'root', parent: null, title: 'Field notes' },
    { id: 'survey', parent: 'root', title: 'Site survey' },
    { id: 'water', parent: 'survey', title: 'Water samples' },
    { id: 'light', parent: 'survey', title: 'Light readings' },
    { id: 'schedule', parent: 'root', title: 'Schedule' },
  ] }
  let item = { ...fixture, id: documentId, title: 'Synthetic map', content_type: 'text', document_format: 'mindmap',
    format_version: 1, media_type: mediaType, payload: { text: JSON.stringify(content) } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await page.route(/\/api\/agents\/7(?:\?|$)/, route => route.fulfill({ json: agent }))
  let avatarRequests = 0
  await page.route(/\/api\/agents\/7\/avatar(?:\?|$)/, route => {
    avatarRequests++
    return route.fulfill({ contentType: 'image/png', body: widePng })
  })
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice' }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/tag-icons', [])
  let attachments = []
  await page.route(`**/api/documents/${documentId}/attachments?*`, route => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: attachments })
    const uploaded = [attachment, local].find(file => route.request().postData().includes(`filename="${file.name}"`))
    expect(uploaded).toBeTruthy()
    attachments.push(uploaded)
    return route.fulfill({ json: uploaded })
  })
  let localImageRequests = 0
  for (const file of [attachment, local]) {
    await page.route(`**/api/documents/${documentId}/attachments/${file.id}?*`, route => {
      if (file === local) localImageRequests++
      return route.fulfill({ contentType: 'image/png', body: png })
    })
    await page.route(`**/api/documents/${documentId}/attachments/${file.id}/thumbnail?*`, route => route.fulfill({ contentType: 'image/png', body: png }))
  }
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'file', label: 'Managed files', capabilities: ['list'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', {
    entries: [
      ...['index', 'summary'].map(name => ({ uri: `file://${name}`, name: `${name}.txt`, media_type: 'text/plain' })),
      { uri: portraitUri, name: 'portrait.png', media_type: 'image/png' },
      { uri: 'galaris://agent/7', name: 'Agent source', media_type: 'application/json' },
    ].map(entry => ({ ...entry, is_collection: false, size: 10, capabilities: ['read', 'info'] })), next_cursor: null, truncated: false,
  })
  await page.route('**/api/file-share/browser/thumbnail?*', route =>
    new URL(route.request().url()).searchParams.get('uri') === portraitUri
      ? route.fulfill({ contentType: 'image/png', body: widePng }) : route.fulfill({ status: 404 }))
  await page.route('**/api/file-share/browser/info?*', route =>
    new URL(route.request().url()).searchParams.get('uri') === portraitUri
      ? route.fulfill({ json: { uri: portraitUri, media_type: 'image/png', size: widePng.length } }) : route.fulfill({ status: 404 }))
  let portraitRequests = 0
  await page.route('**/api/file-share/browser/content?*', route => {
    if (new URL(route.request().url()).searchParams.get('uri') !== portraitUri) return route.fulfill({ status: 404 })
    portraitRequests++
    return route.fulfill({ contentType: 'image/png', body: widePng })
  })
  await jsonRoute(page, `**/api/documents/${documentId}/link-card?*`, {
    attachment: null,
    html: `<blockquote class="galaris-link-card"><p><a href="${webUrl}">Field guide</a></p></blockquote>`,
  })
  await jsonRoute(page, '**/api/documents/formats', [{
    code: 'mindmap', provider: 'galaris', version: 1, contract_version: 1, storage_kind: 'text',
    media_type: mediaType, icon: 'account_tree', qualification: 'not_run', import_extensions: ['.mm', '.opml', '.xmind'],
    capabilities: { editor: 'native', preview: 'native', native_export: 'native', import: 'native' },
  }])
  await page.route(new RegExp(`/api/documents/${documentId}(?:\\?|$)`), route => {
    if (route.request().method() === 'PATCH') {
      const update = route.request().postDataJSON()
      expect(update.expected_revision).toBe(item.revision)
      item = { ...item, revision: item.revision + 1, lock_version: item.lock_version + 1, payload: update.payload }
      return route.fulfill({ json: item })
    }
    return route.fulfill({ json: { item, agent_id: 7 } })
  })
  await page.route(`**/api/documents/${documentId}/source?*`, route => {
    const query = new URL(route.request().url()).searchParams
    expect(query.get('revision')).toBe(String(item.revision))
    expect(query.get('export_format')).toBe('opml')
    return route.fulfill({ contentType: 'application/x-opml+xml', body: '<opml version="2.0"/>' })
  })

  const component = 'app/document/components/DocumentEditor.vue'
  const props = { documentId: item.id, agentId: 7 }
  await page.setViewportSize({ width: 1440, height: 900 })
  await mount(page, component, { props, shell: true, privileges: ['DOCUMENT_EDIT', 'FILE_ACCESS'] })
  const root = page.getByRole('treeitem', { name: 'Field notes', exact: true })
  await root.press('Tab')
  const title = page.getByRole('textbox', { name: 'Branch title' })
  await expect(title).toBeFocused()
  await page.keyboard.insertText('Measurement')
  await expect(title).toHaveText('Measurement')
  await title.press('Enter')
  await expect.poll(() => JSON.parse(item.payload.text).nodes.at(-1)).toMatchObject({ parent: 'root', title: 'Measurement' })
  await page.getByText('Site survey', { exact: true }).click()
  await page.getByText('Measurement', { exact: true }).click()
  await expect(title).toHaveCount(0)
  await page.getByText('Measurement', { exact: true }).click()
  await expect(title).toBeFocused()
  await page.keyboard.insertText('s')
  await page.getByText('Site survey', { exact: true }).click()
  await expect(title).toHaveCount(0)
  await expect.poll(() => JSON.parse(item.payload.text).nodes.at(-1)?.title).toBe('Measurements')
  const measurements = page.getByRole('treeitem', { name: 'Measurements', exact: true })
  await measurements.press('F2')
  await expect(title).toBeFocused()
  await page.keyboard.insertText('!')
  await expect(title).toHaveText('Measurements!')
  await title.press('Escape')
  await expect(measurements).toBeFocused()
  await measurements.press('Shift+Enter')
  await expect(title).toBeFocused()
  await expect(title).toBeEmpty()
  await title.press('Enter')
  await expect.poll(() => JSON.parse(item.payload.text).nodes.at(-1)?.title).toBe('')
  const untitled = page.getByRole('treeitem', { name: 'Untitled', exact: true })
  const emptyLabel = untitled.locator('.mindmap-label')
  await expect(emptyLabel).toBeEmpty()
  await emptyLabel.click()
  await expect(title).toBeFocused()
  await expect(title).toBeEmpty()
  await title.press('Escape')
  await untitled.press('Shift+R')
  await expect(title).toBeFocused()
  await expect(title).toHaveText('R')
  await page.keyboard.insertText('eview')
  await title.press('Enter')
  await expect.poll(() => JSON.parse(item.payload.text).nodes.at(-1)?.title).toBe('Review')
  const revision = item.revision
  const water = page.getByRole('treeitem', { name: 'Water samples', exact: true })
  await page.getByText('Site survey', { exact: true }).click()
  await page.keyboard.press('Space')
  await expect(water).toHaveCount(0)
  await page.keyboard.press('ArrowRight')
  await expect(water).toBeFocused()
  await expect(title).toHaveCount(0)
  await page.keyboard.press('7')
  await expect(title).toBeFocused()
  await expect(title).toHaveText('Water samples7')
  await title.press('Escape')
  expect(item.revision).toBe(revision)
  await water.press('F3')
  const note = page.getByRole('textbox', { name: 'Note', exact: true })
  await note.fill('Collect at the inlet.')
  await note.press('Enter')
  await expect(page.getByText('Collect at the inlet.', { exact: true })).toBeVisible()
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === 'water')?.note).toBe('Collect at the inlet.')
  await water.press('F3')
  await expect(note).toBeFocused()
  await page.keyboard.insertText(' Bring a jar.')
  await expect(note).toHaveValue('Collect at the inlet. Bring a jar.')
  await note.press('Escape')
  await water.press('Escape')
  await page.keyboard.press('Tab')
  await expect(water).not.toBeFocused()
  await expect(title).toHaveCount(0)
  const measurementsId = JSON.parse(item.payload.text).nodes.find(node => node.title === 'Measurements').id
  await page.getByText('Measurements', { exact: true }).dragTo(page.getByText('Site survey', { exact: true }))
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === measurementsId)?.parent).toBe('survey')
  const canvas = page.locator('.mindmap-canvas')
  const bounds = await canvas.boundingBox()
  const empty = { x: bounds.x + bounds.width - 60, y: bounds.y + bounds.height - 50 }
  const cameraRevision = item.revision
  const scrollPosition = () => canvas.evaluate(element => element.scrollLeft)
  const horizontalBar = page.getByRole('slider', { name: 'Scroll map horizontally' })
  await expect(horizontalBar).toBeInViewport()
  const sliderOrigin = await scrollPosition()
  await horizontalBar.press('ArrowRight')
  await expect.poll(scrollPosition).toBe(sliderOrigin + 1)
  const wheelOrigin = await scrollPosition()
  await page.mouse.move(empty.x, empty.y)
  await page.mouse.wheel(80, 0)
  await expect.poll(scrollPosition).toBe(wheelOrigin + 80)
  await expect(horizontalBar).toHaveValue(String(wheelOrigin + 80))
  await page.mouse.wheel(-80, 0)
  await expect.poll(scrollPosition).toEqual(wheelOrigin)
  const original = await root.boundingBox()
  await page.mouse.down()
  await page.mouse.move(empty.x - 70, empty.y - 45, { steps: 4 })
  await page.mouse.up()
  await expect.poll(async () => (await root.boundingBox()).x).toBeLessThan(original.x - 50)
  await expect.poll(async () => (await scrollPosition()) - wheelOrigin).toBeGreaterThan(60)
  await page.keyboard.down('Control')
  await page.mouse.wheel(0, -220)
  await page.keyboard.up('Control')
  await expect(page.getByRole('button', { name: 'Reset to 100%', exact: true })).not.toHaveText('100%')
  await page.getByRole('button', { name: 'Reset to 100%', exact: true }).click()
  expect(item.revision).toBe(cameraRevision)

  await measurements.press('F2')
  await title.press('Escape')
  await page.getByRole('button', { name: 'Node icon', exact: true }).click()
  const iconSearch = page.getByLabel('Search icons', { exact: true })
  await iconSearch.fill('rocket')
  await page.getByRole('button', { name: 'Rocket', exact: true }).click()
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === measurementsId)?.icon).toBe('emoji:1F680')

  const toolbar = page.getByRole('toolbar', { name: 'Mind map', exact: true })
  const editTools = page.getByRole('toolbar', { name: 'Content', exact: true })
  const contextTools = page.getByRole('toolbar', { name: 'Contextual actions', exact: true })
  async function chooseManagedFiles(trigger, ...names) {
    await trigger.click()
    await page.getByRole('button', { name: 'Open Managed files', exact: true }).click()
    for (const name of names) await page.getByRole('button', { name: `Select ${name}`, exact: true }).click()
    await page.getByRole('button', { name: 'Select', exact: true }).click()
  }
  await page.getByText('Site survey', { exact: true }).click()
  await toolbar.getByRole('button', { name: 'Link', exact: true }).click()
  const linkDialog = page.getByRole('dialog', { name: 'Link', exact: true })
  await linkDialog.getByRole('textbox', { name: 'URL or Galaris reference' }).fill(webUrl)
  await linkDialog.getByRole('button', { name: 'Link', exact: true }).click()
  const linkBranch = page.getByRole('treeitem', { name: 'Site survey', exact: true }).getByRole('treeitem', { name: webUrl, exact: true })
  const plainLink = linkBranch.getByRole('link', { name: webUrl, exact: true })
  await expect(plainLink).toHaveAttribute('href', webUrl)
  await plainLink.click()
  await expect(contextTools.getByRole('button', { name: 'Open', exact: true })).toBeVisible()
  expect(page.context().pages()).toEqual([page])
  const bold = editTools.getByRole('button', { name: 'Bold', exact: true })
  await expect(bold).toHaveCount(0)
  await toolbar.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(linkBranch).toHaveCount(0)
  await page.getByText('Site survey', { exact: true }).click()
  await measurements.press('Alt+Enter')
  const body = measurements.locator('[data-editor-surface]')
  await expect(body).toBeFocused()
  await expect(body).toHaveText('Measurements')
  await expect(toolbar).toBeHidden()
  await expect(editTools.getByRole('button', { name: 'Full width', exact: true })).toHaveCount(0)
  await expect(body).not.toHaveAttribute('data-document-layout', /.+/)
  await page.keyboard.insertText('!')
  await expect(body).toHaveText('Measurements!')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await body.fill('Rich evidence')
  await body.press('Control+a')
  await bold.click()
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === measurementsId)?.body_html).toContain('<strong>Rich evidence</strong>')
  await body.press('Control+a')
  await editTools.getByRole('button', { name: 'Font size', exact: true }).click()
  await page.getByRole('menuitemradio', { name: '24', exact: true }).click()
  const evidence = body.getByText('Rich evidence', { exact: true })
  await expect(evidence).toHaveCSS('font-size', '24px')
  await body.press('Control+z')
  await expect(evidence).not.toHaveCSS('font-size', '24px')
  await body.press('Control+Shift+z')
  await expect(evidence).toHaveCSS('font-size', '24px')
  await body.press('End')
  await editTools.getByRole('button', { name: 'Insert an emoji', exact: true }).click()
  const emojiSearch = page.getByRole('textbox', { name: 'Search emojis', exact: true })
  await expect(emojiSearch).toBeFocused()
  await emojiSearch.fill('rocket')
  await page.getByRole('button', { name: 'Rocket', exact: true }).click()
  await expect(body).toContainText('🚀')
  await body.press('Control+z')
  await expect(body).not.toContainText('🚀')
  await body.press('End')
  await body.press('Enter')
  const underline = editTools.getByRole('button', { name: 'Underline', exact: true })
  await underline.click()
  await page.keyboard.insertText('Underlined note')
  await expect(body.locator('u', { hasText: 'Underlined note' })).toHaveCSS('text-decoration-line', 'underline')
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === measurementsId)?.body_html).toContain('<u>Underlined note</u>')
  await page.keyboard.press('Shift+Home')
  await editTools.getByRole('button', { name: 'Italic', exact: true }).click()
  await expect(body.locator('u em, em u', { hasText: 'Underlined note' })).toHaveCSS('font-style', 'italic')
  await body.press('End')
  await body.press('Enter')
  await editTools.getByRole('button', { name: 'Bullet list', exact: true }).click()
  await page.keyboard.insertText('Check the sample')
  await body.press('Enter')
  await body.press('Enter')
  await editTools.getByRole('button', { name: 'Insert table', exact: true }).click()
  await expect(body.locator('table')).toBeVisible()
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === measurementsId)?.body_html).toContain('<table')
  await body.getByText('Rich evidence', { exact: true }).click()
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await body.evaluate((element, url) => {
    const clipboardData = new DataTransfer()
    clipboardData.setData('text/plain', url)
    element.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData }))
  }, webUrl)
  await body.getByRole('link', { name: webUrl, exact: true }).click()
  await contextTools.getByRole('button', { name: 'Show card', exact: true }).click()
  await expect(body.locator('blockquote').getByRole('link', { name: 'Field guide' })).toHaveAttribute('href', webUrl)
  await page.screenshot({ path: testInfo.outputPath('mindmap-node-toolbar.png'), animations: 'disabled' })
  await page.getByText('Site survey', { exact: true }).click()
  await expect(bold).toHaveCount(0)
  await expect(page.locator('.mindmap-node strong', { hasText: 'Rich evidence' })).toBeVisible()
  await expect(measurements.getByText('Measurements', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('mindmap-desktop.png'), animations: 'disabled' })
  await measurements.getByText('Rich evidence', { exact: true }).click()
  await expect(body).toHaveCount(0)
  await measurements.press('3')
  await expect(body.locator('table')).toBeVisible()
  await expect(body.getByText('3', { exact: true })).toBeVisible()
  await expect(body).toBeFocused()
  await body.press('Control+z')
  await expect(body.getByText('3', { exact: true })).toHaveCount(0)
  await body.getByText('Rich evidence', { exact: true }).click()
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  const filePicker = page.waitForEvent('filechooser')
  await editTools.getByRole('button', { name: 'Insert attachment', exact: true }).click()
  const picker = await filePicker
  await picker.setFiles({ name: 'sample.png', mimeType: 'image/png', buffer: png })
  await expect(body.getByRole('img', { name: attachment.name })).toHaveJSProperty('naturalWidth', 1)
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === measurementsId)?.body_html).toContain(`/attachments/${attachment.id}`)
  expect(JSON.parse(item.payload.text).nodes.some(node => node.parent === measurementsId)).toBe(false)
  await page.route(`**/api/documents/${documentId}/export-pdf`, route => {
    expect(route.request().postDataJSON().html).toContain('<strong>Rich evidence</strong>')
    return route.fulfill({ contentType: 'application/pdf', body: '%PDF-Synthetic snapshot' })
  })
  await body.press('Escape')
  await expect(measurements).toBeFocused()
  await expect(toolbar).toBeVisible()
  const pdf = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export PDF', exact: true }).click()
  expect((await pdf).suggestedFilename()).toBe('Synthetic map.pdf')

  await page.getByText('Schedule', { exact: true }).click()
  const localPicker = page.waitForEvent('filechooser')
  await toolbar.getByRole('button', { name: 'Insert file', exact: true }).click()
  await (await localPicker).setFiles({ name: local.name, mimeType: 'image/png', buffer: png })
  const childImage = page.getByRole('treeitem', { name: local.name, exact: true }).getByRole('img', { name: local.name })
  await expect(childImage).toHaveJSProperty('naturalWidth', 1)
  const loadedLocalImageRequests = localImageRequests
  await childImage.click()
  await expect(contextTools.getByRole('button', { name: 'Open', exact: true })).toBeVisible()
  await expect(childImage).toHaveJSProperty('naturalWidth', 1)
  expect(localImageRequests).toBe(loadedLocalImageRequests)
  expect(page.context().pages()).toEqual([page])
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.title === local.name)).toMatchObject({ parent: 'schedule' })
  expect(JSON.parse(item.payload.text).nodes.find(node => node.id === 'schedule').body_html).toBeUndefined()
  await page.getByText('Schedule', { exact: true }).click()
  await chooseManagedFiles(toolbar.getByRole('button', { name: 'Galaris', exact: true }), 'index.txt', 'summary.txt', 'portrait.png', 'Agent source')
  await expect.poll(() => JSON.parse(item.payload.text).nodes.filter(node => node.parent === 'schedule').map(node => node.title)).toEqual([local.name, 'index.txt', 'summary.txt', 'portrait.png', 'Alice Example'])
  const agentBranch = page.getByRole('treeitem', { name: 'Alice Example', exact: true })
  const agentLink = agentBranch.getByRole('link', { name: 'Alice Example', exact: true })
  const agentAvatar = agentBranch.getByRole('img', { name: 'Alice Example' })
  await expect(agentAvatar).toHaveJSProperty('naturalWidth', 2)
  const loadedAvatarRequests = avatarRequests
  await agentLink.click()
  await expect(contextTools.getByRole('button', { name: 'Show URL', exact: true })).toBeVisible()
  await expect(agentAvatar).toHaveJSProperty('naturalWidth', 2)
  expect(avatarRequests).toBe(loadedAvatarRequests)
  const portraitBranch = page.getByRole('treeitem', { name: 'portrait.png', exact: true })
  const portrait = portraitBranch.getByRole('img', { name: 'portrait.png' })
  await expect(portrait).toHaveJSProperty('naturalWidth', 2)
  const loadedPortraitRequests = portraitRequests
  await portrait.click({ delay: 50 })
  await expect(portrait).toHaveJSProperty('naturalWidth', 2)
  const handle = portraitBranch.locator('.galaris-image-resize')
  await expect(handle).toBeVisible()
  expect(portraitRequests).toBe(loadedPortraitRequests)
  await handle.scrollIntoViewIfNeeded()
  const beforeResize = await portrait.boundingBox()
  const knob = await handle.boundingBox()
  const x = knob.x + knob.width / 2, y = knob.y + knob.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 88, y, { steps: 4 })
  await page.mouse.up()
  const portraitBody = () => JSON.parse(item.payload.text).nodes.find(node => node.title === 'portrait.png')?.body_html
  await expect.poll(portraitBody).toMatch(/width:\s*[\d.]+px/)
  expect(decodeURIComponent(portraitBody())).toContain(portraitUri)
  const resized = await portrait.boundingBox()
  expect(resized.width).toBeGreaterThan(beforeResize.width + 40)
  expect(resized.width / resized.height).toBeCloseTo(2, 1)
  await page.screenshot({ path: testInfo.outputPath('mindmap-image-connection.png'), animations: 'disabled' })
  const agentBody = () => JSON.parse(item.payload.text).nodes.find(node => node.title === 'Alice Example')?.body_html
  await expect.poll(agentBody).toMatch(/^<blockquote/)
  await agentLink.click()
  await expect(contextTools.getByRole('button', { name: 'Show embedded content', exact: true })).toHaveCount(0)
  await expect(contextTools.getByRole('button', { name: 'Show URL', exact: true })).toBeVisible()
  await expect(agentAvatar).toHaveJSProperty('naturalWidth', 2)
  expect(avatarRequests).toBe(loadedAvatarRequests)
  await page.keyboard.press('8')
  const agentEditor = agentBranch.locator('[data-editor-surface]')
  await expect(agentEditor.getByText('8', { exact: true })).toBeVisible()
  await expect(agentLink).toBeVisible()
  await expect.poll(agentBody).toContain('<p>8</p>')
  await agentEditor.press('Control+z')
  await expect.poll(agentBody).not.toContain('<p>8</p>')
  await agentLink.click()
  await contextTools.getByRole('button', { name: 'Show URL', exact: true }).click()
  await expect.poll(agentBody).toMatch(/^<p><a /)
  await page.getByText('Schedule', { exact: true }).click()
  await expect.poll(async () => (await portrait.boundingBox()).width).toBeCloseTo(resized.width, 0)
  const attachedFile = page.getByRole('region', { name: 'Attachments', exact: true })
    .locator('.document-attachments__item').filter({ hasText: attachment.name })
  await attachedFile.hover()
  await attachedFile.getByRole('button', { name: 'Actions', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Insert into document', exact: true }).click()
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.parent === 'schedule' && node.title === attachment.name)?.body_html).toContain(`/attachments/${attachment.id}`)

  await measurements.press('Alt+Enter')
  await body.getByText('Rich evidence', { exact: true }).click()
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await chooseManagedFiles(editTools.getByRole('button', { name: 'Galaris link', exact: true }), 'index.txt')
  await expect(body.getByRole('link', { name: 'index.txt', exact: true })).toBeVisible()
  await expect.poll(() => JSON.parse(item.payload.text).nodes.find(node => node.id === measurementsId)?.body_html).toContain('index.txt')
  expect(JSON.parse(item.payload.text).nodes.some(node => node.parent === measurementsId)).toBe(false)

  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, component, { props: { ...props, style: { height: 'calc(100dvh - 64px)' } }, shell: true, dark: true, privileges: ['DOCUMENT_EDIT'] })
  await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 200 } })
  await expect(horizontalBar).toBeInViewport()
  if (browserName === 'chromium') {
    const session = await page.context().newCDPSession(page)
    await session.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 2 })
    const surface = await canvas.boundingBox()
    const y = Math.min(surface.y + surface.height - 35, 810)
    const start = await root.boundingBox()
    const touch = (type, touchPoints) => session.send('Input.dispatchTouchEvent', { type, touchPoints })
    await touch('touchStart', [{ x: 285, y: y - 30, id: 1 }])
    await touch('touchMove', [{ x: 240, y, id: 1 }])
    await touch('touchEnd', [])
    await expect.poll(async () => (await root.boundingBox()).x).toBeLessThan(start.x - 25)
    const pinch = await canvas.evaluate(element => {
      const bounds = element.getBoundingClientRect()
      const isBackground = (x, y) => {
        const hit = document.elementFromPoint(x, y)
        return element.contains(hit) && !hit.closest('.mindmap-node')
      }
      for (let y = Math.min(bounds.bottom, innerHeight) - 30; y > Math.max(bounds.top, 0) + 20; y -= 16) {
        for (let x = Math.max(bounds.left, 0) + 40; x + 100 < Math.min(bounds.right, innerWidth); x += 24) {
          if (isBackground(x, y) && isBackground(x + 55, y)) return { x, y }
        }
      }
      return null
    })
    expect(pinch, 'two visible background points for the pinch gesture').not.toBeNull()
    await touch('touchStart', [{ ...pinch, id: 1 }, { x: pinch.x + 55, y: pinch.y, id: 2 }])
    await touch('touchMove', [{ x: pinch.x - 28, y: pinch.y, id: 1 }, { x: pinch.x + 100, y: pinch.y, id: 2 }])
    await touch('touchEnd', [])
    await expect(page.getByRole('button', { name: 'Reset to 100%', exact: true })).not.toHaveText('100%')
    await session.send('Emulation.setTouchEmulationEnabled', { enabled: false })
    await session.detach()
    await page.getByRole('button', { name: 'Reset to 100%', exact: true }).click()
  }
  await expect(portrait).toHaveJSProperty('naturalWidth', 2)
  await expect.poll(async () => (await portrait.boundingBox()).width).toBeCloseTo(resized.width, 0)
  const branch = page.getByRole('treeitem', { name: 'Measurements', exact: true })
  await expect(branch).toBeVisible()
  await page.getByRole('button', { name: 'Collapse Site survey', exact: true }).click()
  await expect(water).toHaveCount(0)
  await page.getByRole('button', { name: 'Expand Site survey', exact: true }).click()
  await page.getByRole('button', { name: 'Fit map', exact: true }).click()
  await expect(water).toBeVisible()
  await water.getByRole('button', { name: 'Show note and link', exact: true }).click()
  await expect(page.getByText('Collect at the inlet.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Rename branch', exact: true }).click()
  await expect(title).toBeFocused()
  await title.press('Escape')
  await expect(title).toHaveCount(0)
  await branch.getByText('Rich evidence', { exact: true }).click()
  await expect(branch).toBeFocused()
  await expect(title).toHaveCount(0)
  await branch.press('Alt+Enter')
  await expect(branch.locator('[data-editor-surface] table')).toBeVisible()
  await branch.locator('[data-editor-surface] td p').first().click()
  await expect(contextTools.getByRole('button', { name: 'Insert paragraph before block', exact: true })).toBeVisible()
  await expect(contextTools.getByRole('button', { name: 'Insert paragraph after block', exact: true })).toBeVisible()
  await expect(branch.locator('[data-editor-surface] li')).toHaveText('Check the sample')
  await expect(branch.locator('[data-editor-surface] u', { hasText: 'Underlined note' }).first()).toHaveCSS('text-decoration-line', 'underline')
  await expect(evidence).toHaveCSS('font-size', '24px')
  await evidence.click()
  await body.press('Home')
  await body.press('Shift+End')
  await editTools.getByRole('button', { name: 'More tools', exact: true }).click()
  const equation = page.getByRole('button', { name: 'Inline equation', exact: true })
  await expect(equation).toBeVisible()
  await page.getByRole('button', { name: 'Font size', exact: true }).click()
  await page.getByRole('menuitemradio', { name: '18', exact: true }).click()
  await expect(evidence).toHaveCSS('font-size', '18px')
  await expect(equation).toBeHidden()
  await page.screenshot({ path: testInfo.outputPath('mindmap-mobile-dark.png'), animations: 'disabled' })
  await editTools.getByRole('button', { name: 'Return to map', exact: true }).click()
  await expect(toolbar).toBeVisible()

  await page.route(new RegExp(`/api/documents/${documentId}/export-bundle(?:\\?|$)`), route => {
    const { html } = route.request().postDataJSON()
    expect(html).toContain('Rich evidence')
    expect(html).toContain('Water samples')
    expect(html).toContain(`href="document://${documentId}/attachments/${attachment.id}"`)
    expect(html).toContain('data:image/png;base64,')
    return route.fulfill({ contentType: 'application/zip', body: Buffer.from('504b0506000000000000000000000000000000000000', 'hex') })
  })
  const exports = toolbar.getByRole('group', { name: 'Export', exact: true })
  const archive = page.waitForEvent('download')
  await exports.getByRole('button', { name: 'Export document and attachments (ZIP)', exact: true }).click()
  expect((await archive).suggestedFilename()).toBe('Synthetic map.zip')

  await page.evaluate(() => {
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: data => Boolean(data.files?.length) })
    Object.defineProperty(navigator, 'share', { configurable: true, value: async data => {
      window.sharedMap = { name: data.files[0].name, type: data.files[0].type, url: data.url }
    } })
  })
  await exports.getByRole('button', { name: 'Share', exact: true }).click()
  const share = page.getByRole('dialog', { name: 'Share document', exact: true })
  await share.getByRole('button', { name: 'Share', exact: true }).click()
  await expect(share).toBeHidden()
  expect(await page.evaluate(() => window.sharedMap)).toMatchObject({ name: 'Synthetic map.pdf', type: 'application/pdf' })

  await page.getByRole('button', { name: 'Download source', exact: true }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByText('OPML (.opml)', { exact: true }).click()
  expect((await downloaded).suggestedFilename()).toBe('Synthetic map.opml')

  const longMap = { version: 1, nodes: [
    { id: 'root', parent: null, title: 'Long field map' },
    ...Array.from({ length: 52 }, (_, index) => ({ id: `row-${index}`, parent: 'root', title: `Observation ${index + 1}` })),
  ] }
  item = { ...item, revision: item.revision + 1, payload: { text: JSON.stringify(longMap) } }
  await page.setViewportSize({ width: 1440, height: 900 })
  await mount(page, component, { props: { ...props, style: { height: 'calc(100dvh - 90px)' } }, shell: true, privileges: ['DOCUMENT_EDIT'] })
  const documentScroll = page.locator('.document-editor')
  const heading = page.locator('.document-editor-toolbar')
  const attachmentsPanel = page.locator('.document-editor-attachments')
  await expect.poll(() => documentScroll.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(500)
  const originalHeading = await heading.boundingBox()
  const originalAttachments = await attachmentsPanel.boundingBox()
  const mapBounds = await canvas.boundingBox()
  await page.mouse.move(mapBounds.x + mapBounds.width - 45, 690)
  await page.mouse.wheel(0, 280)
  const verticalScroll = () => documentScroll.evaluate(element => element.scrollTop)
  await expect.poll(verticalScroll).toBeGreaterThan(240)
  expect(await canvas.evaluate(element => element.scrollTop)).toBe(0)
  expect((await heading.boundingBox()).y).toBeLessThan(originalHeading.y - 240)
  expect((await attachmentsPanel.boundingBox()).y).toBeLessThan(originalAttachments.y - 240)
  await expect(toolbar).toBeInViewport()
  await expect(horizontalBar).toBeInViewport()
  const scrollBounds = await documentScroll.boundingBox()
  const barBounds = await horizontalBar.boundingBox()
  expect(Math.abs((await toolbar.boundingBox()).y - scrollBounds.y)).toBeLessThan(2)
  expect(Math.abs(barBounds.y + barBounds.height - scrollBounds.y - scrollBounds.height)).toBeLessThan(2)
  await page.screenshot({ path: testInfo.outputPath('mindmap-document-scroll.png'), animations: 'disabled' })
  const beforeBarClick = await scrollPosition()
  await horizontalBar.click({ position: { x: barBounds.width / 10, y: barBounds.height / 2 } })
  await expect.poll(scrollPosition).toBeLessThan(beforeBarClick)
  const beforeDrag = await verticalScroll()
  await page.mouse.move(mapBounds.x + mapBounds.width - 45, 690)
  await page.mouse.down()
  await page.mouse.move(mapBounds.x + mapBounds.width - 45, 615, { steps: 4 })
  await page.mouse.up()
  await expect.poll(verticalScroll).toBeGreaterThan(beforeDrag + 60)
  await page.mouse.wheel(0, 3000)
  await expect(attachmentsPanel).toBeInViewport()
})
