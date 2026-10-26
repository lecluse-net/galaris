import { test, expect, mount } from './fixtures.mjs'

const root = '00000000-0000-4000-8000-000000000701'
const child = '00000000-0000-4000-8000-000000000702'
const id = '00000000-0000-4000-8000-000000000703'
const initial = { id, title: 'Synthetic unplaced data', revision: 1, lock_version: 1, can_write: false, can_manage: false, can_delete: false }

test('personal folders classify readable Datasets, persist moves and return data when a branch is removed', async ({ page }, testInfo) => {
  let tags = [{ id: root, name: 'Synthetic root', parent_id: null, position: 1, icon: null }]
  let placement = null
  let rejectIcon = false
  const moves = []
  await page.route('**/api/datasets/library/facets', route => route.fulfill({ json: { owners: [{ kind: 'user', id: 1, label: 'Synthetic owner', can_write: false }], keywords: ['Synthetic keyword'], current_user_id: 1 } }))
  await page.route('**/api/datasets/tags', async route => {
    if (route.request().method() === 'POST') { const data = route.request().postDataJSON(); const item = { ...data, id: child, icon: null, position: 2 }; tags.push(item); return route.fulfill({ json: item }) }
    await route.fulfill({ json: tags })
  })
  await page.route(`**/api/datasets/tags/${root}*`, async route => {
    if (route.request().method() === 'DELETE') {
      if (!new URL(route.request().url()).searchParams.has('confirmed') || new URL(route.request().url()).searchParams.get('confirmed') !== 'true') return route.fulfill({ json: { deleted: false } })
      tags = []; placement = null; return route.fulfill({ json: { deleted: true } })
    }
    if (rejectIcon) return route.fulfill({ status: 422, json: { detail: 'Synthetic rejected icon' } })
    const update = route.request().postDataJSON()
    if (update.icon?.startsWith('data:image/octet-stream;base64,')) update.icon = update.icon.replace('image/octet-stream', 'image/png')
    tags[0] = { ...tags[0], ...update }; await route.fulfill({ json: null })
  })
  await page.route(`**/api/datasets/tags/${child}`, async route => { tags = tags.map(tag => tag.id === child ? { ...tag, ...route.request().postDataJSON() } : tag); await route.fulfill({ json: null }) })
  await page.route('**/api/datasets/library/move', async route => { const move = route.request().postDataJSON(); moves.push(move); placement = move.parent_id; await route.fulfill({ json: null }) })
  await page.route('**/api/datasets?*', async route => {
    const params = new URL(route.request().url()).searchParams
    const visible = params.get('classification') !== 'root' && (params.get('tag_id') ? params.get('tag_id') === placement : params.get('classification') !== 'unclassified' || placement === null)
    await route.fulfill({ json: { items: visible ? [{ ...initial, tag_ids: placement ? [placement] : [] }] : [], total: visible ? 1 : 0 } })
  })
  await mount(page, 'app/dataset/components/DatasetLibraryNavigation.vue', { props: { selectedId: '' }, privileges: ['DATASET_READ'] })
  const row = page.getByRole('list', { name: 'Unclassified Datasets', exact: true }).getByRole('link', { name: initial.title, exact: true })
  await expect(row).toBeVisible()
  await page.getByText('Synthetic root', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Edit folder', exact: true }).click()
  await page.getByRole('button', { name: 'Icon for folder Synthetic root', exact: true }).click()
  await page.getByRole('button', { name: 'Blue folder', exact: true }).click()
  await expect.poll(() => tags[0].icon).toBe('folder:blue')
  const openIcon = async () => {
    await page.getByText('Synthetic root', { exact: true }).click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Edit folder', exact: true }).click()
    await page.getByRole('button', { name: 'Icon for folder Synthetic root', exact: true }).click()
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 10L5 0L10 10Z"/>${' '.repeat(100_001)}</svg>`
  await openIcon()
  await page.locator('input[type=file]').setInputFiles({ name: 'Synthetic large.svg', mimeType: 'image/svg+xml', buffer: Buffer.from(svg) })
  const uploaded = 'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64')
  await expect.poll(() => tags[0].icon === uploaded).toBe(true)
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await openIcon()
  rejectIcon = true
  const retryFile = { name: 'Synthetic retry.svg', mimeType: 'image/svg+xml',
    buffer: Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg">${' '.repeat(58_000)}</svg>`) }
  await page.locator('input[type=file]').setInputFiles(retryFile)
  await expect(page.locator('.tag-icon-picker').getByRole('alert')).toContainText('Could not save this icon. Please try again.')
  expect(tags[0].icon).toBe(uploaded)
  await expect(page.getByLabel('Search icons', { exact: true })).toBeVisible()
  rejectIcon = false
  await page.locator('input[type=file]').setInputFiles(retryFile)
  await expect.poll(() => tags[0].icon).toBe('data:image/svg+xml;base64,' + retryFile.buffer.toString('base64'))
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  for (const format of ['png', 'jpeg', 'webp']) {
    const image = await page.evaluate(format => {
      const canvas = document.createElement('canvas'); canvas.width = 16; canvas.height = 8
      canvas.getContext('2d').fillRect(0, 0, 16, 8)
      return canvas.toDataURL(`image/${format}`)
    }, format)
    await openIcon()
    await page.locator('input[type=file]').setInputFiles({ name: `Synthetic icon.${format}`, mimeType: `image/${format}`, buffer: Buffer.from(image.split(',')[1], 'base64') })
    await expect.poll(() => tags[0].icon).toBe(image)
    await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
    const rendered = page.getByRole('button', { name: 'Icon for folder Synthetic root', exact: true }).locator('img')
    await expect.poll(() => rendered.evaluate(image => image.naturalWidth)).toBe(16)
  }
  const png = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 16; canvas.height = 8
    return canvas.toDataURL('image/png')
  })
  await openIcon()
  await page.locator('input[type=file]').setInputFiles({ name: 'Synthetic unknown-type.png', mimeType: '', buffer: Buffer.from(png.split(',')[1], 'base64') })
  await expect.poll(() => tags[0].icon).toBe(png)
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await openIcon()
  await page.getByRole('combobox', { name: 'Icon library', exact: true }).click()
  await page.getByRole('option', { name: 'My icons', exact: true }).click()
  const normalized = page.getByRole('button', { name: 'Synthetic unknown-type.png', exact: true }).locator('img')
  await expect(normalized).toHaveAttribute('src', png)
  await expect.poll(() => normalized.evaluate(image => image.naturalWidth)).toBe(16)
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
  await page.getByRole('textbox', { name: 'Name', exact: true }).press('Escape')
  await page.getByText('Synthetic root', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Create a subfolder', exact: true }).click()
  const name = page.getByRole('textbox', { name: 'Name', exact: true })
  await expect(name).toBeVisible(); await name.fill('Synthetic child'); await name.press('Enter')
  await expect(page.getByText('Synthetic child', { exact: true })).toBeVisible()
  await row.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Move to a folder', exact: true }).click()
  await page.getByRole('combobox', { name: 'Parent folder', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic root / Synthetic child', exact: true }).click()
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(moves).toEqual([{ kind: 'dataset', identity: id, parent_id: child }])
  await expect(page.locator('.dataset-list-scroll').getByRole('link', { name: initial.title, exact: true })).toHaveCount(0)
  // Reopen the branch through its context menu and verify the retained resource.
  await page.getByText('Synthetic child', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Expand all in this folder', exact: true }).click()
  await expect(page.getByRole('tree').getByRole('link', { name: initial.title, exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('dataset-folders.png'), animations: 'disabled' })
  await page.getByText('Synthetic root', { exact: true }).click({ button: 'right' })
  await expect(page.getByRole('menu', { name: 'Actions for folder Synthetic child', exact: true })).toHaveCount(0)
  await page.getByRole('menu', { name: 'Actions for folder Synthetic root', exact: true }).getByRole('menuitem', { name: 'Delete folder', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete folder', exact: true }).click()
  await expect(page.getByText('Synthetic root', { exact: true })).toHaveCount(0)
  await expect(page.locator('.dataset-list-scroll').getByRole('link', { name: initial.title, exact: true })).toBeVisible()
})

test('the same library filters apply together and stale searches cannot overwrite the current results', async ({ page }) => {
  const requests = []
  let releaseSlow
  await page.route('**/api/datasets/tags', route => route.fulfill({ json: [] }))
  await page.route('**/api/datasets/library/facets', route => route.fulfill({ json: { owners: [{ kind: 'agent', id: 7, label: 'Synthetic agent', can_write: false }], keywords: ['Synthetic keyword'], current_user_id: 1 } }))
  await page.route('**/api/datasets?*', async route => {
    const params = Object.fromEntries(new URL(route.request().url()).searchParams); requests.push(params)
    if (params.q === 'slow') await new Promise(resolve => { releaseSlow = resolve })
    await route.fulfill({ json: { items: [{ ...initial, title: params.q || initial.title }], total: 1 } })
  })
  await mount(page, 'app/dataset/components/DatasetLibraryNavigation.vue', { props: { selectedId: '' }, privileges: ['DATASET_READ'] })
  await expect(page.getByRole('list', { name: 'Unclassified Datasets', exact: true }).getByRole('link', { name: initial.title, exact: true })).toBeVisible()
  expect(requests[0].classification).toBe('unclassified')
  const search = page.getByRole('textbox', { name: 'Search', exact: true })
  await search.fill('Synthetic')
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('switch', { name: 'Unclassified', exact: true }).click()
  await page.getByRole('combobox', { name: 'Owner', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic agent', exact: true }).click()
  await page.getByRole('combobox', { name: 'Keyword', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic keyword', exact: true }).click()
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ classification: 'all', owner_kind: 'agent', owner: '7', keyword: 'Synthetic keyword' })
  await expect(search).toHaveValue('Synthetic')
  const readsBeforeRenewal = requests.length
  await page.route('**/api/auth/refresh', route => route.fulfill({ json: { access_token: 'synthetic-renewed-session', token_type: 'bearer' } }))
  await page.evaluate(async () => { const { refreshAccessToken } = await import('/core/api.ts'); await refreshAccessToken() })
  await expect(search).toHaveValue('Synthetic')
  expect(requests.length).toBe(readsBeforeRenewal)
  await search.fill('slow'); await expect.poll(() => !!releaseSlow).toBe(true)
  await search.fill('current'); await expect(page.getByRole('link', { name: 'current', exact: true })).toBeVisible()
  const slowResponse = page.waitForResponse(response => new URL(response.url()).searchParams.get('q') === 'slow')
  releaseSlow(); await slowResponse
  await expect(page.getByRole('link', { name: 'slow', exact: true })).toHaveCount(0)
})
