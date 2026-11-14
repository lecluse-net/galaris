import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

for (const mode of ['folders', 'topics', 'agents']) test(`${mode} sends all 210 selected documents in one request that survives leaving the view`, async ({ page }, testInfo) => {
  const entries = Array.from({ length: 210 }, (_, index) => ({ item: { ...document, id: `synthetic-${index}`, title: `Synthetic ${String(index).padStart(3, '0')}`,
    owner_agent_id: mode === 'agents' ? null : 7, owner_user_id: mode === 'agents' ? 1 : null, topic_id: null,
    access: { can_read: true, can_write: true } }, tags: [], agent_ids: [7], writable_agent_ids: [7], user_access: { can_read: true, can_write: true } }))
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: mode === 'folders' ? [{ id: 'target', name: 'Synthetic destination', parent_id: null }] : [] })
  await jsonRoute(page, '**/api/topics/document-library', [{ id: 'target', title: 'Synthetic destination', keywords: [], document_count: 1, without_keywords_count: 1 }])
  await jsonRoute(page, '**/api/documents/library/agents', [{ id: 8, title: 'Synthetic destination', has_avatar: false, keywords: [], document_count: 1, without_keywords_count: 1 }])
  await page.route('**/api/documents/synthetic-*', route => route.fulfill({ json: { item: entries.find(entry => new URL(route.request().url()).pathname.endsWith('/' + entry.item.id)).item, agent_id: 7 } }))
  await page.route('**/api/documents/library', route => {
    const body = route.request().postDataJSON()
    const items = body.classification === 'root' || body.tag_id || body.owner || body.topic_id ? [] : entries
    return route.fulfill({ json: { entries: items.slice(body.offset, body.offset + body.limit), total: items.length, has_more: items.length > body.offset + body.limit, keywords: [] } })
  })
  let release
  const requests = [], moved = []
  const endpoint = mode === 'folders' ? '**/api/documents/order/batch' : mode === 'topics' ? '**/api/topics/documents/classification-batch' : '**/api/documents/library/owners'
  await page.route(endpoint, async route => {
    const body = route.request().postDataJSON(); requests.push(body)
    await new Promise(resolve => { release = resolve })
    if (mode === 'folders' && requests.length === 1) return route.fulfill({ status: 409, json: { detail: 'Synthetic conflict' } })
    moved.push(...(body.document_ids ?? body.documents.map(entry => entry.document_id ?? entry.id)))
    return route.fulfill({ status: 204 })
  })
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', { props: { selectedDocumentId: null },
    user: { id: 1, document_library_mode: mode }, privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT'], containerStyle: { height: '950px', width: '700px' } })
  await page.getByLabel('Per page', { exact: true }).click()
  await page.getByRole('option', { name: '500', exact: true }).click()
  const list = page.getByRole('list', { name: /^(Unclassified documents|Without a topic|Without an agent)$/, exact: true })
  await expect(list.locator('.document-row')).toHaveCount(210)
  const first = list.getByText('Synthetic 000', { exact: true })
  await first.click()
  await list.getByText('Synthetic 209', { exact: true }).click({ modifiers: ['Shift'] })
  await expect(list.locator('.document-row[aria-selected="true"]')).toHaveCount(210)
  await first.dragTo(page.getByRole('tree').getByText('Synthetic destination', { exact: true }))
  await expect.poll(() => requests.length).toBe(1)
  const requested = requests[0].document_ids ?? requests[0].documents.map(entry => entry.document_id ?? entry.id)
  expect(requested).toEqual(entries.map(entry => entry.item.id))
  await expect(page.getByText('Moving 210 documents… You can navigate away.', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('moving-batch.png'), animations: 'disabled' })
  if (mode === 'folders') {
    release()
    await expect(page.getByText('The move could not be confirmed. Refresh the library before retrying.', { exact: true })).toBeVisible()
    await expect(list.locator('.document-row[aria-selected="true"]')).toHaveCount(210)
    expect(moved).toEqual([])
    await first.dragTo(page.getByRole('tree').getByText('Synthetic destination', { exact: true }))
    await expect.poll(() => requests.length).toBe(2)
    expect(requests[1].document_ids).toEqual(requested)
  }
  await page.evaluate(() => window.testApp.unmount())
  release()
  await expect.poll(() => moved.length).toBe(210)
  await expect(page.getByText('210 documents moved.', { exact: true })).toBeVisible()
  expect(requests).toHaveLength(mode === 'folders' ? 2 : 1)
})
