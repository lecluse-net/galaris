import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('the process catalogue loads summaries and opens its editor with the real API', async ({ page, request }, testInfo) => {
  const errors = collectPageErrors(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const created = await request.post('/api/processes/internal/definitions', { headers: { Authorization: `Bearer ${session.access_token}` }, data: {
    agent_id: fixture.agent_id, title: 'Synthetic catalogue process', owner: 'user', graph: {
      schema_version: 'galaris.bpmn/v1', nodes: [{ id: 'start', kind: 'start' }, { id: 'end', kind: 'end' }],
      flows: [{ id: 'finish', source: 'start', target: 'end' }],
    },
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const definition = await created.json()
  const runIds = []
  for (let index = 0; index < 5; index++) {
    const launched = await request.post(`/api/processes/internal/definitions/${definition.code}/runs`, {
      headers: { Authorization: `Bearer ${session.access_token}` }, data: { agent_id: fixture.agent_id, input: {} },
    })
    expect(launched.ok(), await launched.text()).toBeTruthy()
    runIds.push((await launched.json()).run_id)
  }
  const fullAgentReads = []
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/agents') fullAgentReads.push(request.method()) })
  const selected = page.waitForResponse(response => new URL(response.url()).pathname === '/api/agents/selection')
  const definitions = page.waitForResponse(response => new URL(response.url()).pathname === '/api/processes/definitions')
  const runs = page.waitForResponse(response => new URL(response.url()).pathname === '/api/processes/internal/runs')
  const started = Date.now()
  await page.goto('/process')
  const link = page.getByRole('link', { name: 'Synthetic catalogue process', exact: true })
  await expect(link).toBeVisible()
  const catalogueMs = Date.now() - started
  expect((await runs).ok()).toBeTruthy()
  for (const id of runIds) await expect(page.locator('.native-runs-table').getByRole('link', { name: new RegExp(id) })).toBeVisible()
  const executionsMs = Date.now() - started
  expect((await selected).ok()).toBeTruthy()
  expect((await definitions).ok()).toBeTruthy()
  expect(fullAgentReads).toEqual([])
  await testInfo.attach('process-catalogue-timing.json', { body: JSON.stringify({ catalogue_ms: catalogueMs, executions_ms: executionsMs, execution_count: runIds.length }), contentType: 'application/json' })
  await page.screenshot({ path: testInfo.outputPath('process-catalogue.png'), animations: 'disabled' })
  await link.click()
  await expect(page).toHaveURL(new RegExp(`/process/internal/${definition.code}$`))
  await expect(page.getByRole('textbox', { name: /^(Title|Titre)$/ })).toHaveValue('Synthetic catalogue process')
  expect(errors()).toEqual([])
})
