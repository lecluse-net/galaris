import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

for (const domain of ['document', 'dataset']) for (const width of [390, 1280]) {
  test(`${domain} root survives filters, folder moves and reopening at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const isDocument = domain === 'document'
    const base = isDocument ? 'documents' : 'datasets'
    const item = { ...document, id: '00000000-0000-4000-8000-000000000801', title: 'Synthetic root resource',
      uri: 'data://00000000-0000-4000-8000-000000000801', can_write: true, can_manage: true, can_delete: true }
    const folder = { id: '00000000-0000-4000-8000-000000000802', name: 'Synthetic folder', parent_id: null, position: 1 }
    const untouched = { ...item, id: '00000000-0000-4000-8000-000000000803', title: 'Synthetic unclassified resource' }
    let parent = null, atRoot = false
    const writes = []
    if (isDocument) await jsonRoute(page, `**/api/documents/${item.id}`, { item, agent_id: 7 })
    if (isDocument) await jsonRoute(page, `**/api/documents/${untouched.id}`, { item: untouched, agent_id: 7 })
    await jsonRoute(page, `**/api/${base}/tags`, isDocument ? { user_id: 1, tags: [folder] } : [folder])
    if (!isDocument) await jsonRoute(page, '**/api/datasets/library/facets', { owners: [], keywords: [], current_user_id: 1 })
    await page.route(isDocument ? '**/api/documents/library' : '**/api/datasets?*', route => {
      const filters = isDocument ? route.request().postDataJSON() : Object.fromEntries(new URL(route.request().url()).searchParams)
      const visible = !(filters.query || filters.q) && (filters.tag_id ? filters.tag_id === parent : filters.classification === 'root' ? atRoot : !parent && !atRoot)
      const items = visible ? [{ ...item, at_root: atRoot, tag_ids: parent ? [parent] : [] }] : []
      if (!filters.tag_id && filters.classification === 'unclassified' && !(filters.query || filters.q)) items.push(untouched)
      return route.fulfill({ json: isDocument ? { entries: items.map(item => ({ item, tags: parent ? [folder] : [],
        agent_ids: [7], writable_agent_ids: [7], user_access: item.access })), total: items.length, has_more: false, keywords: [] }
        : { items, total: items.length } })
    })
    await page.route(isDocument ? `**/api/documents/${item.id}/tags` : '**/api/datasets/library/move', route => {
      const move = route.request().postDataJSON(); writes.push(move)
      parent = isDocument ? move.tag_id : move.parent_id
      atRoot = Boolean(move.at_root)
      return route.fulfill({ json: null })
    })
    const options = { props: isDocument ? { selectedDocumentId: null } : { selectedId: '' },
      privileges: [isDocument ? 'DOCUMENT_EDIT' : 'DATASET_EDIT'], containerStyle: { height: '850px', width: '100%' } }
    const component = `app/${domain}/components/${isDocument ? 'Document' : 'Dataset'}LibraryNavigation.vue`
    await mount(page, component, options)
    const tree = page.getByRole('tree')
    const resource = tree.getByText(item.title, { exact: true })
    const list = page.getByRole('list', { name: isDocument ? 'Unclassified documents' : 'Unclassified Datasets', exact: true })
    const root = page.getByRole('group', { name: 'Root', exact: true })
    await expect(resource).toHaveCount(0)
    await expect(list.getByText(untouched.title, { exact: true })).toBeVisible()
    await list.getByText(item.title, { exact: true }).dragTo(root)
    await expect.poll(() => atRoot).toBe(true)
    await expect(resource).toBeVisible()
    await expect(tree.getByText(untouched.title, { exact: true })).toHaveCount(0)
    await expect(list.getByText(item.title, { exact: true })).toHaveCount(0)
    const search = page.getByRole('textbox', { name: isDocument ? 'Search document titles and content' : 'Search', exact: true })
    await search.fill('No matching resource')
    await expect(list.getByText(item.title, { exact: true })).toHaveCount(0)
    await expect(resource).toBeVisible()
    await search.fill('')
    await resource.dragTo(tree.getByText(folder.name, { exact: true }))
    await expect.poll(() => parent).toBe(folder.id)
    if (!isDocument) await tree.getByText(folder.name, { exact: true }).click()
    await expect(resource).toBeVisible()
    await resource.dragTo(root)
    await expect.poll(() => parent).toBeNull()
    await expect(resource).toHaveCount(1)
    await expect(resource).toBeVisible()
    expect(writes).toEqual(isDocument ? [{ tag_id: null, at_root: true }, { tag_id: folder.id }, { tag_id: null, at_root: true }]
      : [{ kind: 'dataset', identity: item.id, parent_id: null, at_root: true }, { kind: 'dataset', identity: item.id, parent_id: folder.id }, { kind: 'dataset', identity: item.id, parent_id: null, at_root: true }])
    await resource.dragTo(list)
    await expect.poll(() => atRoot).toBe(false)
    await expect(resource).toHaveCount(0)
    await expect(list.getByText(item.title, { exact: true })).toBeVisible()
    await list.getByText(item.title, { exact: true }).dragTo(root)
    await expect(resource).toBeVisible()
    await mount(page, component, options)
    await expect(resource).toBeVisible()
    await root.getByRole('button', { name: isDocument ? 'Create a document at the root' : 'Create a Dataset at the root', exact: true }).click()
    expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'create').at(-1)?.args)).toEqual(isDocument ? [undefined, undefined, true] : [undefined, true])
    await page.screenshot({ path: testInfo.outputPath(`${domain}-root.png`), animations: 'disabled' })
  })
}
