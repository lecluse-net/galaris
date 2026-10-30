import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const id = '11111111-1111-4111-8111-111111111111'
const workspace = { id, uri: `galaris://code/${id}`, label: 'work/synthetic-project', mode: 'edit' }

async function setup(page, { codeAccess = true, denied = false, consoleDirectory = false, worktree = false } = {}) {
  const opens = []
  const registrations = [], inspections = []
  await jsonRoute(page, '**/api/agents/selection?*', [{ id: 7, label: 'Synthetic Agent', has_avatar: false }])
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [
    { scheme: 'galaris', label: 'Galaris', capabilities: ['list', 'info', 'read'], native: true },
    ...(consoleDirectory ? [{ scheme: 'console', label: 'Console', capabilities: ['list', 'info', 'read'], native: true }] : []),
  ])
  const directory = { uri: 'console://work/synthetic%20project/', name: 'Synthetic project', is_collection: true,
    media_type: 'inode/directory', capabilities: ['info', 'list'], size: null }
  const ordinary = { ...directory, uri: 'console://ordinary/', name: 'Ordinary directory' }
  await page.route('**/api/file-share/browser/entries?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    return route.fulfill({ json: { uri, entries: consoleDirectory ? (uri === 'console://' ? [directory, ordinary] : []) : [{ uri: workspace.uri, name: `code-${id}.json`,
      media_type: 'application/vnd.galaris.code+json', is_collection: false, capabilities: ['info', 'read'],
      size: null, metadata: { label: workspace.label } }], truncated: false, next_cursor: null } })
  })
  await page.route('**/api/file-share/browser/info?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    inspections.push(uri)
    return uri === directory.uri + '.git'
      ? route.fulfill({ json: { ...directory, uri, name: '.git', is_collection: !worktree } })
      : route.fulfill({ status: 404, json: { detail: 'Resource unavailable' } })
  })
  await page.route('**/api/code/agents/7/repository?*', route => {
    registrations.push({ method: route.request().method(), uri: new URL(route.request().url()).searchParams.get('uri') })
    return denied ? route.fulfill({ status: 403, json: { detail: 'Repository unavailable' } }) : route.fulfill({ json: workspace })
  })
  await page.route('**/api/file-share/browser/thumbnail?*', route => route.fulfill({ status: 404 }))
  await page.route(`**/api/code/workspaces/${id}/sessions`, route => {
    opens.push(id)
    return denied ? route.fulfill({ status: 403, json: { detail: 'Synthetic denied repository' } })
      : route.fulfill({ json: { id: 'synthetic-session', workspace, url: 'http://localhost:8000/synthetic-code-editor', expires_at: '2099-01-01T00:00:00Z' } })
  })
  await jsonRoute(page, '**/api/code/sessions/synthetic-session/navigate', { state: 'requested' })
  await jsonRoute(page, '**/api/code/sessions/synthetic-session/heartbeat', { workspace })
  await page.route('**/synthetic-code-editor', route => route.fulfill({ contentType: 'text/html', body:
    '<textarea aria-label="Synthetic source"></textarea><script>parent.postMessage({type:"galaris.code.ready",session:"synthetic-session"},location.origin)</script>' }))
  await mount(page, 'test-support/browser/FileCodeHarness.vue', {
    route: consoleDirectory ? '/files?agent_id=7&uri=console%3A%2F%2F' : '/files?agent_id=7&uri=galaris%3A%2F%2Fcode%2F',
    privileges: ['FILE_ACCESS', ...(codeAccess ? ['CODE_ACCESS'] : [])],
  })
  return { opens, registrations, inspections, allow: () => { denied = false } }
}

