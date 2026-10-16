import { test, expect, mount, jsonRoute } from './fixtures.mjs'

async function fixtures(page) {
  await jsonRoute(page, '**/api/processes/internal/definitions?*', { items: [{ id: 2, code: 'synthetic', title: 'Synthetic process', archived: false, document_id: 'synthetic-document' }], total: 1, page: 1, page_size: 50 })
  await jsonRoute(page, '**/api/processes/internal/runs?*', { items: [{ id: 'synthetic-run', status: 'success', process_label: 'Synthetic execution', engine_code: 'galaris', result_preview: 'Synthetic result' }], total: 1, page: 1, page_size: 50 })
  await jsonRoute(page, '**/api/processes/definitions', [{ id: 1, agent_id: 7, tool_id: 1, engine_process_id: 'synthetic-external', label: 'Synthetic n8n workflow', description: null }])
  await jsonRoute(page, '**/api/processes/tools', [{ id: 1, code: 'n8n', label: 'Synthetic n8n' }])
  await jsonRoute(page, '**/api/processes/tools/n8n/health', { status: 'healthy', message: 'Synthetic engine available' })
  await jsonRoute(page, '**/api/processes/operations', { pending_start_jobs: 0, stale_active_runs: 0, failed_last_24h: 0 })
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Alice', last_name: 'Example', code: 'synthetic', has_avatar: false }])
  await jsonRoute(page, '**/api/processes/internal/runs/synthetic-run?*', { id: 'synthetic-run', status: 'success', graph: null,
    operational: null, nodes: [], total: 0, page: 1, page_size: 50, events: [], event_cursor: 0, breakpoints: [], duration_seconds: 1, can_control: false })
  await jsonRoute(page, '**/api/processes/internal/runs/synthetic-run/metrics', { direct: {}, inclusive: {}, nodes: {}, tasks: {}, partial: false })
}

test('measure process catalogue startup without opening an execution', async ({ page }, testInfo) => {
  await fixtures(page)
  const started = Date.now()
  await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ', 'PROCESS_ADMIN'] })
  await expect(page.getByRole('link', { name: 'Synthetic process', exact: true })).toBeVisible()
  await expect(page.getByText('Synthetic n8n workflow', { exact: true })).toBeVisible()
  const measurement = await page.evaluate(() => {
    const resources = performance.getEntriesByType('resource')
    const modules = resources.filter(entry => new URL(entry.name).pathname.match(/^\/(app|core)\/.+\.(vue|ts)$/))
    return { module_requests: modules.length, module_bytes: modules.reduce((total, entry) => total + entry.decodedBodySize, 0),
      detail_modules: modules.filter(entry => /NativeRunPanel|BpmnCanvas|ProcessRunDetailContent|TaskDetail/.test(entry.name)).length }
  })
  measurement.catalogue_ms = Date.now() - started
  console.log('process_catalogue_startup', JSON.stringify(measurement))
  await testInfo.attach('process-catalogue-startup.json', { body: JSON.stringify(measurement), contentType: 'application/json' })
})

for (const width of [1440, 390]) {
  test(`process lists remain usable while execution code downloads, close and reopen at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await fixtures(page)
    let requested = false, release
    const pending = new Promise(resolve => { release = resolve })
    await page.route('**/app/process/components/NativeRunPanel.vue', async route => { requested = true; await pending; await route.continue() })
    const mounted = mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ', 'PROCESS_ADMIN'] })
    try {
      await expect(page.getByRole('link', { name: 'Synthetic process', exact: true })).toBeVisible()
      await mounted
      expect(requested).toBe(false)
      await page.getByLabel('Show details: Synthetic execution', { exact: true }).click()
      await expect.poll(() => requested).toBe(true)
      await expect(page.getByRole('dialog').getByRole('status')).toBeVisible()
      await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    } finally { release(); await mounted }
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByLabel('Show details: Synthetic execution', { exact: true }).click()
    await expect(page.getByRole('dialog').getByLabel('Run URL', { exact: true })).toHaveValue('processus://run/synthetic-run')
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    await expect(page.getByText('Synthetic n8n workflow', { exact: true })).toBeVisible()
  })
}

test('external definitions display before slow auxiliary catalogues and engine health', async ({ page }) => {
  await fixtures(page)
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route(url => ['/api/agents', '/api/agents/selection', '/api/processes/tools', '/api/processes/tools/n8n/health'].includes(url.pathname), async route => { await pending; await route.fallback() })
  await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ', 'PROCESS_ADMIN'] })
  try {
    await expect(page.getByText('Synthetic n8n workflow', { exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Synthetic process', exact: true })).toBeVisible()
    await page.getByPlaceholder('Filter processes…').fill('Synthetic')
  } finally { release() }
  await expect(page.getByText('Synthetic n8n', { exact: true })).toBeVisible()
  await expect(page.getByText('Alice Example', { exact: true })).toBeVisible()
})
