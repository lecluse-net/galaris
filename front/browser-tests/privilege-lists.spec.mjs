import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function privilegePage(page, { canManage = true, failFirstMove = false } = {}) {
  const privilege = { id: 17, code: 'SYNTHETIC_EDIT', display_name: 'Synthetic edit privilege', privilege_list_id: null }
  const lists = [
    { id: 3, display_name: 'Synthetic destination', privileges: [] },
    { id: 4, display_name: 'Synthetic other list', privileges: [] },
  ]
  const writes = []
  await page.route('**/api/authorize/privileges', route => route.fulfill({ json: [privilege] }))
  await page.route('**/api/authorize/privilege-lists', route => route.fulfill({ json: lists }))
  await page.route('**/api/authorize/privilege-lists/*/privileges', route => {
    const request = route.request()
    const listId = Number(new URL(request.url()).pathname.split('/').at(-2))
    writes.push({ method: request.method(), listId, body: request.postDataJSON() })
    if (failFirstMove) {
      failFirstMove = false
      return route.fulfill({ status: 500, json: { detail: 'Synthetic failure' } })
    }
    privilege.privilege_list_id = request.method() === 'POST' ? listId : null
    for (const list of lists) list.privileges = privilege.privilege_list_id === list.id ? [{ ...privilege }] : []
    return route.fulfill({ json: lists.find(list => list.id === listId) })
  })
  await mount(page, 'core/authorize/components/PrivilegeListManager.vue', {
    privileges: ['READ_PRIVILEGE', ...(canManage ? ['MANAGE_PRIVILEGE'] : [])],
  })
  const unassigned = page.getByRole('region', { name: 'Unassigned privileges', exact: true })
  const card = name => page.locator('.privilege-list-card').filter({ hasText: name })
  const chip = page.getByText(privilege.display_name, { exact: true })
  await expect(chip).toBeVisible()
  return { privilege, writes, unassigned, card, chip }
}

for (const target of ['title', 'contents']) test(`privileges move between lists and back when dropped on ${target}`, async ({ page }) => {
  const { privilege, writes, unassigned, card, chip } = await privilegePage(page)
  const destination = card('Synthetic destination')
  const other = card('Synthetic other list')
  const dropTarget = list => target === 'title' ? list.locator('.privilege-list-name') : list.locator('.privilege-list-drop-zone')

  await chip.dragTo(dropTarget(destination))
  await expect(destination.getByText(privilege.display_name, { exact: true })).toBeVisible()
  expect(writes).toEqual([{ method: 'POST', listId: 3, body: { privilege_ids: [17] } }])
  await expect(unassigned.getByText(privilege.display_name, { exact: true })).toHaveCount(0)

  await chip.dragTo(dropTarget(other))
  await expect(other.getByText(privilege.display_name, { exact: true })).toBeVisible()
  expect(writes).toHaveLength(2)
  expect(writes[1]).toEqual({ method: 'POST', listId: 4, body: { privilege_ids: [17] } })

  await chip.dragTo(target === 'title' ? page.getByText('Unassigned privileges', { exact: true }) : unassigned)
  await expect(unassigned.getByText(privilege.display_name, { exact: true })).toBeVisible()
  expect(writes).toHaveLength(3)
  expect(writes[2]).toEqual({ method: 'DELETE', listId: 4, body: { privilege_ids: [17] } })
})

test('a failed privilege move preserves the source and can be retried', async ({ page }) => {
  const { privilege, writes, unassigned, card, chip } = await privilegePage(page, { failFirstMove: true })
  const destination = card('Synthetic destination')
  await chip.dragTo(destination.locator('.privilege-list-name'))
  await expect(page.getByText('Error while assigning', { exact: true })).toBeVisible()
  await expect(unassigned.getByText(privilege.display_name, { exact: true })).toBeVisible()
  await expect(destination.getByText(privilege.display_name, { exact: true })).toHaveCount(0)
  await chip.dragTo(destination.locator('.privilege-list-name'))
  await expect(destination.getByText(privilege.display_name, { exact: true })).toBeVisible()
  expect(writes).toHaveLength(2)
})

test('read-only viewers cannot drag privileges into a list', async ({ page }) => {
  const { privilege, writes, unassigned, card, chip } = await privilegePage(page, { canManage: false })
  const destination = card('Synthetic destination')
  await expect(page.getByRole('button', { name: 'New list', exact: true })).toHaveCount(0)
  await chip.dragTo(destination.locator('.privilege-list-name'))
  await expect(unassigned.getByText(privilege.display_name, { exact: true })).toBeVisible()
  expect(writes).toEqual([])
})

