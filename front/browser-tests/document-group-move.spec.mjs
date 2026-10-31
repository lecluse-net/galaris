import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

async function library(page, { list = false } = {}) {
  const tags = ['Source', 'Target'].map(name => ({ id: name.toLowerCase(), name, parent_id: null }))
  const items = ['Alpha', 'Beta', 'Gamma', 'Omega', 'Child'].map((title, index) => ({
    ...structuredClone(document), id: `move-${index}`, title,
  }))
  const folders = new Map(items.slice(0, 4).map(item => [item.id, 'source']))
  const parents = new Map([['move-4', 'move-1']])
  let order = items.map(item => item.id)
  const state = { writes: [], fail: null, hold: null, release: null, invalidate: false, folders, parents, order: () => order }
  const entry = item => ({ item, tags: tags.filter(tag => folders.get(item.id) === tag.id), agent_ids: [7], writable_agent_ids: [7],
    parent_document_id: parents.get(item.id) ?? null, children_count: [...parents.values()].filter(id => id === item.id).length,
    position: order.indexOf(item.id),
  })
  for (const item of items) await jsonRoute(page, `**/api/documents/${item.id}`, { item, agent_id: 7 })
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags })
  await page.route('**/api/documents/library', route => {
    const body = route.request().postDataJSON()
    const values = order.map(id => items.find(item => item.id === id)).filter(item =>
      body.parent_document_id ? parents.get(item.id) === body.parent_document_id
        : body.tag_id ? folders.get(item.id) === body.tag_id
          : body.classification === 'root' ? folders.get(item.id) === 'root'
            : body.classification === 'unclassified' ? !folders.has(item.id) && !parents.has(item.id) : !parents.has(item.id))
    return route.fulfill({ json: { entries: values.map(entry), total: values.length, has_more: false, keywords: [] } })
  })
  await page.route(/\/api\/documents\/(?:move-\d+\/tags|order)$/, async route => {
    const body = route.request().postDataJSON()
    const id = body.node?.id ?? new URL(route.request().url()).pathname.split('/')[3]
    state.writes.push({ id, ...body })
    if (state.hold === id) await new Promise(resolve => { state.release = resolve })
    if (state.fail === id) return route.fulfill({ status: 409, json: { detail: 'Placement changed' } })
    if (!body.list_only) {
      folders.delete(id); parents.delete(id)
      if (body.parent_document_id) parents.set(id, body.parent_document_id)
      else if (body.tag_id ?? body.parent_id) folders.set(id, body.tag_id ?? body.parent_id)
      else if (body.at_root) folders.set(id, 'root')
    }
    order = order.filter(value => value !== id)
    const anchor = body.anchor ? order.indexOf(body.anchor.id) : -1
    order.splice(anchor < 0 ? order.length : anchor + Number(Boolean(body.after)), 0, id)
    if (state.invalidate) await page.evaluate(() => window.testApp.emitSocket('document.invalidate', { data: {} }))
    return route.fulfill({ status: 204 })
  })
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', {
    props: { selectedDocumentId: null }, containerStyle: { height: '1000px', width: '500px' },
  })
  if (list) {
    await page.getByRole('button', { name: 'Filters', exact: true }).click()
    await page.getByRole('switch', { name: 'Unclassified', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('list', { name: 'All documents', exact: true }).getByText('Omega', { exact: true })).toBeVisible()
  } else {
    await page.getByRole('treeitem').filter({ has: page.getByText('Source', { exact: true }) }).press('Space')
    await expect(page.getByRole('tree').getByText('Omega', { exact: true })).toBeVisible()
  }
  return state
}
const panel = (page, list) => list ? page.getByRole('list', { name: 'All documents', exact: true }) : page.getByRole('tree')
const row = (page, surface, title) => surface.locator('.document-row').filter({ has: page.getByText(title, { exact: true }) })

for (const list of [false, true]) test(`dragging any selected document moves the whole group from the ${list ? 'list' : 'tree'} and supports moving it again`, async ({ page }) => {
  const state = await library(page, { list })
  state.invalidate = list
  const surface = panel(page, list)
  await row(page, surface, 'Alpha').click()
  await row(page, surface, 'Gamma').click({ modifiers: ['Shift'] })
  await row(page, surface, 'Beta').dragTo(page.getByText('Target', { exact: true }))
  await expect.poll(() => state.writes.map(write => write.id)).toEqual(['move-0', 'move-1', 'move-2'])
  await expect.poll(() => [...state.folders.values()].filter(id => id === 'target').length).toBe(3)
  expect(state.parents.get('move-4')).toBe('move-1')
  const target = page.getByLabel('Documents in folder Target', { exact: true })
  await expect(target.getByText('Gamma', { exact: true })).toBeVisible()
  await target.getByText('Gamma', { exact: true }).dragTo(page.getByText('Source', { exact: true }))
  await expect.poll(() => state.writes.map(write => write.id)).toEqual(['move-0', 'move-1', 'move-2', 'move-0', 'move-1', 'move-2'])
  await expect.poll(() => [...state.folders.values()].filter(id => id === 'source').length).toBe(4)
})

