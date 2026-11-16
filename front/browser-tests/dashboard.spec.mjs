import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const totals = cost => ({ tasks: 0, successful_tasks: 0, task_errors: 0, llm_calls: 0,
  llm_errors: 0, incidents: 0, tokens: 0, cost, inference_cost: cost,
  average_llm_duration: 0, task_success_rate: 0, llm_success_rate: 0 })

const activityComponent = 'app/index/components/DashboardLiveActivity.vue'
const activityPrivileges = ['TASK_ACCESS', 'LLM_CALL_ACCESS']
const avatar = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=', 'base64')

async function activityRoutes(page, agents = []) {
  const reads = { tasks: 0, calls: 0, avatars: 0 }
  await page.route('**/api/tasks/active?*', route => { reads.tasks++; return route.fulfill({ json: [] }) })
  await page.route('**/api/llm-calls/running?*', route => { reads.calls++; return route.fulfill({ json: [] }) })
  await jsonRoute(page, '**/api/agents/selection?scope=management', agents)
  await page.route('**/api/agents/*/avatar?*', route => {
    reads.avatars++
    return route.fulfill({ contentType: 'image/png', body: avatar })
  })
  return reads
}

async function observeAvatarUrls(page) {
  await page.addInitScript(() => {
    window.avatarUrls = { created: 0, revoked: 0 }
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL)
    URL.createObjectURL = blob => { window.avatarUrls.created++; return create(blob) }
    URL.revokeObjectURL = url => { window.avatarUrls.revoked++; return revoke(url) }
  })
}

test('activity preloads every avatar once and reopening reuses the shared image cache', async ({ page }) => {
  await page.clock.install()
  await observeAvatarUrls(page)
  const agents = Array.from({ length: 12 }, (_, i) => ({ id: i + 1, label: `Synthetic agent ${i}`, has_avatar: true, updated_at: '2026-11-01T12:00:00Z' }))
  const reads = await activityRoutes(page, agents)
  await mount(page, activityComponent, { privileges: activityPrivileges })
  await expect.poll(() => page.evaluate(() => window.avatarUrls.created)).toBe(12)
  expect(reads.avatars).toBe(12)
  await expect(page.locator('.activity-item')).toHaveCount(0)
  await page.evaluate(() => window.testApp.emitSocket('task.restore', { data: {} }))
  await expect.poll(() => reads.tasks).toBe(2)
  expect(reads.avatars).toBe(12)
  await page.clock.fastForward(120_000)
  await page.evaluate(component => window.testApp.mount({ component }), activityComponent)
  await expect.poll(() => page.evaluate(() => window.avatarUrls.created)).toBe(24)
  expect(reads.avatars).toBe(12)
  expect(await page.evaluate(() => window.avatarUrls.revoked)).toBe(12)
})

test('activity discards a read from former privileges and reconciles restored access without waiting for polling', async ({ page }) => {
  await page.clock.install()
  await activityRoutes(page)
  let releaseOld, releaseCurrent, reads = 0
  const old = new Promise(resolve => { releaseOld = resolve })
  const current = new Promise(resolve => { releaseCurrent = resolve })
  await page.route('**/api/tasks/active?*', async route => {
    const previous = ++reads === 1
    await (previous ? old : current)
    await route.fulfill({ json: [{ id: previous ? 'old-task' : 'current-task',
      label: previous ? 'Obsolete activity' : 'Current activity', status: 'EXEC', paused: false,
      objective: '<p>Synthetic activity</p>', created_at: '2026-11-01T12:00:00Z', updated_at: '2026-11-01T12:00:00Z' }] }).catch(error => {
        if (!previous) throw error
      })
  })
  await mount(page, activityComponent, { privileges: ['TASK_ACCESS'] })
  await expect.poll(() => reads).toBe(1)
  await setPrivileges(page, [])
  await setPrivileges(page, ['TASK_ACCESS'])
  await expect.poll(() => reads).toBe(2)
  await expect(page.getByText('Obsolete activity', { exact: true })).toHaveCount(0)
  releaseOld()
  releaseCurrent()
  await expect(page.getByText('Current activity', { exact: true })).toBeVisible()
  expect(reads).toBe(2)
})

