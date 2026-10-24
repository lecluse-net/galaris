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
  const checkRunSummaries = async () => {
    const response = await request.get(`/api/processes/runs?process_id=${definition.id}&page_size=500`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    const summaries = await response.json()
    expect(summaries.total).toBe(runIds.length)
    expect(summaries.items.map(run => run.id).sort()).toEqual([...runIds].sort())
    for (const run of summaries.items) {
      expect(run.process_label).toBe('Synthetic catalogue process')
      expect(run.workflow_id).toBe(definition.code)
      expect(run.launcher_agent_id).toBe(fixture.agent_id)
      expect(run.fresh).toBe(true)
      expect(run).not.toHaveProperty('execution_state')
      expect(run).not.toHaveProperty('raw_snapshot')
    }
  }
  await checkRunSummaries()
  const fullAgentReads = []
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/agents') fullAgentReads.push(request.method()) })
  const selected = page.waitForResponse(response => new URL(response.url()).pathname === '/api/agents/selection')
  const definitions = page.waitForResponse(response => new URL(response.url()).pathname === '/api/processes/catalogue')
  const runs = page.waitForResponse(response => new URL(response.url()).pathname === '/api/processes/internal/runs')
  const started = Date.now()
  await page.goto('/process')
  const link = page.getByRole('link', { name: /^(Edit|Modifier): Synthetic catalogue process$/ })
  await expect(link).toBeVisible()
  await page.getByPlaceholder(/^(Filter processes…|Filtrer les processus…)$/).fill('Synthetic catalogue')
  const catalogueMs = Date.now() - started
  await page.getByLabel(/^(Runs|Exécutions): Synthetic catalogue process$/, { exact: true }).click()
  expect((await runs).ok()).toBeTruthy()
  for (const id of runIds) await expect(page.locator('.native-runs-table').getByRole('link', { name: new RegExp(id) })).toBeVisible()
  const executionsMs = Date.now() - started
  expect((await selected).ok()).toBeTruthy()
  const catalogueResponse = await definitions
  expect(catalogueResponse.ok()).toBeTruthy()
  const summary = (await catalogueResponse.json()).items.find(item => item.id === definition.id)
  expect(summary.code).toBe(definition.code)
  expect(runIds).toContain(summary.latest_run.id)
  expect(summary).not.toHaveProperty('bpmn_xml')
  expect(fullAgentReads).toEqual([])
  await testInfo.attach('process-catalogue-timing.json', { body: JSON.stringify({ catalogue_ms: catalogueMs, executions_ms: executionsMs, execution_count: runIds.length }), contentType: 'application/json' })
  await page.screenshot({ path: testInfo.outputPath('process-catalogue.png'), animations: 'disabled' })
  await link.click()
  await expect(page).toHaveURL(new RegExp(`/process/internal/${definition.code}$`))
  await expect(page.getByRole('textbox', { name: /^(Title|Titre)$/ })).toHaveValue('Synthetic catalogue process')
  await page.getByRole('main').getByRole('link', { name: /^(Back to list|Retour à la liste)$/ }).click()
  await expect(page.getByPlaceholder(/^(Filter processes…|Filtrer les processus…)$/)).toHaveValue('Synthetic catalogue')
  await expect(page.getByLabel(/^(Runs|Exécutions): Synthetic catalogue process$/, { exact: true })).toHaveAttribute('aria-expanded', 'true')
  for (const id of runIds) await expect(page.locator('.native-runs-table').getByRole('link', { name: new RegExp(id) })).toBeVisible()

  await checkRunSummaries()
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const toolsResponse = await request.get('/api/processes/tools', { headers })
  expect(toolsResponse.ok(), await toolsResponse.text()).toBeTruthy()
  const tools = await toolsResponse.json()
  let externalTool = tools.find(tool => tool.code === 'n8n')
  if (!externalTool) {
    const toolResponse = await request.post('/api/tools', { headers, data: {
      code: 'n8n', label: 'Synthetic external engine',
    } })
    expect(toolResponse.ok(), await toolResponse.text()).toBeTruthy()
    externalTool = await toolResponse.json()
  }
  const externalResponse = await request.post('/api/processes/definitions', { headers, data: {
    agent_id: fixture.agent_id, tool_id: externalTool.id,
    engine_process_id: 'synthetic-external-catalogue', label: 'Synthetic external catalogue process', description: 'Synthetic original description',
  } })
  expect(externalResponse.ok(), await externalResponse.text()).toBeTruthy()
  const external = await externalResponse.json()
  await page.setViewportSize({ width: 390, height: 1000 })
  await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop =>
    backdrop.click({ position: { x: 380, y: 150 } }))
  await page.goto('/process')
  await expect(page.getByRole('link', { name: /^(Edit|Modifier): Synthetic catalogue process$/ })).toBeVisible()
  const externalRow = page.getByLabel(/^(Runs|Exécutions): Synthetic external catalogue process$/, { exact: true })
  await expect(externalRow).toHaveAttribute('aria-expanded', 'false')
  await externalRow.click()
  await expect(externalRow).toHaveAttribute('aria-expanded', 'true')
  await page.getByRole('link', { name: /^(Edit|Modifier): Synthetic external catalogue process$/ }).click()
  await expect(page).toHaveURL(new RegExp(`/process/external/${external.id}$`))
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const description = page.getByRole('textbox', { name: 'Description', exact: true })
  await expect(description).toHaveValue('Synthetic original description')
  await description.fill('Synthetic saved description')
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/processes/definitions/${external.id}` && response.request().method() === 'PUT')
  await page.getByRole('button', { name: /^(Save|Enregistrer)$/ }).click()
  expect((await saved).ok()).toBeTruthy()
  await page.getByRole('main').getByRole('link', { name: /^(Back to list|Retour à la liste)$/ }).click()
  await expect(externalRow).toHaveAttribute('aria-expanded', 'true')
  await page.getByRole('link', { name: /^(Edit|Modifier): Synthetic external catalogue process$/ }).click()
  await page.reload()
  await expect(description).toHaveValue('Synthetic saved description')
  await expect(page.getByRole('button', { name: /^(Save|Enregistrer)$/ })).toBeVisible()
  await expect(page.getByRole('main').getByRole('link', { name: /^(Back to list|Retour à la liste)$/ })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('external-process-editor.png'), animations: 'disabled' })
  expect(errors()).toEqual([])
})
