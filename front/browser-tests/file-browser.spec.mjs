import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { document, goal as goalFixture } from './data.mjs'

const component = 'app/file_share/pages/index.vue'
const routeComponent = 'test-support/browser/FileRouteHarness.vue'
const schemes = [
  { scheme: 'console', label: 'Console', capabilities: ['list', 'info', 'read'], native: true },
  { scheme: 'galaris', label: 'Galaris', capabilities: ['list', 'info', 'read'], native: true },
  { scheme: 'messenger', label: 'Messenger', capabilities: ['list', 'info', 'read'], native: true, root_listable: false },
  { scheme: 'https', label: 'HTTPS', capabilities: ['info', 'read'], native: true },
  { scheme: 'mail', label: 'Mail', capabilities: ['list', 'info', 'read'], native: false },
]
const entry = (uri, name, collection = false) => ({ uri, name, is_collection: collection,
  media_type: collection ? 'inode/directory' : 'text/plain', size: collection ? null : 24, capabilities: ['info', 'read'] })
const pageOf = (uri, entries, next_cursor = null) => ({ uri, entries, next_cursor, truncated: !!next_cursor })

for (const picker of [false, true]) for (const width of [1440, 390]) test(`system resource labels follow the locale in ${picker ? 'the picker' : '/files'} at ${width}px`, async ({ page }, testInfo) => {
  await setup(page)
  await page.setViewportSize({ width, height: 1000 })
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [
    { scheme: 'galaris', label: 'Galaris business resources', label_code: 'scheme_galaris', capabilities: ['list'], native: true },
  ])
  const task = { ...entry('galaris://task/', 'Tasks', true), label_code: 'collection_task' }
  const custom = entry('galaris://task/custom/', 'Tasks', true)
  await page.route('**/api/file-share/browser/entries?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    return route.fulfill({ json: pageOf(uri, uri === 'galaris://' ? [task, custom] : []) })
  })
  await mount(page, picker ? 'resourcePicker.vue' : routeComponent, {
    locale: 'fr', route: '/files?agent_id=7', browserHistory: true,
    props: picker ? { modelValue: true, agentId: 7 } : {}, privileges: ['FILE_ACCESS'],
  })
  await page.getByRole('button', { name: 'Ouvrir Ressources Galaris', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Ouvrir Tâches', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Ouvrir Tasks', exact: true })).toBeVisible()
  if (width >= 1024) await expect(page.locator('.file-tree')).toContainText('Tâches')
  if (picker) {
    await page.getByRole('checkbox', { name: 'Sélectionner Tâches', exact: true }).check()
    await expect(page.locator('.picker-selection')).toContainText('Tâches')
  }
  await page.getByRole('button', { name: 'Ouvrir Tâches', exact: true }).click()
  await expect(page.getByRole('navigation', { name: 'Navigation des fichiers' })).toContainText('Tâches')
  await page.screenshot({ path: testInfo.outputPath('resource-labels-light.png'), fullPage: true })
  await page.evaluate(async () => {
    const { setLocale } = await import('/core/i18n/index.ts')
    await setLocale('en')
  })
  await expect(page.getByRole('navigation', { name: 'File navigation' })).toContainText('Tasks')
  await expect(page.locator('.file-scheme-label')).toHaveText('Galaris resources')
  if (picker) await expect(page.locator('.picker-selection')).toContainText('Tasks')
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('resource-labels-dark.png'), fullPage: true })
})

