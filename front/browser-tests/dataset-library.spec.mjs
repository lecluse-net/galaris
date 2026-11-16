import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document as fixture } from './data.mjs'

// Retired the standalone Dataset tree. Shared folder/icon/error guarantees live
// in document-classification.spec.mjs; these cases protect Data in that same library.
async function dataLibrary(page, respond) {
  const item = { ...fixture, document_format: 'data', media_type: 'application/json', title: 'Synthetic data document', payload: { text: '{"count":1}' }, access: { can_read: true, can_write: false } }
  await jsonRoute(page, '**/api/documents/tag-icons', [])
  await jsonRoute(page, '**/api/documents/doc-a', item)
  await page.route('**/api/documents/library', route => respond(route, item))
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', {
    privileges: ['DOCUMENT_ACCESS', 'DOCUMENT_EDIT', 'DATASET_READ'], props: { selectedDocumentId: null },
    containerStyle: { width: '440px', height: '760px', maxWidth: '100vw' },
  })
  return item
}

test('readable Data documents use the shared folders and return to unclassified when a folder is removed', async ({ page }) => {
  let tags = [{ id: 'folder', name: 'Synthetic folder', parent_id: null, position: 1, icon: null }], classified = false
  await page.route('**/api/documents/tags', route => route.fulfill({ json: { user_id: 1, tags } }))
  await page.route('**/api/documents/doc-a/tags', route => {
    classified = Boolean(route.request().postDataJSON().tag_id)
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/documents/tags/folder*', route => {
    const deleted = new URL(route.request().url()).searchParams.get('confirmed') === 'true'
    if (deleted) { tags = []; classified = false }
    return route.fulfill({ json: { deleted, tag_count: 1, document_count: 1 } })
  })
  const item = await dataLibrary(page, (route, item) => {
    const query = route.request().postDataJSON()
    const visible = query.classification !== 'root' && (query.tag_id ? classified : query.classification !== 'unclassified' || !classified)
    return route.fulfill({ json: { entries: visible ? [{ item, tags: classified ? tags : [], agent_ids: [7], writable_agent_ids: [] }] : [], total: Number(visible), keywords: [], owners: [], has_more: false } })
  })
  const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
  await expect(list.getByText(item.title, { exact: true })).toBeVisible()
  await list.getByText(item.title, { exact: true }).dragTo(page.getByRole('tree').getByText('Synthetic folder', { exact: true }))
  await expect.poll(() => classified).toBe(true)
  await expect(list.getByText(item.title, { exact: true })).toHaveCount(0)
  await page.getByRole('tree').getByText('Synthetic folder', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Delete folder', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete folder', exact: true }).click()
  await expect(list.getByText(item.title, { exact: true })).toBeVisible()
})

test('Data document filters use the common query contract and ignore an obsolete search', async ({ page }) => {
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [] })
  let release, oldHandled = false
  const requests = []
  await dataLibrary(page, async (route, item) => {
    const query = route.request().postDataJSON(); requests.push(query)
    if (query.query === 'slow') await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { entries: [{ item: { ...item, title: query.query || item.title }, tags: [], agent_ids: [7], writable_agent_ids: [] }], total: 1, keywords: [], owners: [], has_more: false } })
    if (query.query === 'slow') oldHandled = true
  })
  const search = page.getByRole('textbox', { name: 'Search document titles and content', exact: true })
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('combobox', { name: 'Document format', exact: true }).click()
  await page.getByRole('option', { name: 'Data format', exact: true }).click()
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.document_format).toBe('data')
  try {
    await search.fill('slow'); await expect.poll(() => Boolean(release)).toBe(true)
    await search.fill('current'); await expect(page.getByRole('list', { name: 'Unclassified documents', exact: true }).getByText('current', { exact: true })).toBeVisible()
    release(); await expect.poll(() => oldHandled).toBe(true)
    await expect(page.getByText('slow', { exact: true })).toHaveCount(0)
  } finally { release?.() }
})
