import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

async function library(page, options = {}) {
  const entries = ['Alpha', 'Beta', 'Gamma', 'Omega'].map((title, index) => ({
    item: { ...structuredClone(document), id: `selection-${index}`, title }, children_count: index === 1 ? 1 : 0,
    tags: [], agent_ids: [7], writable_agent_ids: [7], position: index,
  }))
  const child = { ...entries[0], item: { ...entries[0].item, id: 'child', title: 'Child' } }
  for (const entry of [...entries, child]) await jsonRoute(page, `**/api/documents/${entry.item.id}`, { item: entry.item, agent_id: 7 })
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [] })
  await page.route('**/api/documents/library', route => {
    const body = route.request().postDataJSON()
    const values = body.parent_document_id ? [child] : entries.filter(entry => !body.query || entry.item.title.includes(body.query))
    return route.fulfill({ json: { entries: values, total: values.length, has_more: false, keywords: [] } })
  })
  await mount(page, 'app/document/components/DocumentLibraryNavigation.vue', {
    props: { selectedDocumentId: null }, containerStyle: { height: '900px', width: '440px', maxWidth: '100vw' }, ...options,
  })
  await expect(page.getByRole('tree').getByText('Omega', { exact: true })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Unclassified documents', exact: true }).getByText('Omega', { exact: true })).toBeVisible()
}

for (const scope of ['tree', 'list']) {
  test(`document ${scope} selects visible ranges and toggles individual documents without opening them`, async ({ page }, testInfo) => {
    await library(page)
    const panel = scope === 'tree' ? page.getByRole('tree') : page.getByRole('list', { name: 'Unclassified documents', exact: true })
    const row = title => panel.locator('.document-row').filter({ has: page.getByText(title, { exact: true }) })
    const selected = () => panel.locator('.document-row[aria-selected="true"]')
    await row('Beta').click()
    await row('Omega').click({ modifiers: ['Shift'] })
    await expect(selected()).toHaveCount(3)
    await expect(row('Alpha')).toHaveAttribute('aria-selected', 'false')
    await row('Gamma').click({ modifiers: ['Control'] })
    await expect(selected()).toHaveCount(2)
    await row('Alpha').click({ modifiers: ['Meta'] })
    await expect(selected()).toHaveCount(3)
    // The most recent individual click becomes the anchor; Shift can shrink a range.
    await row('Gamma').click({ modifiers: ['Shift'] })
    await expect(selected()).toHaveCount(3)
    await row('Beta').click({ modifiers: ['Shift'] })
    await expect(selected()).toHaveCount(2)
    await row('Omega').click({ modifiers: ['Control', 'Shift'] })
    await expect(selected()).toHaveCount(4)
    expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').map(event => event.value.item.title))).toEqual(['Beta'])
    await expect(page.getByText('4 selected', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`selection-${scope}.png`), animations: 'disabled' })
    await page.setViewportSize({ width: 390, height: 1000 })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath(`selection-${scope}-mobile-dark.png`), animations: 'disabled' })
    await page.getByRole('button', { name: 'Clear selection', exact: true }).click()
    await expect(selected()).toHaveCount(0)
    await row('Omega').click()
    await row('Beta').click({ modifiers: ['Shift'] })
    await expect(selected()).toHaveCount(3)
    await row('Alpha').click()
    await expect(selected()).toHaveCount(1)
    await row('Alpha').focus()
    await page.keyboard.press('Control+Enter')
    await expect(selected()).toHaveCount(0)
  })
}

test('tree intervals include expanded descendants, exclude collapsed ones and reset with the session', async ({ page }) => {
  await library(page)
  const tree = page.getByRole('tree')
  const row = title => tree.locator('.document-row').filter({ has: page.getByText(title, { exact: true }) })
  const betaNode = tree.getByRole('treeitem').filter({ has: page.getByText('Beta', { exact: true }) })
  await betaNode.press('Space')
  await expect(row('Child')).toBeVisible()
  await row('Alpha').click()
  await row('Gamma').click({ modifiers: ['Shift'] })
  await expect(row('Child')).toHaveAttribute('aria-selected', 'true')
  await betaNode.press('Space')
  await row('Alpha').click()
  await row('Gamma').click({ modifiers: ['Shift'] })
  await expect(page.getByText('3 selected', { exact: true })).toBeVisible()
  await expect(row('Child')).not.toBeVisible()
  await page.evaluate(async () => {
    const api = await import('/core/api.ts')
    api.invalidateSessionRequests()
    window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'new-session' }))
  })
  await expect(tree.locator('[aria-selected="true"]')).toHaveCount(0)
  await expect(row('Omega')).toBeVisible()
  await row('Gamma').click({ modifiers: ['Shift'] })
  await expect(tree.locator('.document-row[aria-selected="true"]')).toHaveCount(1)
})

test('search changes reset the list selection and its range anchor', async ({ page }) => {
  await library(page)
  const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
  await list.getByText('Alpha', { exact: true }).click()
  await list.getByText('Omega', { exact: true }).click({ modifiers: ['Shift'] })
  await page.getByRole('textbox', { name: 'Search document titles and content', exact: true }).fill('Beta')
  await expect(list.locator('.document-row')).toHaveCount(1)
  await expect(list.locator('[aria-selected="true"]')).toHaveCount(0)
  await list.getByText('Beta', { exact: true }).click({ modifiers: ['Shift'] })
  await expect(list.locator('[aria-selected="true"]')).toHaveCount(1)
})
