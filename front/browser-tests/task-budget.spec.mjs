import { test, expect, mount } from './fixtures.mjs'

test('cost evidence keeps unknown totals visible and discards a late response from another task', async ({ page }) => {
  let release
  const summary = { calls: 2, estimated_calls: 0, unknown_calls: 1, running_calls: 0,
    failed_calls: 1, subscription_calls: 0, recorded_cost: .25, total_cost: null,
    inference_cost: null, quality: 'partial' }
  await page.route('**/api/tasks/*/costs', async route => {
    if (route.request().url().includes('/slow/')) await new Promise(resolve => { release = resolve })
    return route.fulfill({ json: { tasks_without_calls: 0, restricted: false,
      summary: { ...summary, recorded_cost: route.request().url().includes('/slow/') ? 999 : .25 }, by_purpose: {} } })
  })
  await mount(page, 'app/task/components/TaskCosts.vue', { props: { taskId: 'slow' } })
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ taskId: 'current' }))
  await expect(page.getByText('0.25', { exact: true })).toBeVisible()
  await expect(page.getByText('Partial', { exact: true })).toBeVisible()
  await expect(page.getByText('—', { exact: true })).toHaveCount(2)
  await expect(page.getByText(/1 with unknown cost/)).toBeVisible()
  release()
  await expect(page.getByText('999', { exact: true })).toHaveCount(0)
  await page.route('**/api/tasks/current/costs', route => route.fulfill({ status: 404, json: { detail: 'Synthetic scope denial' } }))
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Synthetic scope denial')
  await expect(page.getByText('0.25', { exact: true })).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: test.info().outputPath('cost-evidence.png'), fullPage: true })
})

test('usage is opt-in to read, shows unlimited budgets and clears inaccessible task data', async ({ page }) => {
  let requests = 0
  await page.route('**/api/tasks/*/budget', route => {
    requests++
    if (route.request().url().includes('/private/')) return route.fulfill({ status: 404, json: { detail: 'Task not found' } })
    return route.fulfill({ json: {
      enabled: false, scope: 'task_tree', provider_hard_cap: false,
      recorded_tokens: 123, recorded_cost: 0.25, active_phases: 2,
      reserved_tokens: 0, reserved_cost: 0,
      remaining_tokens: null, remaining_cost: null, remaining_seconds: null,
    } })
  })
  await mount(page, 'app/task/components/ExecutionResult.vue', { props: { taskId: 'visible', executionResult: null } })
  expect(requests).toBe(0)
  await page.getByRole('tab', { name: 'Details', exact: true }).click()
  await expect(page.getByText('No budget imposed', { exact: true })).toBeVisible()
  await expect(page.getByText('123 tokens · $0.2500', { exact: true })).toBeVisible()
  await expect(page.getByText('∞ tokens · $∞ · ∞ seconds', { exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ taskId: 'private' }))
  await expect(page.getByRole('alert')).toContainText('Task not found')
  await expect(page.getByText('123 tokens · $0.2500', { exact: true })).toHaveCount(0)
})
