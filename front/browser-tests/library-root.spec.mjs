import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

// Text and Data share one Document library; Dataset-only navigation was retired.
for (const format of ['text', 'data']) for (const width of [390, 1280]) {
  test(`${format} document root survives filters, folder moves and reopening at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const item = { ...document, id: '00000000-0000-4000-8000-000000000801', title: 'Synthetic root resource',
      document_format: format, media_type: format === 'data' ? 'application/json' : 'text/html',
      payload: { text: format === 'data' ? '{"synthetic":true}' : '<p>Synthetic root content</p>' } }
    const folder = { id: '00000000-0000-4000-8000-000000000802', name: 'Synthetic folder', parent_id: null, position: 1 }
    const untouched = { ...item, id: '00000000-0000-4000-8000-000000000803', title: 'Synthetic unclassified resource' }
    let parent = null, atRoot = false
    const writes = []
    await jsonRoute(page, `**/api/documents/${item.id}`, { item, agent_id: 7 })
    await jsonRoute(page, `**/api/documents/${untouched.id}`, { item: untouched, agent_id: 7 })
    await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [folder] })
    await page.route('**/api/documents/library', route => {
      const filters = route.request().postDataJSON()
      const visible = !(filters.query || filters.q) && (filters.tag_id ? filters.tag_id === parent : filters.classification === 'root' ? atRoot : !parent && !atRoot)
      const items = visible ? [{ ...item, at_root: atRoot, tag_ids: parent ? [parent] : [] }] : []
      if (!filters.tag_id && filters.classification === 'unclassified' && !(filters.query || filters.q)) items.push(untouched)
      return route.fulfill({ json: { entries: items.map(item => ({ item, tags: parent ? [folder] : [],
        agent_ids: [7], writable_agent_ids: [7], user_access: item.access })), total: items.length, has_more: false, keywords: [] }
      })
    })
    await page.route(`**/api/documents/${item.id}/tags`, route => {
      const move = route.request().postDataJSON(); writes.push(move)
      parent = move.tag_id
      atRoot = Boolean(move.at_root)
      return route.fulfill({ json: null })
    })
    const options = { props: { selectedDocumentId: null },
      privileges: ['DOCUMENT_EDIT'], containerStyle: { height: '850px', width: '100%' } }
    const component = 'app/document/components/DocumentLibraryNavigation.vue'
    await mount(page, component, options)
    const tree = page.getByRole('tree')
    const resource = tree.getByText(item.title, { exact: true })
    const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
    const root = page.getByRole('group', { name: 'Root', exact: true })
    await expect(resource).toHaveCount(0)
    await expect(list.getByText(untouched.title, { exact: true })).toBeVisible()
    await list.getByText(item.title, { exact: true }).dragTo(root)
    await expect.poll(() => atRoot).toBe(true)
    await expect(resource).toBeVisible()
    await expect(tree.getByText(untouched.title, { exact: true })).toHaveCount(0)
    await expect(list.getByText(item.title, { exact: true })).toHaveCount(0)
    const search = page.getByRole('textbox', { name: 'Search document titles and content', exact: true })
    await search.fill('No matching resource')
    await expect(list.getByText(item.title, { exact: true })).toHaveCount(0)
    await expect(resource).toBeVisible()
    await search.fill('')
    await resource.dragTo(tree.getByText(folder.name, { exact: true }))
    await expect.poll(() => parent).toBe(folder.id)
    await expect(resource).toBeVisible()
    await resource.dragTo(root)
    await expect.poll(() => parent).toBeNull()
    await expect(resource).toHaveCount(1)
    await expect(resource).toBeVisible()
    expect(writes).toEqual([{ tag_id: null, at_root: true }, { tag_id: folder.id }, { tag_id: null, at_root: true }])
    await resource.dragTo(list)
    await expect.poll(() => atRoot).toBe(false)
    await expect(resource).toHaveCount(0)
    await expect(list.getByText(item.title, { exact: true })).toBeVisible()
    await list.getByText(item.title, { exact: true }).dragTo(root)
    await expect(resource).toBeVisible()
    await mount(page, component, options)
    await expect(resource).toBeVisible()
    await root.getByRole('button', { name: 'Create a document at the root', exact: true }).click()
    expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'create').at(-1)?.args.slice(0, 3))).toEqual([undefined, undefined, true])
    await page.screenshot({ path: testInfo.outputPath(`${format}-root.png`), animations: 'disabled' })
  })
}
