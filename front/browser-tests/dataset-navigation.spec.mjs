import { test, expect, mount, jsonRoute } from './fixtures.mjs'

async function library(page) {
  const items = ['Alpha', 'Beta', 'Gamma'].map((title, index) => ({
    id: `00000000-0000-4000-8000-00000000004${index + 1}0`, title: `Synthetic ${title}`,
    content: JSON.stringify({ value: title }), revision: 1, lock_version: 1,
    can_write: true, can_manage: true, can_delete: true, read_only: false,
    owner_agent_id: null, owner_user_id: 1, global_access: 0, group_access: 0, keywords: [],
    created_at: '2026-01-01T00:00:00Z', updated_at: null,
  })).map(item => ({ ...item, uri: `data://${item.id}` }))
  const state = { items, failSave: false, writes: [] }
  await jsonRoute(page, '**/api/datasets/tags', [])
  await jsonRoute(page, '**/api/datasets/library/facets', { owners: [], keywords: [], current_user_id: 1 })
  await page.route('**/api/datasets?*', route => route.fulfill({ json: { items: state.items, total: state.items.length } }))
  for (const item of items) {
    await page.route(`**/api/datasets/${item.id}`, route => route.fulfill({ json: state.items.find(value => value.id === item.id) }))
    await jsonRoute(page, `**/api/datasets/${item.id}/owner`, { owner: null, options: [], current_user_id: 1 })
    await jsonRoute(page, `**/api/datasets/${item.id}/sharing`, { lock_version: 1, can_manage: true,
      level: 'private', can_write: false, grants: [], options: [], owner: null, owner_groups: [] })
    await page.route(`**/api/datasets/${item.id}/content`, route => {
      if (state.failSave) return route.fulfill({ status: 503, json: { detail: 'Synthetic save unavailable' } })
      const change = route.request().postDataJSON()
      state.writes.push(change)
      const index = state.items.findIndex(value => value.id === item.id)
      state.items[index] = { ...state.items[index], title: change.title, content: change.content,
        revision: state.items[index].revision + 1, lock_version: state.items[index].lock_version + 1 }
      return route.fulfill({ json: state.items[index] })
    })
  }
  return state
}

for (const width of [1440, 390]) {
  test(`Dataset browser history restores visits and the list at ${width}px`, async ({ page }) => {
    const { items } = await library(page)
    await page.setViewportSize({ width, height: 900 })
    await mount(page, 'test-support/browser/DatasetRouteHarness.vue', {
      route: '/dataset', browserHistory: true, privileges: ['DATASET_EDIT'],
    })
    const title = page.getByRole('textbox', { name: 'Title', exact: true })
    const search = page.getByRole('textbox', { name: 'Search', exact: true })
    await search.fill('Synthetic')
    await page.getByRole('list', { name: 'Unclassified Datasets', exact: true }).getByRole('link', { name: items[0].title, exact: true }).click()
    await expect(title).toHaveValue(items[0].title)
    if (width < 1024) await page.evaluate(() => window.testApp.router.push('/dataset'))
    await page.getByRole('list', { name: 'Unclassified Datasets', exact: true }).getByRole('link', { name: items[1].title, exact: true }).click()
    await expect(title).toHaveValue(items[1].title)
    if (width >= 1024) await page.getByRole('list', { name: 'Unclassified Datasets', exact: true }).getByRole('link', { name: items[1].title, exact: true }).click()
    await page.evaluate(() => window.history.back())
    if (width < 1024) {
      await expect(title).toHaveCount(0)
      await expect(search).toHaveValue('Synthetic')
      await page.evaluate(() => window.history.back())
    }
    await expect(title).toHaveValue(items[0].title)
    await expect(page).toHaveURL(new RegExp(`/dataset/${items[0].id}$`))
    await page.evaluate(() => window.history.forward())
    if (width < 1024) {
      await expect(title).toHaveCount(0)
      await page.evaluate(() => window.history.forward())
    }
    await expect(title).toHaveValue(items[1].title)
    await page.evaluate(() => window.history.back())
    if (width < 1024) {
      await expect(title).toHaveCount(0)
      await page.evaluate(() => window.history.back())
    }
    await expect(title).toHaveValue(items[0].title)
    await page.evaluate(() => window.history.back())
    await expect(page).toHaveURL(/\/dataset$/)
    await expect(title).toHaveCount(0)
    await expect(search).toHaveValue('Synthetic')
  })

  test(`Dataset browser traversal preserves an invalid draft and recovers after a failed save at ${width}px`, async ({ page }) => {
    const state = await library(page)
    await page.setViewportSize({ width, height: 900 })
    await mount(page, 'test-support/browser/DatasetRouteHarness.vue', {
      route: '/dataset', browserHistory: true, privileges: ['DATASET_EDIT'],
    })
    await page.getByRole('list', { name: 'Unclassified Datasets', exact: true }).getByRole('link', { name: state.items[0].title, exact: true }).click()
    const json = page.getByRole('textbox', { name: 'JSON content', exact: true })
    await expect(json).toHaveValue(/Alpha/)
    await json.fill('{')
    await page.evaluate(() => window.history.back())
    const confirmation = page.getByRole('dialog').filter({ hasText: 'Discard unsaved changes before continuing?' })
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(json).toHaveValue('{')
    await expect(page).toHaveURL(new RegExp(`/dataset/${state.items[0].id}$`))
    await json.fill('{"value":"Draft to save"}')
    state.failSave = true
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Synthetic save unavailable')
    await page.evaluate(() => window.history.back())
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(json).toHaveValue('{"value":"Draft to save"}')
    state.failSave = false
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => state.writes.length).toBe(1)
    await expect(json).toHaveValue('{\n  "value": "Draft to save"\n}')
    await page.evaluate(() => window.history.back())
    await expect(page).toHaveURL(/\/dataset$/)
    await expect(confirmation).toHaveCount(0)
    await page.evaluate(() => window.history.forward())
    await expect(json).toHaveValue(/Draft to save/)
    await json.fill('{"discarded":true}')
    await page.evaluate(() => window.history.back())
    await confirmation.getByRole('button', { name: 'Discard changes', exact: true }).click()
    await expect(page).toHaveURL(/\/dataset$/)
    await page.evaluate(() => window.history.forward())
    await expect(json).toHaveValue(/Draft to save/)
  })
}