test('activity pauses periodic reads while hidden and reconciles immediately on return', async ({ page }, info) => {
  await page.clock.install()
  const reads = await activityRoutes(page)
  await mount(page, activityComponent, { privileges: activityPrivileges })
  await expect(page.locator('.activity-empty')).toHaveCount(2)
  const before = { ...reads }
  const visibility = hidden => page.evaluate(value => {
    Object.defineProperty(document, 'hidden', { configurable: true, value })
    document.dispatchEvent(new Event('visibilitychange'))
  }, hidden)
  await visibility(true)
  await page.clock.runFor(60_000)
  await info.attach('hidden-activity-reads', { body: JSON.stringify({ tasks: reads.tasks - before.tasks, calls: reads.calls - before.calls }), contentType: 'application/json' })
  expect(reads.tasks).toBe(before.tasks)
  expect(reads.calls).toBe(before.calls)
  await page.evaluate(() => window.testApp.emitSocket('task.create', { data: {
    id: 'synthetic-live-task', label: 'Synthetic live task', status: 'EXEC', paused: false,
    objective: '<p>Preserved live progress</p>', created_at: '2026-11-01T12:00:00Z', updated_at: '2026-11-01T12:00:00Z',
  } }))
  await expect(page.getByText('Synthetic live task', { exact: true })).toBeVisible()
  await visibility(false)
  await expect.poll(() => reads.tasks).toBe(before.tasks + 1)
  await expect.poll(() => reads.calls).toBe(before.calls + 1)
  await expect(page.getByText('Synthetic live task', { exact: true })).toHaveCount(0)
})

test('leaving activity cancels queued avatar reads and retains no late Blob URL', async ({ page }) => {
  await page.clock.install()
  await observeAvatarUrls(page)
  await activityRoutes(page, Array.from({ length: 12 }, (_, i) => ({ id: i + 1, label: `Synthetic agent ${i}`, has_avatar: true })))
  let release, reads = 0
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/agents/*/avatar?*', async route => {
    reads++
    await gate
    await route.fulfill({ contentType: 'image/png', body: avatar }).catch(() => {})
  })
  await mount(page, activityComponent, { privileges: activityPrivileges })
  await expect.poll(() => reads).toBe(2)
  await page.evaluate(() => window.testApp.mount({ component: 'core/util/components/PanelState.vue', props: { state: 'empty', message: 'Synthetic replacement' } }))
  release()
  await page.clock.runFor(5000)
  expect(reads).toBe(2)
  expect(await page.evaluate(() => window.avatarUrls.created - window.avatarUrls.revoked)).toBe(0)
})

test('dashboard month navigation reuses data, refresh bypasses cache and revoked access clears it', async ({ page }) => {
  const requests = []
  await jsonRoute(page, '**/api/tasks/active?*', [])
  await jsonRoute(page, '**/api/llm-calls/running?*', [])
  await jsonRoute(page, '**/api/agents?*', [])
  await page.route('**/api/dashboard?*', async route => {
    const month = new URL(route.request().url()).searchParams.get('month')
    requests.push(month)
    const cost = month === '2026-07' ? (requests.filter(value => value === month).length > 1 ? 19 : 17) : 23
    await route.fulfill({ json: { month, available_months: [...new Set([month, '2026-08', '2026-07'])],
      totals: totals(cost), previous_totals: totals(0), daily_usage: [], agents: [] } })
  })
  await mount(page, 'app/index/components/HomeConnected.vue', { privileges: ['DASHBOARD_ACCESS'] })
  const select = page.getByRole('combobox', { name: 'Reporting month' })
  await expect(page.getByRole('button', { name: 'Refresh data', exact: true })).toBeVisible()
  await select.click()
  await page.getByRole('option', { name: 'July 2026', exact: true }).click()
  await expect(page.getByText('$17.00', { exact: true }).first()).toBeVisible()
  await select.click()
  await page.getByRole('option', { name: 'August 2026', exact: true }).click()
  await expect(page.getByText('$23.00', { exact: true }).first()).toBeVisible()
  const count = requests.length
  await select.click()
  await page.getByRole('option', { name: 'July 2026', exact: true }).click()
  await expect(page.getByText('$17.00', { exact: true }).first()).toBeVisible()
  expect(requests).toHaveLength(count)
  await page.getByRole('button', { name: 'Refresh data', exact: true }).click()
  await expect(page.getByText('$19.00', { exact: true }).first()).toBeVisible()
  expect(requests).toHaveLength(count + 1)
  await setPrivileges(page, [])
  await expect(select).toHaveCount(0)
  await expect(page.getByText('$19.00', { exact: true })).toHaveCount(0)
  await setPrivileges(page, ['DASHBOARD_ACCESS'])
  await expect(page.getByText('$19.00', { exact: true }).first()).toBeVisible()
  expect(requests).toHaveLength(count + 2)
})