async function setup(page) {
  await jsonRoute(page, '**/api/agents/selection?*', [
    { id: 7, label: 'Alice Example', has_avatar: false }, { id: 8, label: 'Bob Example', has_avatar: false },
  ])
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', schemes)
  await page.route('**/api/file-share/browser/thumbnail?*', route => route.fulfill({ status: 404 }))
}
async function selectAgent(page, name) {
  if (!await page.getByRole('combobox').count()) {
    await page.getByRole('button', { name: `Browse files for ${name}`, exact: true }).click()
    await expect(page.getByRole('combobox')).toBeVisible()
    return
  }
  await page.getByRole('combobox').click()
  await page.getByRole('option', { name, exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
}

for (const width of [1440, 390]) test(`Goals open their modal while cycles stay outside file navigation at ${width}px`, async ({ page }, testInfo) => {
  await setup(page)
  await page.setViewportSize({ width, height: 1000 })
  const id = '00000000-0000-4000-8000-000000000731'
  const folder = entry(`galaris://goal/${id}/`, 'Z Synthetic objective', true)
  const root = entry('galaris://goal/', 'Goals', true)
  const galaris = entry('galaris://', 'Galaris', true)
  const goal = { ...entry(`galaris://goal/${id}`, folder.name), media_type: 'application/vnd.galaris.goal+json', metadata: { sort_order: 0 } }
  const cycles = [1, 2, 10000].map(sequence => ({
    ...entry(`galaris://goal_cycle/00000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`, String(sequence).padStart(4, '0')),
    media_type: 'application/vnd.galaris.goal_cycle+json', metadata: { sort_order: sequence },
  }))
  const detail = { ...goalFixture, id, title: folder.name, description: '<p>Synthetic objective description</p>' }
  await jsonRoute(page, '**/api/goals/settings', { globally_paused: false, schedule_enabled: false, schedule: [], timezone: 'UTC', is_active: true })
  await jsonRoute(page, '**/api/goals/runtime-status', { globally_paused: false, schedule_enabled: false, timezone: 'UTC', is_active: true })
  await jsonRoute(page, '**/api/goals/tree', { items: [detail], total: 1 })
  await jsonRoute(page, `**/api/goals/${id}`, detail)
  await jsonRoute(page, `**/api/goals/${id}/cycles?*`, { items: [], total: 0, page: 1, page_size: 50 })
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await page.route('**/api/file-share/browser/entries?*', route => {
    const params = new URL(route.request().url()).searchParams
    const uri = params.get('uri')
    const listing = uri === folder.uri ? { ...pageOf(uri, params.has('cursor') ? cycles.slice(1) : [goal, cycles[0]], params.has('cursor') ? null : '2'), ancestors: [galaris, root, folder] }
      : pageOf(uri, uri === root.uri ? [goal] : [root])
    return route.fulfill({ json: listing })
  })
  await jsonRoute(page, '**/api/file-share/browser/info?*', cycles[0])
  await page.route('**/api/file-share/browser/content?*', route => route.fulfill({ contentType: cycles[0].media_type, body: JSON.stringify({ goal_id: id, sequence: 1 }) }))
  await mount(page, routeComponent, { route: '/files?agent_id=7&uri=' + encodeURIComponent(galaris.uri), browserHistory: true, privileges: ['FILE_ACCESS', 'GOAL_ACCESS'] })
  await expect(page.getByRole('button', { name: 'Open Goal cycles', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Open Goals', exact: true }).click()
  const names = page.locator('.file-main .file-tile-name')
  await expect(names).toHaveText([goal.name])
  await page.screenshot({ path: testInfo.outputPath('goals-light.png'), animations: 'disabled' })
  await page.getByRole('button', { name: `Open ${goal.name}`, exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Synthetic objective description')
  await page.keyboard.press('Escape')
  await page.evaluate(() => window.history.back())
  await expect(page.getByRole('button', { name: 'Open Goals', exact: true })).toBeVisible()
  await page.evaluate(() => window.history.forward())
  await expect(names).toHaveText([goal.name])
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('goals-dark.png'), animations: 'disabled' })
  // Old directory links or cached provider results must not reintroduce cycle tiles.
  await mount(page, routeComponent, { route: '/files?agent_id=7&uri=' + encodeURIComponent(folder.uri), browserHistory: true, privileges: ['FILE_ACCESS', 'GOAL_ACCESS'] })
  await expect(page.locator('.file-main .file-tile-name')).toHaveText([goal.name])
  await page.getByRole('button', { name: `Open ${goal.name}`, exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Synthetic objective description')
})

for (const width of [1440, 390]) test(`browser history restores agents and directories, including failed and late loads at ${width}px`, async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width, height: 1000 })
  let release
  const slow = new Promise(resolve => { release = resolve })
  await page.route('**/api/file-share/browser/entries?*', async route => {
    const params = new URL(route.request().url()).searchParams
    const uri = params.get('uri')
    if (uri === 'console://Reports/Slow/') {
      await slow
      return route.fulfill({ json: pageOf(uri, [entry(uri + 'Late.txt', 'Late.txt')]) }).catch(() => {})
    }
    if (uri === 'console://Reports/Denied/') return route.fulfill({ status: 403, json: { detail: 'Synthetic directory denial' } })
    return route.fulfill({ json: pageOf(uri, params.get('agent_id') === '8' ? [] : uri === 'console://' ? [
      entry('console://Reports/', 'Reports', true),
    ] : [entry(uri + 'Notes.txt', 'Notes.txt'), entry(uri + 'Slow/', 'Slow', true), entry(uri + 'Denied/', 'Denied', true)]) })
  })
  await mount(page, routeComponent, { route: '/files', browserHistory: true, privileges: ['FILE_ACCESS'] })
  const location = () => page.evaluate(() => ({
    agent: new URL(location.href).searchParams.get('agent_id'), uri: new URL(location.href).searchParams.get('uri'),
  }))
  const back = () => page.evaluate(() => window.history.back())
  const forward = () => page.evaluate(() => window.history.forward())
  await selectAgent(page, 'Alice Example')
  await expect.poll(location).toEqual({ agent: '7', uri: null })
  if (width < 1024) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.getByText('console://', { exact: true }).click()
  await expect.poll(location).toEqual({ agent: '7', uri: 'console://' })
  await page.getByRole('button', { name: 'Open Reports', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  await expect.poll(location).toEqual({ agent: '7', uri: 'console://Reports/' })
  // Selecting the current breadcrumb does not insert another browser-history entry.
  await page.getByRole('button', { name: 'Reports', exact: true }).click()
  await back()
  await expect.poll(location).toEqual({ agent: '7', uri: 'console://' })
  await expect(page.getByRole('button', { name: 'Open Reports', exact: true })).toBeVisible()
  await forward()
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Open Denied', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect.poll(location).toEqual({ agent: '7', uri: 'console://Reports/Denied/' })
  await back()
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  const requested = page.waitForRequest(request => request.url().includes('/browser/entries?') && new URL(request.url()).searchParams.get('uri') === 'console://Reports/Slow/')
  await page.getByRole('button', { name: 'Open Slow', exact: true }).click()
  await requested
  await expect.poll(location).toEqual({ agent: '7', uri: 'console://Reports/Slow/' })
  await back()
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  release()
  await expect.poll(location).toEqual({ agent: '7', uri: 'console://Reports/' })
  await expect(page.getByRole('button', { name: 'Open Late.txt', exact: true })).toHaveCount(0)
  await selectAgent(page, 'Bob Example')
  await expect.poll(location).toEqual({ agent: '8', uri: null })
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toHaveCount(0)
  await back()
  await expect(page.getByRole('combobox')).toHaveValue('Alice Example')
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  await back()
  await expect(page.getByRole('button', { name: 'Open Reports', exact: true })).toBeVisible()
  await back()
  await expect.poll(location).toEqual({ agent: '7', uri: null })
  await back()
  await expect(page.getByRole('button', { name: 'Browse files for Alice Example', exact: true })).toBeVisible()
  await expect(page.getByRole('combobox')).toHaveCount(0)
  await forward()
  await expect(page.getByRole('combobox')).toHaveValue('Alice Example')
  await forward()
  await expect(page.getByRole('button', { name: 'Open Reports', exact: true })).toBeVisible()
  await forward()
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  // Reopening the copied URL restores the same agent and folder from fresh state.
  const restored = new URL(page.url())
  await mount(page, routeComponent, { route: restored.pathname + restored.search, browserHistory: true, privileges: ['FILE_ACCESS'] })
  await expect(page.getByRole('combobox')).toHaveValue('Alice Example')
  await expect(page.getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
})

for (const width of [1440, 390]) test(`browser Back protects an unsaved Dataset opened from Files at ${width}px`, async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width, height: 1000 })
  const id = '00000000-0000-4000-8000-000000000321'
  const dataset = { id, uri: `data://${id}`, title: 'Synthetic history Dataset', content: '{"amount":0}', revision: 1,
    lock_version: 1, can_write: true, can_manage: true, can_delete: true, read_only: false,
    global_access: 0, group_access: 0, keywords: [], created_at: '2026-01-01T00:00:00Z' }
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'data', label: 'Datasets', capabilities: ['list'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('data://', [entry(dataset.uri, dataset.title)]))
  await jsonRoute(page, `**/api/datasets/${id}`, dataset)
  await jsonRoute(page, `**/api/datasets/${id}/owner`, { owner: null, options: [] })
  await jsonRoute(page, `**/api/datasets/${id}/sharing`, { lock_version: 1, can_manage: true, level: 'private', can_write: false,
    grants: [], options: [], owner: null, owner_groups: [] })
  await mount(page, routeComponent, { route: '/files?agent_id=7', browserHistory: true, privileges: ['FILE_ACCESS', 'DATASET_EDIT'] })
  if (width < 1024) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.getByText('data://', { exact: true }).click()
  await page.getByRole('button', { name: `Open ${dataset.title}`, exact: true }).click()
  const input = page.getByRole('textbox', { name: 'JSON content', exact: true })
  await expect(input).toHaveValue('{\n  "amount": 0\n}')
  await input.fill('{')
  await page.evaluate(() => window.history.back())
  const discard = page.getByRole('dialog').filter({ hasText: 'Discard unsaved changes before continuing?' })
  await discard.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(input).toHaveValue('{')
  await expect.poll(() => new URL(page.url()).searchParams.get('uri')).toBe('data://')
  await page.evaluate(() => window.history.back())
  await discard.getByRole('button', { name: 'Discard changes', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect.poll(() => new URL(page.url()).searchParams.get('uri')).toBeNull()
  await page.evaluate(() => window.history.forward())
  await page.getByRole('button', { name: `Open ${dataset.title}`, exact: true }).click()
  await expect(input).toHaveValue('{\n  "amount": 0\n}')
})

for (const width of [1440, 390]) test(`file and directory menus rename, confirm deletion, recover from errors and recheck permissions at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await setup(page)
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [schemes[0]])
  let items = [
    { ...entry('console://Folder/', 'Folder', true), capabilities: ['info', 'list', 'move', 'delete'] },
    { ...entry('console://Notes.txt', 'Notes.txt'), capabilities: ['info', 'read', 'move', 'delete'] },
    entry('console://Read-only.txt', 'Read-only.txt'),
  ]
  const mutations = []
  let denied = false
  await page.route('**/api/file-share/browser/entries?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    return route.fulfill({ json: pageOf(uri, uri === 'console://' ? items : []) })
  })
  await page.route('**/api/file-share/browser/entry?*', route => {
    const params = new URL(route.request().url()).searchParams
    const uri = params.get('uri')
    expect(params.get('agent_id')).toBe('7')
    mutations.push({ method: route.request().method(), uri, recursive: params.get('recursive') })
    if (denied) return route.fulfill({ status: 404, json: { detail: 'Synthetic revoked write access' } })
    if (route.request().method() === 'PATCH') {
      const name = route.request().postDataJSON().name
      const item = items.find(item => item.uri === uri)
      const renamed = 'console://' + encodeURIComponent(name) + (item.is_collection ? '/' : '')
      items = items.map(item => item.uri === uri ? { ...item, uri: renamed, name } : item)
      return route.fulfill({ json: { uri: renamed } })
    }
    items = items.filter(item => item.uri !== uri)
    return route.fulfill({ json: { uri, operation: 'delete', state: 'deleted' } })
  })
  await mount(page, component, { route: '/files?agent_id=7', privileges: ['FILE_ACCESS'] })
  if (width < 1024) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.getByText('console://', { exact: true }).click()
  await page.getByRole('button', { name: 'Open Notes.txt', exact: true }).click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: /Rename|Delete/ })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await setPrivileges(page, ['FILE_ACCESS', 'FILE_EDIT'])
  await page.getByRole('button', { name: 'Open Read-only.txt', exact: true }).click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: /Rename|Delete/ })).toHaveCount(0)
  await page.keyboard.press('Escape')
  const notes = page.getByRole('button', { name: 'Open Notes.txt', exact: true })
  await notes.focus()
  await page.keyboard.press('Shift+F10')
  await page.getByRole('menuitem', { name: 'Rename', exact: true }).click()
  await page.getByRole('dialog').getByRole('textbox').fill('Renamed.txt')
  await page.getByRole('dialog').getByRole('button', { name: 'Rename', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Open Renamed.txt', exact: true })).toBeVisible()
  if (width < 1024) await page.getByRole('button', { name: 'Open Renamed.txt', exact: true }).click({ button: 'right' })
  else await page.getByRole('button', { name: 'Actions for Renamed.txt', exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('file-actions.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(mutations.filter(item => item.method === 'DELETE')).toEqual([])
  await page.getByRole('button', { name: 'Open Renamed.txt', exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  denied = true
  await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Synthetic revoked write access')
  await expect(page.getByRole('button', { name: 'Open Renamed.txt', exact: true })).toBeVisible()
  denied = false
  await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Open Renamed.txt', exact: true })).toHaveCount(0)
  // The tree menu can rename the currently open directory, then delete it and return to its parent.
  await page.getByRole('button', { name: 'Open Folder', exact: true }).click()
  if (width < 1024) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  const tree = page.locator('.file-tree-entry', { hasText: 'Folder' })
  await tree.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Rename', exact: true }).click()
  await page.getByRole('dialog').getByRole('textbox').fill('Archive')
  await page.getByRole('dialog').getByRole('button', { name: 'Rename', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Archive', exact: true })).toHaveAttribute('aria-current', 'location')
  if (width < 1024) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.locator('.file-tree-entry', { hasText: 'Archive' }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('all its contents')
  await page.screenshot({ path: testInfo.outputPath('directory-delete.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Open Read-only.txt', exact: true })).toBeVisible()
  expect(mutations.at(-1)).toEqual({ method: 'DELETE', uri: 'console://Archive/', recursive: 'true' })
  await expect(page.locator('.file-tree-entry', { hasText: 'Archive' })).toHaveCount(0)
})

test('opening a cached internal file rereads its registered name before previewing it', async ({ page }) => {
  await setup(page)
  const uri = 'file://00000000-0000-4000-8000-000000000004'
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'file', label: 'Files', capabilities: ['list'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('file://', [entry(uri, 'Old name.txt')]))
  await jsonRoute(page, '**/api/file-share/browser/info?*', entry(uri, 'Current registered name.txt'))
  await page.route('**/api/file-share/browser/content?*', route => route.fulfill({ contentType: 'text/plain', body: 'Synthetic file content' }))
  await mount(page, component, { route: '/files?agent_id=7', privileges: ['FILE_ACCESS'] })
  await page.getByText('file://', { exact: true }).click()
  await page.getByRole('button', { name: 'Open Old name.txt', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Current registered name.txt', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Open Current registered name.txt', exact: true })).toBeVisible()
})

test('an existing file citation opens through authorized file sharing and retries denied access', async ({ page }) => {
  await setup(page)
  const uri = 'file://00000000-0000-4000-8000-000000000004'
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'file', label: 'Existing files', capabilities: ['list', 'info', 'read'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('file://', []))
  let denied = true, reads = 0
  await page.route('**/api/file-share/browser/info?*', route => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('agent_id')).toBe('7'); expect(params.get('uri')).toBe(uri)
    return route.fulfill(denied ? { status: 403, json: { detail: 'Synthetic unavailable file' } } : { json: entry(uri, 'Existing notes.txt') })
  })
  await page.route('**/api/file-share/browser/content?*', route => {
    reads++
    expect(new URL(route.request().url()).searchParams.get('uri')).toBe(uri)
    return route.fulfill({ contentType: 'text/plain', body: 'Existing source content' })
  })
  await mount(page, component, { route: `/files?agent_id=7&uri=${encodeURIComponent(uri)}`, privileges: ['FILE_ACCESS'] })
  await expect(page.getByRole('alert')).toBeVisible()
  expect(reads).toBe(0)
  denied = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Existing source content', { exact: true })).toBeVisible()
  expect(reads).toBe(1)
})

test('shared videos play from range URLs, release access on closing and reopen without a full download', async ({ page }) => {
  await setup(page)
  await mount(page, component, { privileges: ['FILE_ACCESS'] })
  const bytes = Buffer.from(await page.evaluate(async () => {
    const canvas = document.createElement('canvas')
    canvas.width = 64; canvas.height = 64
    const stream = canvas.captureStream(10)
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' })
    const chunks = []
    recorder.ondataavailable = event => chunks.push(event.data)
    const recording = new Promise(resolve => { recorder.onstop = () => resolve(new Blob(chunks)) })
    let frame = 0
    const timer = setInterval(() => {
      const context = canvas.getContext('2d')
      context.fillStyle = ++frame % 2 ? '#000000' : '#ffffff'
      context.fillRect(0, 0, 64, 64)
    }, 50)
    recorder.start()
    setTimeout(() => { clearInterval(timer); recorder.stop() }, 1000)
    const blob = await recording
    stream.getTracks().forEach(track => track.stop())
    return [...new Uint8Array(await blob.arrayBuffer())]
  }))
  const uri = 'console://Synthetic.webm'
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('console://', [
    { ...entry(uri, 'Synthetic.webm'), media_type: 'video/webm', size: 3 * 1024 ** 3 },
  ]))
  let issued = 0, released = 0, downloads = 0, mediaReads = 0
  await page.route('**/api/file-share/browser/content?*', route => { downloads++; return route.abort() })
  await page.route('**/api/file-share/browser/media?*', route => {
    issued++
    return route.fulfill({ json: { url: `/api/file-share/browser/media/synthetic-${issued}` } })
  })
  await page.route('**/api/file-share/browser/media/synthetic-*', route => {
    if (route.request().method() === 'DELETE') { released++; return route.fulfill({ status: 204 }) }
    mediaReads++
    const selected = route.request().headers().range?.match(/^bytes=(\d+)-(\d*)$/)
    expect(selected).toBeTruthy()
    const start = Number(selected[1]), end = selected[2] ? Number(selected[2]) : bytes.length - 1
    return route.fulfill({ status: 206, body: bytes.subarray(start, end + 1), headers: {
      'content-type': 'video/webm', 'accept-ranges': 'bytes',
      'content-range': `bytes ${start}-${end}/${bytes.length}`,
    } })
  })
  await selectAgent(page, 'Alice Example')
  await page.locator('.file-tree').getByText('Console', { exact: true }).click()
  for (let attempt = 1; attempt <= 2; attempt++) {
    await page.getByRole('button', { name: 'Open Synthetic.webm', exact: true }).click()
    const video = page.getByRole('dialog').locator('video')
    await expect(video).toBeVisible()
    await expect.poll(() => video.evaluate(element => element.readyState)).toBeGreaterThanOrEqual(1)
    await video.evaluate(element => { element.muted = true; return element.play() })
    await expect.poll(() => video.evaluate(element => element.currentTime)).toBeGreaterThan(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect.poll(() => released).toBe(attempt)
  }
  expect(issued).toBe(2)
  expect(mediaReads).toBeGreaterThanOrEqual(2)
  expect(downloads).toBe(0)
})

for (const width of [1440, 390]) test(`tree folders collapse and reopen on repeated clicks at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await setup(page)
  let reads = 0
  await page.route('**/api/file-share/browser/entries?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    if (uri === 'console://') return route.fulfill({ json: pageOf(uri, [entry('console://reports/', 'Reports', true)]) })
    reads++
    return route.fulfill({ json: pageOf(uri, [
      entry('console://reports/archive/', 'Archive', true), entry('console://reports/notes.txt', 'Notes.txt'),
    ]) })
  })
  await mount(page, component, { route: '/files?agent_id=7', privileges: ['FILE_ACCESS'] })
  if (width === 390) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.locator('.file-tree').getByText('Console', { exact: true }).click()
  const tree = page.locator('.file-tree')
  const reports = tree.getByText('Reports', { exact: true })
  await reports.click()
  if (width === 390) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await expect(tree.getByText('Archive', { exact: true })).toBeVisible()
  await reports.click()
  await expect(tree.getByText('Archive', { exact: true })).toBeHidden()
  await expect(page.locator('.file-main').getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  await reports.click()
  await expect(tree.getByText('Archive', { exact: true })).toBeVisible()
  const reportsItem = tree.getByRole('treeitem', { name: 'Reports', exact: true })
  await reportsItem.press('Enter')
  await expect(tree.getByText('Archive', { exact: true })).toBeHidden()
  await reportsItem.press('Enter')
  await expect(tree.getByText('Archive', { exact: true })).toBeVisible()
  expect(reads).toBe(1)
})

for (const width of [1440, 390]) test(`browse folders, scroll, retry and preview with the keyboard at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await setup(page)
  let failContinuation = true
  const calls = []
  await page.route('**/api/file-share/browser/entries?*', route => {
    const params = new URL(route.request().url()).searchParams
    const uri = params.get('uri'), cursor = params.get('cursor')
    calls.push({ uri, cursor })
    if (uri === 'console://' && cursor) return route.fulfill({ json: pageOf(uri, [entry('console://reports/', 'Reports', true)]) })
    if (uri === 'console://') return route.fulfill({ json: pageOf(uri, [
      entry('console://summary.txt', 'Summary.txt'),
      entry('console://.cache/', '.cache', true),
      entry('console://.settings', '.settings'),
    ], 'next-folders') })
    if (cursor && failContinuation) return route.fulfill({ status: 502, json: { detail: 'Synthetic unavailable provider' } })
    if (cursor) return route.fulfill({ json: pageOf(uri, [entry('console://reports/final.txt', 'Final report.txt')]) })
    return route.fulfill({ json: pageOf(uri, Array.from({ length: 50 }, (_, n) => entry(`console://reports/report-${n}.txt`, `Report ${n}.txt`)), 'next-reports') })
  })
  await page.route('**/api/file-share/browser/content?*', route => route.fulfill({ contentType: 'text/plain', body: 'Synthetic report preview content' }))
  await mount(page, component, { privileges: ['FILE_ACCESS'], dark: width === 390 })
  await expect(page.getByRole('button', { name: 'Browse files for Alice Example', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser-agents.png'), fullPage: true })
  await selectAgent(page, 'Alice Example')
  if (width === 390) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.locator('.file-tree').getByText('Console', { exact: true }).click()
  const main = page.locator('.file-main')
  await expect(main.getByRole('button', { name: 'Open Reports', exact: true })).toBeVisible()
  await expect(page.getByText('.cache', { exact: true })).toHaveCount(0)
  await expect(page.getByText('.settings', { exact: true })).toHaveCount(0)
  await expect(page.locator('.file-tree').getByText('Reports', { exact: true })).toBeInViewport()
  expect(calls.filter(call => call.uri === 'console://' && call.cursor === 'next-folders')).toHaveLength(1)
  await page.screenshot({ path: testInfo.outputPath('file-browser-locations.png'), fullPage: true })
  await main.getByRole('button', { name: 'Open Reports', exact: true }).click()
  await expect(main.getByRole('button', { name: 'Open Report 0.txt', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser-entries.png'), fullPage: true })
  await expect(page.locator('.file-tree').getByText('Report 0.txt', { exact: true })).toHaveCount(0)
  await main.locator('.file-grid').getByRole('button').last().scrollIntoViewIfNeeded()
  await expect(main.getByRole('alert')).toBeVisible()
  failContinuation = false
  await main.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(main.getByRole('button', { name: 'Open Final report.txt', exact: true })).toBeVisible()
  expect(calls.filter(call => call.cursor === 'next-reports')).toHaveLength(2)
  await expect(main.getByRole('button', { name: 'Open Report 0.txt', exact: true })).toHaveCount(1)
  const final = main.getByRole('button', { name: 'Open Final report.txt', exact: true })
  await final.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText('Synthetic report preview content', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await main.getByRole('navigation', { name: 'File navigation', exact: true }).getByRole('button', { name: 'console://', exact: true }).click()
  await expect(main.getByRole('button', { name: 'Open Reports', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser.png'), fullPage: true })
})

test('a Galaris document opens its existing modal with the selected agent scope', async ({ page }) => {
  await setup(page)
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('galaris://', [
    { ...entry('document://doc-a', 'Synthetic document'), media_type: 'text/html' },
  ]))
  const actors = []
  await page.route('**/api/documents/doc-a?*', route => {
    actors.push(new URL(route.request().url()).searchParams.get('agent_id'))
    return route.fulfill({ json: { item: { ...document, title: 'Synthetic document' } } })
  })
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/content/revisions?*', { items: [], total: 0 })
  await mount(page, component, { privileges: ['FILE_ACCESS'] })
  await selectAgent(page, 'Alice Example')
  await page.locator('.file-tree').getByText('Galaris', { exact: true }).click()
  await page.locator('.file-main').getByRole('button', { name: 'Open Synthetic document', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Initial body', { exact: true })).toBeVisible()
  expect(actors).toContain('7')
  await page.locator('.q-dialog__backdrop').last().click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

for (const width of [1440, 390]) test(`document folders restore their named lineage from stable URIs at ${width}px`, async ({ page }, testInfo) => {
  await setup(page)
  await page.setViewportSize({ width, height: 1000 })
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [
    { scheme: 'document', label: 'Documents', capabilities: ['list', 'info', 'read'], native: true },
  ])
  const root = entry('document://', 'Documents', true)
  const parent = entry('document://folders/11111111-1111-4111-8111-111111111111/', 'Synthetic parent', true)
  const child = entry('document://folders/22222222-2222-4222-8222-222222222222/', 'Synthetic child', true)
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/file-share/browser/entries?*', async route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    if (uri === child.uri) await pending
    const ancestors = uri === child.uri ? [root, parent, child] : uri === parent.uri ? [root, parent] : [root]
    const entries = uri === child.uri ? [] : uri === parent.uri ? [child] : [parent, entry('document://doc-unfiled', 'Synthetic unfiled')]
    return route.fulfill({ json: { ...pageOf(uri, entries), ancestors } })
  })
  const location = '/files?agent_id=7&uri=' + encodeURIComponent(child.uri)
  await mount(page, routeComponent, { route: location, browserHistory: true, privileges: ['FILE_ACCESS'] })
  const navigation = page.getByRole('navigation', { name: 'File navigation', exact: true })
  await expect(navigation.getByRole('button', { name: 'Documents', exact: true })).toBeVisible()
  await expect(navigation).not.toContainText('22222222-2222-4222-8222-222222222222')
  release()
  await expect(navigation.getByRole('button', { name: child.name, exact: true })).toBeVisible()
  await expect(navigation.getByRole('button', { name: parent.name, exact: true })).toBeVisible()
  await navigation.getByRole('button', { name: parent.name, exact: true }).click()
  const openChild = page.getByRole('button', { name: `Open ${child.name}`, exact: true })
  await expect(openChild).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('document-folders-light.png'), animations: 'disabled' })
  await openChild.focus()
  await page.keyboard.press('Enter')
  await expect(navigation.getByRole('button', { name: child.name, exact: true })).toHaveAttribute('aria-current', 'location')
  await page.evaluate(() => window.history.back())
  await expect(openChild).toBeVisible()
  await navigation.getByRole('button', { name: 'Documents', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Open Synthetic unfiled', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: `Open ${child.name}`, exact: true })).toHaveCount(0)
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('document-folders-dark.png'), animations: 'disabled' })
})

test('agent changes discard late responses and browsable scheme accordions reopen with empty states', async ({ page }, testInfo) => {
  await setup(page)
  let failMail = true
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/file-share/browser/entries?*', async route => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('uri') === 'mail://' && failMail) return route.fulfill({ status: 502, json: { detail: 'Synthetic unavailable mail provider' } })
    if (params.get('agent_id') === '7') {
      await pending
      return route.fulfill({ json: pageOf('console://', [entry('console://private.txt', 'Alice private.txt')]) }).catch(() => {})
    }
    return route.fulfill({ json: pageOf('console://', [
      entry('console://.cache/', '.cache', true), entry('console://.settings', '.settings'),
    ]) })
  })
  await mount(page, component, { privileges: ['FILE_ACCESS'] })
  await selectAgent(page, 'Alice Example')
  const requested = page.waitForRequest(request => request.url().includes('/browser/entries'))
  await page.locator('.file-tree').getByText('Console', { exact: true }).click()
  await requested
  await selectAgent(page, 'Bob Example')
  release()
  await page.locator('.file-tree').getByText('Console', { exact: true }).click()
  await expect(page.getByText('This directory is empty.', { exact: true })).toBeVisible()
  const consoleHeader = page.getByRole('button', { name: 'Console', exact: true })
  await expect(consoleHeader).toHaveAttribute('aria-expanded', 'true')
  await page.screenshot({ path: testInfo.outputPath('file-browser-empty.png'), fullPage: true })
  await consoleHeader.focus()
  await page.keyboard.press('Enter')
  await expect(consoleHeader).toHaveAttribute('aria-expanded', 'false')
  await page.keyboard.press('Enter')
  await expect(consoleHeader).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('Alice private.txt', { exact: true })).toHaveCount(0)
  for (const scheme of ['Messenger', 'HTTPS']) {
    await expect(page.getByRole('button', { name: scheme, exact: true })).toHaveCount(0)
  }
  await page.getByText('Mail', { exact: true }).click()
  const main = page.locator('.file-main')
  await expect(main.getByRole('alert')).toBeVisible()
  await expect(main.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser-mail-error.png'), fullPage: true })
  failMail = false
  await main.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(main.getByText('This directory is empty.', { exact: true })).toBeVisible()
  await expect(main.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Clear', exact: true })).toHaveCount(0)
  await expect(page.getByRole('combobox')).toHaveValue('Bob Example')
})

for (const width of [1440, 390]) test(`file locations recover from errors and open without the tree (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  let failed = true
  await page.route('**/api/file-share/browser/schemes?*', route => route.fulfill(failed
    ? { status: 503, json: { detail: 'Synthetic provider failure' } }
    : { json: [
      { scheme: 'file', label: 'Synthetic files', capabilities: ['list', 'info'], native: true },
      { scheme: 'https', label: 'Direct access', capabilities: ['read', 'info'], native: false },
      { scheme: 'hidden', label: 'Unlistable root', capabilities: ['list'], root_listable: false, native: false },
    ] }))
  const folder = { uri: 'file://reports/', name: 'Synthetic reports', is_collection: true, media_type: '', size: null, capabilities: ['list', 'info'] }
  await jsonRoute(page, '**/api/file-share/browser/entries?*', { entries: [folder], truncated: false, next_cursor: null })
  await mount(page, 'app/file_share/components/AgentFileBrowser.vue', {
    props: { agentId: 7 }, privileges: ['FILE_ACCESS'], containerStyle: { height: '100vh', display: 'flex' },
  })
  const main = page.getByRole('main')
  await expect(main.getByRole('alert')).toBeVisible()
  failed = false
  await main.getByRole('button', { name: 'Retry', exact: true }).click()
  const root = main.getByRole('button', { name: 'Open Synthetic files', exact: true })
  await expect(root).toBeVisible()
  await expect(main.getByRole('button', { name: /Direct access|Unlistable root/ })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('locations.png') })
  await root.focus()
  await page.keyboard.press('Enter')
  const entry = main.getByRole('button', { name: 'Open Synthetic reports', exact: true })
  await expect(entry).toBeVisible()
  await entry.focus()
  await page.keyboard.press('Shift+F10')
  await expect(page.getByRole('menuitem', { name: 'Copy reference', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('files.png') })
  // Restoring an empty location must reveal the roots again without remounting.
  await page.evaluate(async () => {
    await window.testApp.setProps({ initialUri: 'file://' })
    await window.testApp.setProps({ initialUri: null })
  })
  await expect(root).toBeVisible()
})

test('the attachment picker opens locations directly and handles an empty scheme catalogue', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [])
  const options = { props: { agentId: 7, selection: true }, containerStyle: { height: '100vh', display: 'flex' } }
  await mount(page, 'app/file_share/components/AgentFileBrowser.vue', options)
  await expect(page.getByRole('main').getByText('No visible directories.', { exact: true })).toBeVisible()
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [
    { scheme: 'file', label: 'Synthetic files', capabilities: ['list', 'info'], native: true },
  ])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', { entries: [], truncated: false, next_cursor: null })
  await mount(page, 'app/file_share/components/AgentFileBrowser.vue', options)
  await page.getByRole('main').getByRole('button', { name: 'Open Synthetic files', exact: true }).click()
  await expect(page.getByRole('main').getByText('This directory is empty.', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:selected'))).toEqual([])
})
