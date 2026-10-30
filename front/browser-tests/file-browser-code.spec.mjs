import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const id = '11111111-1111-4111-8111-111111111111'
const workspace = { id, uri: `galaris://code/${id}`, label: 'work/synthetic-project', mode: 'edit' }

async function setup(page, { codeAccess = true, denied = false } = {}) {
  const opens = []
  await jsonRoute(page, '**/api/agents/selection?*', [{ id: 7, label: 'Synthetic Agent', has_avatar: false }])
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [
    { scheme: 'galaris', label: 'Galaris', capabilities: ['list', 'info', 'read'], native: true },
  ])
  await page.route('**/api/file-share/browser/entries?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    return route.fulfill({ json: { uri, entries: [{ uri: workspace.uri, name: `code-${id}.json`,
      media_type: 'application/vnd.galaris.code+json', is_collection: false, capabilities: ['info', 'read'],
      size: null, metadata: { label: workspace.label } }], truncated: false, next_cursor: null } })
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
    route: '/files?agent_id=7&uri=galaris%3A%2F%2Fcode%2F',
    privileges: ['FILE_ACCESS', ...(codeAccess ? ['CODE_ACCESS'] : [])],
  })
  return { opens, allow: () => { denied = false } }
}

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
