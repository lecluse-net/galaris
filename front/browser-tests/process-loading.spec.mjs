import { test, expect, mount, jsonRoute } from './fixtures.mjs'

async function fixtures(page) {
  await jsonRoute(page, '**/api/processes/internal/definitions?*', { items: [{ id: 2, code: 'synthetic', title: 'Synthetic process', archived: false, document_id: 'synthetic-document' }], total: 1, page: 1, page_size: 50 })
  await jsonRoute(page, '**/api/processes/internal/runs?*', { items: [{ id: 'synthetic-run', status: 'success', process_label: 'Synthetic execution', engine_code: 'galaris', result_preview: 'Synthetic result', started_at: '2026-01-01T12:00:00Z', finished_at: '2026-01-01T12:01:05Z' }], total: 1, page: 1, page_size: 50 })
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
  const runRequests = []
  page.on('request', request => { if (/\/processes\/(internal\/)?runs/.test(new URL(request.url()).pathname)) runRequests.push(request.url()) })
  const started = Date.now()
  await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ', 'PROCESS_ADMIN'] })
  await expect(page.getByText('Synthetic process', { exact: true })).toBeVisible()
  await expect(page.getByText('Synthetic n8n workflow', { exact: true })).toBeVisible()
  expect(runRequests).toEqual([])
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
      await expect(page.getByText('Synthetic process', { exact: true })).toBeVisible()
      await mounted
      expect(requested).toBe(false)
      const expand = page.getByLabel('Runs: Synthetic process', { exact: true })
      await expand.focus()
      await page.keyboard.press('Enter')
      await expect(expand).toHaveAttribute('aria-expanded', 'true')
      await page.getByLabel('Show details: Synthetic execution', { exact: true }).click()
      await expect.poll(() => requested).toBe(true)
      await expect(page.getByRole('dialog').getByRole('status').filter({ hasText: 'Loading' })).toBeVisible()
      await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    } finally { release(); await mounted }
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByLabel('Show details: Synthetic execution', { exact: true }).click()
    await expect(page.getByRole('dialog').getByRole('link', { name: 'Copy run URL: synthetic-run', exact: true })).toHaveAttribute('href', 'galaris://processes/runs/synthetic-run')
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByLabel('Runs: Synthetic process', { exact: true }).click()
    await expect(page.getByLabel('Show details: Synthetic execution', { exact: true })).toHaveCount(0)
    await page.getByLabel('Runs: Synthetic process', { exact: true }).click()
    await expect(page.getByLabel('Show details: Synthetic execution', { exact: true })).toBeVisible()
    await page.screenshot({ path: test.info().outputPath('process-expanded.png'), fullPage: true, animations: 'disabled' })
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
    await expect(page.getByText('Synthetic process', { exact: true })).toBeVisible()
    await page.getByPlaceholder('Filter processes…').fill('Synthetic')
  } finally { release() }
  await expect(page.getByText('Synthetic n8n', { exact: true })).toBeVisible()
  await expect(page.getByText('Alice Example', { exact: true })).toBeVisible()
})

