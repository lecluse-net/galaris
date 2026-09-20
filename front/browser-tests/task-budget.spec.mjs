import { test, expect, mount } from './fixtures.mjs'

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
