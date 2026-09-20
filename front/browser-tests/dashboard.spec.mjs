import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const totals = cost => ({ tasks: 0, successful_tasks: 0, task_errors: 0, llm_calls: 0,
  llm_errors: 0, incidents: 0, tokens: 0, cost, inference_cost: cost,
  average_llm_duration: 0, task_success_rate: 0, llm_success_rate: 0 })

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
  await mount(page, 'app/index/components/HomeConnected.vue', { privileges: ['TASK_ACCESS'] })
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
  await setPrivileges(page, ['TASK_ACCESS'])
  await expect(page.getByText('$19.00', { exact: true }).first()).toBeVisible()
  expect(requests).toHaveLength(count + 2)
})