for (const width of [1440, 390]) {
  test(`process rows and edit icons navigate independently of run expansion at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await fixtures(page)
    const requests = []
    page.on('request', request => { if (/\/processes\/(internal\/)?runs/.test(new URL(request.url()).pathname)) requests.push(request.url()) })
    await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ', 'PROCESS_ADMIN'] })
    for (const [label, path] of [['Synthetic n8n workflow', '/process/external/1'], ['Synthetic process', '/process/internal/synthetic']]) {
      await page.getByText(label, { exact: true }).click()
      await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(path)
      await expect(page.getByRole('button', { name: `Runs: ${label}`, exact: true })).toHaveAttribute('aria-expanded', 'false')
      await page.evaluate(() => window.testApp.router.push('/'))
      const row = page.getByLabel(label, { exact: true })
      await row.focus()
      await page.keyboard.press('Enter')
      await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(path)
      await expect(page.getByRole('button', { name: `Runs: ${label}`, exact: true })).toHaveAttribute('aria-expanded', 'false')
    }
    const external = page.getByRole('link', { name: 'Edit: Synthetic n8n workflow', exact: true })
    await expect(external).toHaveAttribute('href', '/process/external/1')
    await external.click()
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/process/external/1')
    await expect(page.getByLabel('Runs: Synthetic n8n workflow', { exact: true })).toHaveAttribute('aria-expanded', 'false')
    const internal = page.getByRole('link', { name: 'Edit: Synthetic process', exact: true })
    await expect(internal).toHaveAttribute('href', '/process/internal/synthetic')
    await internal.click()
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/process/internal/synthetic')
    await expect(page.getByLabel('Runs: Synthetic process', { exact: true })).toHaveAttribute('aria-expanded', 'false')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(requests).toEqual([])
  })

  test(`process sublists isolate runs and recover from loading errors at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await fixtures(page)
    let failed = true
    const requestedProcesses = []
    await page.route('**/api/processes/runs?*', route => {
      const params = new URL(route.request().url()).searchParams
      requestedProcesses.push(params.get('process_id'))
      expect(params.get('process_id')).toBe('1')
      if (failed) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary failure' } })
      return route.fulfill({ json: { items: [{ id: 'external-run', process_id: 1, status: 'success', summary: 'External execution', launcher_agent_id: 7,
        output: { message: 'Synthetic external result' }, started_at: '2026-01-01T12:00:00Z', created_at: '2026-01-01T11:59:00Z', finished_at: '2026-01-01T12:01:05Z' }], total: 1, page: 1, page_size: 50 } })
    })
    await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ'] })
    const internal = page.getByLabel('Runs: Synthetic process', { exact: true })
    const external = page.getByLabel('Runs: Synthetic n8n workflow', { exact: true })
    await expect(external).toBeVisible()
    expect(requestedProcesses).toEqual([])
    // The whole left-hand area expands runs, including the space around the arrow.
    await internal.locator('..').click({ position: { x: 2, y: 2 } })
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/')
    await expect(page.getByLabel('Show details: Synthetic execution', { exact: true })).toBeVisible()
    await external.click()
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/')
    const error = page.getByRole('alert').filter({ hasText: 'An error occurred' })
    await expect(error).toBeVisible()
    failed = false
    await error.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(page.getByLabel('Show details: External execution', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Show details: Synthetic execution', { exact: true })).toBeVisible()
    await test.info().attach('expanded-run-lists', { body: await page.screenshot({ fullPage: true, animations: 'disabled' }), contentType: 'image/png' })
    await external.click()
    await expect(page.getByLabel('Show details: External execution', { exact: true })).toHaveCount(0)
    await external.click()
    await expect(page.getByLabel('Show details: External execution', { exact: true })).toBeVisible()
    await page.getByPlaceholder('Filter processes…').fill('n8n')
    await expect(page.getByText('Synthetic process', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Synthetic n8n workflow', { exact: true })).toBeVisible()
  })
}

const externalDefinition = { id: 1, agent_id: 7, tool_id: 1, engine_process_id: 'synthetic-external', label: 'Synthetic external process', description: 'Saved synthetic description' }

for (const width of [1440, 390]) {
  test(`external editor preserves its draft after a failed save at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await fixtures(page)
    let saved = false
    await page.route('**/api/processes/definitions/1', route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: externalDefinition })
      expect(route.request().method()).toBe('PUT')
      expect(route.request().postDataJSON()).toEqual({ description: 'New synthetic description' })
      return route.fulfill(saved ? { json: { ...externalDefinition, description: 'New synthetic description' } } : { status: 503, json: { detail: 'Synthetic save failed' } })
    })
    await mount(page, 'app/process/components/ExternalProcessEditor.vue', { props: { id: 1 }, route: '/process/external/1', privileges: ['PROCESS_ADMIN'] })
    await expect(page.getByRole('heading', { name: externalDefinition.label })).toBeVisible()
    const description = page.getByRole('textbox', { name: 'Description', exact: true })
    await expect(description).toHaveValue(externalDefinition.description)
    await description.fill('New synthetic description')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Synthetic save failed', { exact: true })).toBeVisible()
    await expect(description).toHaveValue('New synthetic description')
    saved = true
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
    await expect(description).toHaveValue('New synthetic description')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.screenshot({ path: test.info().outputPath('external-process-editor.png'), fullPage: true, animations: 'disabled' })
  })
}

test('external editor respects read-only access and ignores late definition responses', async ({ page }) => {
  await fixtures(page)
  let late
  await page.route('**/api/processes/definitions/1', route => { late = route })
  await jsonRoute(page, '**/api/processes/definitions/2', { ...externalDefinition, id: 2, label: 'Second synthetic external process', description: 'Second description' })
  await mount(page, 'app/process/components/ExternalProcessEditor.vue', { props: { id: 1 }, privileges: ['PROCESS_READ'] })
  await expect.poll(() => Boolean(late)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ id: 2 }))
  const description = page.getByRole('textbox', { name: 'Description', exact: true })
  await expect(description).toHaveValue('Second description')
  await late.fulfill({ json: externalDefinition })
  await expect(description).toHaveValue('Second description')
  await expect(description).toHaveAttribute('readonly', '')
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0)
})

test('external process creation navigates to its own editor page', async ({ page }) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/processes/definitions/sync?*', [{ engine_process_id: 'synthetic-external', label: externalDefinition.label, description: externalDefinition.description, active: true }])
  await page.route('**/api/processes/definitions', route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().postDataJSON()).toEqual({ agent_id: null, tool_id: 1, engine_process_id: 'synthetic-external', label: externalDefinition.label, description: externalDefinition.description })
    return route.fulfill({ json: externalDefinition })
  })
  await mount(page, 'app/process/components/ExternalProcessEditor.vue', { route: '/process/new-external', privileges: ['PROCESS_ADMIN'] })
  await page.getByRole('button', { name: 'Sync n8n', exact: true }).click()
  await page.getByLabel('Available process', { exact: true }).click()
  await page.getByRole('option').filter({ hasText: externalDefinition.label }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/process/external/1')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

const n8nHealth = (message, code = null) => ({
  tool_code: 'n8n', status: code ? 'error' : 'healthy', reachable: code !== 'engine_unreachable', authenticated: code !== 'unauthorized',
  supports_cancel: true, cancel_mode: 'best_effort', message, details: code ? [code] : [], checked_at: '2026-01-01T12:00:00Z',
})

for (const width of [1440, 390]) {
  test(`n8n diagnostics open on synchronization and stay hidden after closing at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await fixtures(page)
    await jsonRoute(page, '**/api/processes/tools/n8n/health', n8nHealth('Synthetic n8n API available; 3 workflows discovered.'))
    let release, calls = 0
    const pending = new Promise(resolve => { release = resolve })
    await page.route('**/api/processes/definitions/sync?*', async route => {
      calls++
      await pending
      await route.fulfill({ json: [] })
    })
    await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ', 'PROCESS_ADMIN'] })
    await expect(page.getByText('Synthetic n8n API available; 3 workflows discovered.', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Sync n8n', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect.poll(() => calls).toBe(1)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    release()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Sync n8n', exact: true })).toBeEnabled()
    await expect(page.getByText('Synthetic n8n API available; 3 workflows discovered.', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Sync n8n', exact: true }).click()
    await expect(dialog.getByText('Synthetic n8n API available; 3 workflows discovered.', { exact: true })).toBeVisible()
    await expect(dialog.getByText(/pending launch/)).toBeVisible()
    await test.info().attach('n8n-diagnostics', { body: await dialog.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(page.getByText('Synthetic n8n API available; 3 workflows discovered.', { exact: true })).toHaveCount(0)
  })
}

for (const [code, visible] of [['not_configured', false], ['engine_unreachable', true]]) {
  test(`n8n connection banner distinguishes ${code}`, async ({ page }) => {
    await fixtures(page)
    await jsonRoute(page, '**/api/processes/tools/n8n/health', n8nHealth('Synthetic n8n connection diagnostic', code))
    await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ'] })
    const banner = page.getByRole('alert').filter({ hasText: 'Synthetic n8n connection diagnostic' })
    if (visible) await expect(banner).toBeVisible()
    else {
      await expect(page.getByText('Synthetic process', { exact: true })).toBeVisible()
      await expect(banner).toHaveCount(0)
    }
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })
}

test('run lists keep their server totals and navigate independently to the next page', async ({ page }) => {
  await fixtures(page)
  const pages = { internal: [], external: [] }
  for (const [kind, pattern] of [['internal', '**/api/processes/internal/runs?*'], ['external', '**/api/processes/runs?*']]) {
    await page.route(pattern, route => {
      const params = new URL(route.request().url()).searchParams
      const pageNumber = Number(params.get('page'))
      expect(params.get('page_size')).toBe('50')
      pages[kind].push(pageNumber)
      return route.fulfill({ json: { items: Array.from({ length: pageNumber === 1 ? 50 : 1 }, (_, index) => ({
        id: `${kind}-run-${(pageNumber - 1) * 50 + index + 1}`, status: 'success', process_label: 'Synthetic paged process',
        engine_code: kind === 'internal' ? 'galaris' : 'n8n', process_id: 1, summary: 'Synthetic paged run', output: null,
      })), total: 51, page: pageNumber, page_size: 50 } })
    })
  }
  await mount(page, 'app/process/pages/index.vue', { privileges: ['PROCESS_READ'] })
  await page.getByLabel('Runs: Synthetic process', { exact: true }).click()
  await page.getByLabel('Runs: Synthetic n8n workflow', { exact: true }).click()
  for (const [kind, selector] of [['internal', '.native-runs-table'], ['external', '.run-table']]) {
    const table = page.locator(selector)
    await expect(table.getByRole('link', { name: `Copy run URL: ${kind}-run-1`, exact: true })).toBeVisible()
    await table.getByRole('button', { name: 'Next page', exact: true }).click()
    await expect(table.getByRole('link', { name: `Copy run URL: ${kind}-run-51`, exact: true })).toBeVisible()
    expect(pages[kind]).toEqual([1, 2])
  }
  await page.locator('.process-toolbar-actions').getByRole('button', { name: 'Refresh', exact: true }).click()
  for (const [kind, selector] of [['internal', '.native-runs-table'], ['external', '.run-table']]) {
    await expect.poll(() => pages[kind]).toEqual([1, 2, 2])
    await expect(page.locator(selector).getByRole('link', { name: `Copy run URL: ${kind}-run-51`, exact: true })).toBeVisible()
  }
})