for (const width of [390, 1440]) test(`default labels follow the language and preserve custom text and edits at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const key = 'authorize.privilegeLists.defaults.goals'
  const lists = [
    { id: 3, display_name: key, translation_key: key, privileges: [] },
    { id: 4, display_name: key, translation_key: null, privileges: [] },
    { id: 5, display_name: 'Synthetic custom category', translation_key: null, privileges: [] },
  ]
  const writes = []
  await jsonRoute(page, '**/api/authorize/privileges', [])
  await page.route('**/api/authorize/privilege-lists', route => route.fulfill({ json: lists }))
  await page.route('**/api/authorize/privilege-lists/3', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    if (body.display_name !== lists[0].display_name) lists[0].translation_key = null
    Object.assign(lists[0], body)
    return route.fulfill({ json: lists[0] })
  })
  await mount(page, 'core/authorize/components/PrivilegeListManager.vue', { privileges: ['MANAGE_PRIVILEGE'] })
  const heading = label => page.locator('.privilege-list-name').filter({ hasText: new RegExp(`^${label}$`) })
  await expect(heading('Goals')).toBeVisible()
  await expect(heading(key)).toBeVisible()
  await page.evaluate(async () => { await (await import('/core/i18n/index.ts')).setLocale('fr') })
  await expect(heading('Objectifs')).toBeVisible()
  await expect(heading(key)).toBeVisible()
  await expect(heading('Synthetic custom category')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('localized-categories.png'), fullPage: true })

  const category = page.locator('.privilege-list-card').filter({ has: heading('Objectifs') })
  await category.getByRole('button', { name: 'Modifier', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('textbox')).toHaveValue('Objectifs')
  await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toEqual([{ display_name: key }])
  await category.getByRole('button', { name: 'Modifier', exact: true }).click()
  await dialog.getByRole('textbox').fill('Synthetic renamed default')
  await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  await expect(heading('Synthetic renamed default')).toBeVisible()
  await page.evaluate(async () => { await (await import('/core/i18n/index.ts')).setLocale('en') })
  await expect(heading('Synthetic renamed default')).toBeVisible()
  expect(writes[1]).toEqual({ display_name: 'Synthetic renamed default' })
})

test('role readers see the complete catalogue with translated and custom categories', async ({ page }, testInfo) => {
  const key = 'authorize.privilegeLists.defaults.goals'
  const privileges = [
    { id: 11, code: 'SYNTHETIC_READ', display_name: 'Synthetic read', privilege_list_id: 3 },
    { id: 12, code: 'SYNTHETIC_EDIT', display_name: 'Synthetic edit', privilege_list_id: 4 },
    { id: 13, code: 'SYNTHETIC_UNCLASSIFIED', display_name: null, privilege_list_id: null },
  ]
  await jsonRoute(page, '**/api/authorize/roles', [{
    id: 1, code: 'SYNTHETIC', display_name: 'Synthetic role', privileges: [privileges[0]],
  }])
  await jsonRoute(page, '**/api/authorize/privileges', privileges)
  await jsonRoute(page, '**/api/authorize/privilege-lists', [
    { id: 3, display_name: key, translation_key: key, privileges: [privileges[0]] },
    { id: 4, display_name: 'Synthetic custom group', translation_key: null, privileges: [privileges[1]] },
  ])
  const component = 'core/user/pages/users.vue'
  const options = { route: '/users', shell: true, privileges: ['READ_ROLE'] }
  await mount(page, component, { ...options, dark: false })
  const read = page.getByRole('switch', { name: 'Synthetic read' })
  const edit = page.getByRole('switch', { name: 'Synthetic edit' })
  await expect(read).toBeChecked()
  await expect(edit).not.toBeChecked()
  await expect(edit).toBeDisabled()
  await expect(page.getByRole('switch', { name: 'SYNTHETIC_UNCLASSIFIED' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Goals', exact: true })).toBeVisible()
  await page.evaluate(async () => { await (await import('/core/i18n/index.ts')).setLocale('fr') })
  await expect(page.getByRole('heading', { name: 'Objectifs', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Synthetic custom group', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('roles-desktop-light.png'), animations: 'disabled' })
  for (const [width, height, device] of [[1440, 1000, 'desktop'], [390, 844, 'mobile']]) {
    await page.setViewportSize({ width, height })
    await mount(page, component, { ...options, dark: true, locale: 'fr' })
    await expect(read).toBeChecked()
    const backdrop = page.locator('.q-drawer__backdrop')
    if (device === 'mobile' && await backdrop.isVisible()) {
      await backdrop.click({ position: { x: width - 10, y: 200 } })
    }
    await page.screenshot({ path: testInfo.outputPath(`roles-${device}-dark.png`), animations: 'disabled' })
  }
})

test('role switches save for the originating role and recover from a failed write', async ({ page }) => {
  const privilege = { id: 17, code: 'SYNTHETIC_EDIT', display_name: 'Synthetic edit', privilege_list_id: null }
  const roles = [
    { id: 1, code: 'FIRST', display_name: 'First role', privileges: [] },
    { id: 2, code: 'SECOND', display_name: 'Second role', privileges: [] },
  ]
  const writes = []
  let releaseWrite
  const delayedWrite = new Promise(resolve => { releaseWrite = resolve })
  await page.route('**/api/authorize/roles', route => route.fulfill({ json: roles }))
  await jsonRoute(page, '**/api/authorize/privilege-lists', [])
  await jsonRoute(page, '**/api/authorize/privileges', [privilege])
  await page.route('**/api/authorize/roles/*/privileges', async route => {
    const request = route.request()
    const roleId = Number(new URL(request.url()).pathname.split('/').at(-2))
    const method = request.method()
    writes.push({ method, roleId, body: request.postDataJSON() })
    if (writes.length === 1) return route.fulfill({ status: 409, json: { detail: 'Synthetic write refused' } })
    if (writes.length === 2) await delayedWrite
    const role = roles.find(role => role.id === roleId)
    role.privileges = method === 'POST' ? [privilege] : []
    return route.fulfill({ json: role })
  })
  await mount(page, 'core/user/pages/users.vue', { privileges: ['MANAGE_ROLE'] })
  await page.evaluate(() => window.testApp.patchStore(
    'core/authorize/stores/authorizeStore.ts', 'useAuthorizeStore', { activeRole: { id: 1, code: 'FIRST' } },
  ))
  const toggle = page.getByRole('switch', { name: 'Synthetic edit' })
  const first = page.getByRole('button', { name: 'First role' })
  const second = page.getByRole('button', { name: 'Second role' })
  await expect(first).toHaveAttribute('aria-pressed', 'true')
  await toggle.press('Space')
  await expect(page.getByText('Synthetic write refused')).toBeVisible()
  await expect(toggle).not.toBeChecked()
  try {
    const pending = page.waitForRequest('**/api/authorize/roles/1/privileges')
    await toggle.click()
    await pending
    await second.click()
    await expect(second).toHaveAttribute('aria-pressed', 'true')
    await expect(toggle).not.toBeChecked()
  } finally {
    releaseWrite()
  }
  await expect(toggle).toBeEnabled()
  await expect(second).toHaveAttribute('aria-pressed', 'true')
  await expect(toggle).not.toBeChecked()
  await first.click()
  await expect(toggle).toBeChecked()
  await toggle.click()
  await expect(toggle).not.toBeChecked()
  expect(writes).toEqual(['POST', 'POST', 'DELETE'].map(method => ({
    method, roleId: 1, body: { privilege_ids: [17] },
  })))
  await mount(page, 'core/user/pages/users.vue', { privileges: ['MANAGE_ROLE'] })
  await expect(toggle).not.toBeChecked()
})

test('the Privileges tab requires development mode and privilege catalogue access', async ({ page }) => {
  await jsonRoute(page, '**/api/authorize/privilege-lists', [])
  await jsonRoute(page, '**/api/authorize/privileges', [])
  const component = 'core/user/pages/users.vue'
  await mount(page, component, { privileges: ['READ_PRIVILEGE'] })
  const tab = page.getByRole('tab', { name: 'Privileges', exact: true })
  await expect(tab).toHaveCount(0)
  await page.evaluate(async component => {
    const { configurePrivilegeCatalogue } = await import('/core/authorize/access.ts')
    configurePrivilegeCatalogue(true)
    await window.testApp.mount({ component })
  }, component)
  await expect(tab).toBeVisible()
  await expect(tab).toHaveAttribute('aria-selected', 'true')
  await setPrivileges(page, [])
  await expect(tab).toHaveCount(0)
})