for (const width of [1440, 390]) test(`Console repository context actions open the retained editor at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const state = await setup(page, { consoleDirectory: true, worktree: width === 390 })
  const folder = page.getByRole('button', { name: 'Open Synthetic project', exact: true })
  await folder.click({ button: 'right' })
  const action = page.getByRole('menuitem', { name: 'Open code editor', exact: true })
  await expect(action).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('console-context-light.png') })
  await page.evaluate(() => window.testApp.dark(true))
  await page.keyboard.press('Escape')
  await folder.click({ button: 'right' })
  await expect(action).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('console-context-dark.png') })
  await action.click()
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic source' })
  await source.fill('Synthetic unsaved console change')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeEnabled()
  await folder.focus()
  await expect(folder).toBeFocused()
  await page.keyboard.press('Shift+F10')
  await expect(action).toBeVisible()
  await action.click()
  await expect(source).toHaveValue('Synthetic unsaved console change')
  expect(state.opens).toEqual([id])
  expect(state.registrations).toEqual(Array(2).fill({ method: 'POST', uri: 'console://work/synthetic%20project/' }))
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await folder.click()
  await expect(page.getByRole('navigation', { name: 'File navigation' })).toContainText('synthetic project')
  await page.locator('.file-scroll').focus()
  await page.keyboard.press('Shift+F10')
  await expect(page.getByRole('menuitem', { name: 'Open code editor', exact: true })).toBeVisible()
})

test('Console repository access denial leaves the browser usable and permits retry', async ({ page }) => {
  const state = await setup(page, { consoleDirectory: true, denied: true })
  const folder = page.getByRole('button', { name: 'Open Synthetic project', exact: true })
  await page.getByRole('button', { name: 'Actions for Synthetic project', exact: true }).click()
  await page.getByRole('menuitem', { name: /code editor/ }).click()
  await expect(page.getByRole('alert')).toContainText('Repository unavailable')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  state.allow()
  await folder.click({ button: 'right' })
  await page.getByRole('menuitem', { name: /code editor/ }).click()
  await expect(page.frameLocator('iframe.code-editor-frame').getByRole('textbox')).toBeVisible()
  expect(state.registrations).toHaveLength(2)
})

test('changing folders while Console registration is pending ignores its late result', async ({ page }) => {
  await setup(page, { consoleDirectory: true })
  let pending
  await page.route('**/api/code/agents/7/repository?*', route => { pending = route })
  await page.getByRole('button', { name: 'Open Synthetic project', exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: /code editor/ }).click()
  await expect.poll(() => Boolean(pending)).toBe(true)
  await page.getByRole('button', { name: 'Open Ordinary directory', exact: true }).click()
  await expect(page.getByRole('navigation', { name: 'File navigation' })).toContainText('Ordinary directory')
  await pending.fulfill({ json: workspace })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(0)
})

test('ordinary Console folders keep their regular actions', async ({ page }) => {
  const state = await setup(page, { consoleDirectory: true })
  await page.getByRole('button', { name: 'Open Ordinary directory', exact: true }).click({ button: 'right' })
  await expect.poll(() => state.inspections.includes('console://ordinary/.git')).toBe(true)
  await expect(page.getByRole('menuitem', { name: /code editor/ })).toHaveCount(0)
  await expect(page.getByRole('menuitem', { name: 'Open', exact: true })).toBeVisible()
  expect(state.registrations).toEqual([])
})

test('Console context menus do not inspect or open repositories without Code access', async ({ page }) => {
  const state = await setup(page, { consoleDirectory: true, codeAccess: false })
  await page.getByRole('button', { name: 'Open Synthetic project', exact: true }).click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: 'Open', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: /code editor/ })).toHaveCount(0)
  expect(state.inspections).toEqual([])
  expect(state.registrations).toEqual([])
})

for (const width of [1440, 390]) test(`a repository opens its retained editor from Files at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const state = await setup(page)
  const repository = page.getByRole('button', { name: `Open ${workspace.label}`, exact: true })
  await repository.click()
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic source' })
  await source.fill('Synthetic unsaved change')
  await page.getByRole('dialog').evaluate(element => Promise.allSettled(element.getAnimations({ subtree: true }).map(animation => animation.finished)))
  await page.screenshot({ path: testInfo.outputPath('repository-editor-light.png') })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('repository-editor-dark.png') })
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('iframe.code-editor-frame')).toBeHidden()
  await repository.focus()
  await page.keyboard.press('Enter')
  await expect(source).toHaveValue('Synthetic unsaved change')
  await expect(page.locator('iframe.code-editor-frame')).toBeVisible()
  expect(state.opens).toEqual([id])
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('Files cannot start an editor without Code access', async ({ page }) => {
  const state = await setup(page, { codeAccess: false })
  await page.getByRole('button', { name: `Open ${workspace.label}`, exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(0)
  expect(state.opens).toEqual([])
})

test('repository access denial can be retried without leaving Files', async ({ page }) => {
  const state = await setup(page, { denied: true })
  await page.getByRole('button', { name: `Open ${workspace.label}`, exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(0)
  state.allow()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.frameLocator('iframe.code-editor-frame').getByRole('textbox')).toBeVisible()
  expect(state.opens).toEqual([id, id])
})

test('closing Files editor during opening prevents a late session from showing it again', async ({ page }) => {
  await setup(page)
  let pending
  await page.route(`**/api/code/workspaces/${id}/sessions`, route => { pending = route })
  const repository = page.getByRole('button', { name: `Open ${workspace.label}`, exact: true })
  await repository.click()
  await expect.poll(() => Boolean(pending)).toBe(true)
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await pending.fulfill({ json: { id: 'synthetic-session', workspace,
    url: 'http://localhost:8000/synthetic-code-editor', expires_at: '2099-01-01T00:00:00Z' } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('iframe.code-editor-frame')).toBeHidden()
  await repository.click()
  await expect(page.frameLocator('iframe.code-editor-frame').getByRole('textbox')).toBeVisible()
})
