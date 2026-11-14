import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

test('skill files remain directly selectable throughout the tree', async ({ page }, testInfo) => {
  const files = Array.from({ length: 301 }, (_, index) => ({ path: `docs/entry-${String(index).padStart(3, '0')}.txt`, name: `entry-${index}.txt`, size: 12, text: true }))
  await mount(page, 'app/skill/components/SkillViewerDialog.vue', { props: { label: 'Synthetic package', files, path: files[205].path, content: 'Synthetic contents' } })
  const tree = page.getByRole('tree')
  await tree.getByText('entry-000.txt', { exact: true }).click()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').at(-1).value)).toBe(files[0].path)
  await tree.getByText('entry-300.txt', { exact: true }).click()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').at(-1).value)).toBe(files[300].path)
  await page.screenshot({ path: testInfo.outputPath('skill-file-tree.png'), animations: 'disabled' })
})

test('folder selectors reveal their current folder through its range and preserve selection', async ({ page }) => {
  const options = Array.from({ length: 301 }, (_, index) => ({ path: `Folder${String(index).padStart(3, '0')}` }))
  await mount(page, 'app/document/components/DocumentFolderSelect.vue', { props: { options, modelValue: options[205].path } })
  await page.getByRole('button', { name: options[205].path, exact: true }).click()
  const tree = page.getByRole('tree')
  await expect(tree.getByText(options[205].path, { exact: true })).toBeVisible()
  await expect(tree.getByText(options[0].path, { exact: true })).toHaveCount(0)
  await tree.getByText('1–100', { exact: true }).click()
  await tree.getByText(options[0].path, { exact: true }).click()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1).value)).toBe(options[0].path)
})

test('Mail folder filtering preserves previously selected folders', async ({ page }) => {
  await jsonRoute(page, '**/api/mail/connections/42/mailboxes', ['INBOX', 'Projects', 'Archive'].map(name => ({
    name, label: name, delimiter: '/', selectable: true,
  })))
  await mount(page, 'app/connection/components/MailFolderAccess.vue', { props: { connectionId: 42, modelValue: '["INBOX"]' } })
  await expect(page.getByRole('checkbox', { name: 'Projects', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: 'Filter folders', exact: true }).fill('Archive')
  await expect(page.getByRole('checkbox', { name: 'Projects', exact: true })).toBeHidden()
  await page.getByRole('checkbox', { name: 'Archive', exact: true }).check()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1).value)).toBe('["INBOX","Archive"]')
})

test('sub-document ranges in the lower list fetch only the opened page and survive reopening', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 1000 })
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [] })
  await jsonRoute(page, '**/api/documents/parent', { item: { ...document, id: 'parent', title: 'Synthetic parent' }, agent_id: 7 })
  const reads = []
  const childTitle = index => `Synthetic child ${index}` + (index < 300 ? ' with a long title for range navigation' : '')
  const entry = (id, title, children_count = 0) => ({ item: { ...document, id, title }, children_count,
    tags: [], agent_ids: [7], writable_agent_ids: [] })
  await page.route('**/api/documents/library', route => {
    const body = route.request().postDataJSON()
    if (body.parent_document_id) {
      reads.push(body)
      const entries = Array.from({ length: Math.min(100, 301 - body.offset) }, (_, index) => entry(`child-${body.offset + index}`, childTitle(body.offset + index)))
      const tree_ranges = body.include_tree_ranges ? [0, 100, 200, 300].map(offset => ({ offset, size: 100,
        first_title: childTitle(offset), last_title: childTitle(Math.min(300, offset + 99)) })) : []
      return route.fulfill({ json: { entries, total: 301, has_more: body.offset + entries.length < 301, keywords: [], tree_ranges } })
    }
    const entries = body.classification === 'root' ? [] : [entry('parent', 'Synthetic parent', 301)]
    return route.fulfill({ json: { entries, total: entries.length, has_more: false, keywords: [] } })
  })
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null },
    privileges: ['DOCUMENT_ACCESS'], containerStyle: { height: '950px', width: '100%' } })
  const list = page.getByLabel('Unclassified documents', { exact: true })
  await list.getByRole('button', { name: 'Expand sub-documents of Synthetic parent', exact: true }).click()
  const lastRange = list.getByTitle('Synthetic child 300 - Synthetic child 300', { exact: true })
  await expect(lastRange).toBeVisible()
  expect(reads.map(read => read.offset)).toEqual([0])
  await lastRange.click()
  await expect(list.locator('.document-branch-row').getByText('Synthetic child 300', { exact: true })).toBeVisible()
  expect(reads.map(read => read.offset)).toEqual([0, 300])
  expect(reads.every(read => read.limit === 100)).toBe(true)
  await list.getByRole('button', { name: 'Collapse sub-documents of Synthetic parent', exact: true }).click()
  await list.getByRole('button', { name: 'Expand sub-documents of Synthetic parent', exact: true }).click()
  await expect(list.locator('.document-branch-row').getByText('Synthetic child 300', { exact: true })).toBeVisible()
  expect(reads).toHaveLength(2)
  await page.screenshot({ path: testInfo.outputPath('mobile-subdocument-ranges.png'), animations: 'disabled' })
})