test('group ordering preserves rendered order before and after an anchor', async ({ page }) => {
  const state = await library(page, { list: true })
  const list = panel(page, true)
  await row(page, list, 'Alpha').click()
  await row(page, list, 'Gamma').click({ modifiers: ['Control'] })
  const target = title => list.locator('.document-branch-row').filter({ has: page.getByText(title, { exact: true }) })
  await row(page, list, 'Gamma').dragTo(target('Beta'), { targetPosition: { x: 100, y: 1 } })
  await expect.poll(() => state.order().filter(id => id !== 'move-4')).toEqual(['move-0', 'move-2', 'move-1', 'move-3'])
  await expect(list.locator('.document-row[aria-selected="true"]')).toHaveCount(2)
  const bounds = await target('Omega').boundingBox()
  await row(page, list, 'Alpha').dragTo(target('Omega'), { targetPosition: { x: 100, y: bounds.height - 1 } })
  await expect.poll(() => state.order().filter(id => id !== 'move-4')).toEqual(['move-1', 'move-3', 'move-0', 'move-2'])
  expect(state.writes.slice(-2).map(write => write.anchor.id)).toEqual(['move-3', 'move-0'])
})

test('a partial failure leaves only failed documents selected for retry', async ({ page }) => {
  const state = await library(page)
  const tree = panel(page, false)
  state.fail = 'move-1'
  await row(page, tree, 'Alpha').click()
  await row(page, tree, 'Gamma').click({ modifiers: ['Shift'] })
  await row(page, tree, 'Alpha').dragTo(page.getByText('Target', { exact: true }))
  await expect(page.getByText('2 succeeded, 1 failed.', { exact: false })).toBeVisible()
  await expect(row(page, tree, 'Beta')).toHaveAttribute('aria-selected', 'true')
  await expect(row(page, tree, 'Gamma')).toHaveAttribute('aria-selected', 'false')
  state.fail = null
  await row(page, tree, 'Beta').dragTo(page.getByText('Target', { exact: true }))
  await expect.poll(() => state.folders.get('move-1')).toBe('target')
  expect(state.writes.map(write => write.id)).toEqual(['move-0', 'move-1', 'move-2', 'move-1'])
})

for (const destination of ['document', 'root', 'unclassified']) test(`a group can move to ${destination}`, async ({ page }) => {
  const state = await library(page)
  const tree = panel(page, false)
  await row(page, tree, 'Alpha').click()
  await row(page, tree, 'Gamma').click({ modifiers: ['Shift'] })
  const target = destination === 'document' ? row(page, tree, 'Omega')
    : destination === 'root' ? page.getByRole('group', { name: 'Root', exact: true })
      : page.getByRole('list', { name: 'Unclassified documents', exact: true })
  await row(page, tree, 'Beta').dragTo(target)
  await expect.poll(() => state.writes.map(write => write.id)).toEqual(['move-0', 'move-1', 'move-2'])
  await expect.poll(() => ['move-0', 'move-1', 'move-2'].every(id => destination === 'document'
    ? state.parents.get(id) === 'move-3' : destination === 'root'
      ? state.folders.get(id) === 'root' : !state.parents.has(id) && !state.folders.has(id))).toBe(true)
  expect(state.parents.get('move-4')).toBe('move-1')
})

test('selected descendants follow their parent and cannot become the destination of the group', async ({ page }) => {
  const state = await library(page)
  const tree = panel(page, false)
  await tree.getByRole('treeitem').filter({ has: page.getByText('Beta', { exact: true }) }).press('Space')
  await row(page, tree, 'Beta').click()
  await row(page, tree, 'Child').click({ modifiers: ['Control'] })
  await row(page, tree, 'Gamma').click({ modifiers: ['Control'] })
  await row(page, tree, 'Gamma').dragTo(row(page, tree, 'Child'))
  expect(state.writes).toEqual([])
  await row(page, tree, 'Child').dragTo(page.getByText('Target', { exact: true }))
  await expect.poll(() => state.writes.map(write => write.id)).toEqual(['move-1', 'move-2'])
  expect(state.parents.get('move-4')).toBe('move-1')
})

test('changing session during a group move stops unsent requests', async ({ page }) => {
  const state = await library(page)
  const tree = panel(page, false)
  state.hold = 'move-0'
  await row(page, tree, 'Alpha').click()
  await row(page, tree, 'Gamma').click({ modifiers: ['Shift'] })
  await row(page, tree, 'Alpha').dragTo(page.getByText('Target', { exact: true }))
  await expect.poll(() => Boolean(state.release)).toBe(true)
  await page.evaluate(async () => {
    const api = await import('/core/api.ts')
    api.invalidateSessionRequests()
    window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'new-session' }))
  })
  const response = page.waitForResponse(response => response.url().endsWith('/move-0/tags'))
  state.release()
  await (await response).finished()
  await expect(tree.locator('.document-row[aria-selected="true"]')).toHaveCount(0)
  expect(state.writes.map(write => write.id)).toEqual(['move-0'])
})
