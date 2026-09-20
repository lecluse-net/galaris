import { test, expect, mount, setPrivileges, jsonRoute } from './fixtures.mjs'

test('Lab grants reveal only their own section and revocation removes access', async ({ page }) => {
  await mount(page, 'app/lab/pages/index.vue', { route: '/lab', privileges: ['BRIEFING_EVALUATION_ACCESS'] })
  await expect(page.getByRole('complementary', { name: 'Contextual help' })).toBeVisible()
  await expect(page.locator('a[href="/lab/briefing"]')).toBeVisible()
  await expect(page.locator('a[href="/lab/planner"]')).toHaveCount(0)
  await page.locator('a[href="/lab/briefing"]').press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/lab/briefing')
  await setPrivileges(page, ['PLANNER_EVALUATION_EDIT'])
  await expect(page.locator('a[href="/lab/briefing"]')).toHaveCount(0)
  await expect(page.locator('a[href="/lab/planner"]')).toBeVisible()
  await setPrivileges(page, ['INCIDENT_ACCESS'])
  await expect(page.locator('a[href^="/lab/"]')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/')
})

test('task analysis returns to the Lab using the visible back link', async ({ page }) => {
  await jsonRoute(page, '**/api/evaluation/config', { lab_llm_id: null, llms: [] })
  await jsonRoute(page, '**/api/evaluation/tasks', [])
  await jsonRoute(page, '**/api/evaluation/mechanisms', [])
  await jsonRoute(page, '**/api/evaluation/task_analysis/datasets', [])
  await mount(page, 'app/lab/pages/ai-evaluations.vue', { route: '/lab/ai-evaluations', privileges: ['EVALUATION_ACCESS'] })
  await expect(page.getByRole('complementary', { name: 'Contextual help' })).toHaveCount(0)
  await page.getByRole('link', { name: 'Back', exact: true }).press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/lab')
})

test('the incident journal searches occurrences and returns to preferences', async ({ page }) => {
  const queries = []
  await page.route('**/api/incidents?*', route => {
    queries.push(Object.fromEntries(new URL(route.request().url()).searchParams))
    return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } })
  })
  await mount(page, 'app/incident/pages/index.vue', { route: '/incident', privileges: ['INCIDENT_ACCESS'] })
  await expect(page.getByRole('complementary', { name: 'Contextual help' })).toHaveCount(0)
  await page.getByRole('textbox').first().fill('provider unavailable')
  await expect.poll(() => queries.at(-1)?.search).toBe('provider unavailable')
  await page.getByRole('link', { name: 'Back', exact: true }).press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/params')
})

test('message import selects its participants and invalidates the preview when the agent changes', async ({ page }) => {
  await jsonRoute(page, '**/api/evaluation/topic-classification/message-agents', [
    { id: 7, label: 'Alice', message_count: 1 }, { id: 8, label: 'Bob', message_count: 1 },
  ])
  const peopleRequests = []
  await page.route('**/api/evaluation/topic-classification/message-people?*', route => {
    const agent = new URL(route.request().url()).searchParams.get('agent_id')
    peopleRequests.push(agent)
    return route.fulfill({ json: [{ connection_id: Number(agent), user_id: 'human', label: 'Reviewer', platform: 'web', message_count: 1 }] })
  })
  const filters = []
  await page.route('**/api/evaluation/topic-classification/message-preview?*', route => {
    filters.push(Object.fromEntries(new URL(route.request().url()).searchParams))
    return route.fulfill({ json: { total_count: 1, truncated: false, messages: [{ journal_message_id: 'message-a', role: 'human', occurred_at: '2026-09-01T12:00:00Z', message: { text: 'Review this report', time: 1 }, detected_topic: null }] } })
  })
  await mount(page, 'app/lab/components/TopicMessageRangeImportDialog.vue', { props: { modelValue: false, datasetId: 'dataset-a' } })
  await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
  const agent = page.locator('[aria-label="AI"]')
  const person = page.getByRole('combobox', { name: 'Person', exact: true })
  const preview = page.getByRole('button', { name: 'Show messages', exact: true })
  const importExchange = page.getByRole('button', { name: 'Import this exchange', exact: true })
  await expect(preview).toBeDisabled()
  await agent.click()
  await page.getByRole('option', { name: /Alice/ }).click()
  await person.click()
  await page.getByRole('option', { name: /Reviewer/ }).click()
  await preview.click()
  await expect(page.getByText('Review this report', { exact: true })).toBeVisible()
  expect(filters[0]).toMatchObject({ agent_id: '7', connection_id: '7', user_id: 'human' })
  await expect(importExchange).toBeEnabled()
  await agent.click()
  await page.getByRole('option', { name: /Bob/ }).click()
  await expect.poll(() => peopleRequests).toEqual(['7', '8'])
  await expect(page.getByText('Review this report', { exact: true })).toHaveCount(0)
  await expect(preview).toBeDisabled()
  await expect(importExchange).toBeDisabled()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
