import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const icon = { media_type: 'image/svg+xml', encoding: 'text', data: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="#397CA1"/></svg>' }
const preset = {
  code: 'synthetic-service', label: 'Synthetic service', description: 'Synthetic API preset', icon,
  capabilities: ['rest.api'], rest_config: { base_url: '${connection:url}', auth: { type: 'header', param: 'token', header_name: 'X-API-Key' }, header_params: {}, timeout: 60, max_response_bytes: 2097152 },
  connection_schema: { params: { url: { type: 'string', required: true, label: 'URL' }, token: { type: 'password', required: true, label: 'Token' } } },
  catalog: { format_version: 1, version: '1.0.0', minimum_galaris_version: '0.1.0', summary: { en: 'Synthetic API preset', fr: 'Modèle API synthétique' }, documentation: '', icon_credit: 'Synthetic fixture' },
}
const catalog = { source: 'bundled', revision: 'bundled', refresh_failed: false, entries: [{ definition: preset, compatible: true, compatibility: 'supported' }] }

async function routes(page, rows = []) {
  await jsonRoute(page, '**/api/services', rows)
  await jsonRoute(page, '**/api/services/catalog', catalog)
  await jsonRoute(page, '**/api/services/capabilities', [{ code: 'api', label: 'services.capabilityLabels.api', builtin: true, protocols: [{ value: 'rest.api', capability: 'api', label: 'services.protocolLabels.rest', builtin: true }] }])
  await jsonRoute(page, '**/api/file-share/bridges', [])
  await jsonRoute(page, '**/api/messenger/bridges', [])
}

for (const [width, dark] of [[1400, false], [390, true]]) {
  test(`A catalog copy preserves its portable icon and parameters, survives save errors and does not overwrite an installed service (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const installed = { ...preset, id: 7, can_edit: true, can_disable: true, global_params: {} }
    await routes(page, [installed])
    let writes = [], reject = true
    await page.route('**/api/services', route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: [installed] })
      const body = route.request().postDataJSON(); writes.push(body)
      if (reject) { reject = false; return route.fulfill({ status: 422, json: { detail: 'Synthetic save failure' } }) }
      return route.fulfill({ status: 201, json: { ...body, id: 8, can_edit: true, can_disable: true, global_params: {} } })
    })
    await mount(page, 'app/services/components/ServicesList.vue', { dark, privileges: ['SERVICE_ACCESS', 'SERVICE_EDIT'] })
    await page.getByRole('button', { name: 'New service', exact: true }).click()
    await expect(page.getByRole('dialog').getByText('Synthetic API preset', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`catalog-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: 'Configure a copy', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Technical name *', { exact: true })).toHaveValue('synthetic-service-2')
    await expect(dialog.getByRole('img', { name: 'Service icon', exact: true })).toHaveAttribute('src', /^data:image\/svg\+xml/)
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.getByText('Synthetic save failure', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Technical name *', { exact: true })).toHaveValue('synthetic-service-2')
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes).toHaveLength(2)
    expect(writes[1].icon).toEqual(icon)
    expect(writes[1].catalog.version).toBe('1.0.0')
    expect(writes[1].connection_schema.params.token.type).toBe('password')
    expect(writes[1].rest_config.auth.param).toBe('token')
    expect(writes[1].code).toBe('synthetic-service-2')
    expect(installed.code).toBe('synthetic-service')
  })
}

test('Catalog refresh failures retain usable entries and read-only users cannot add or refresh', async ({ page }) => {
  await routes(page)
  await page.route('**/api/services/catalog/refresh', route => route.fulfill({ json: { ...catalog, refresh_failed: true } }))
  await mount(page, 'app/services/components/ServicesList.vue', { privileges: ['SERVICE_ACCESS', 'SERVICE_EDIT'] })
  await page.getByRole('button', { name: 'New service', exact: true }).click()
  await page.getByRole('button', { name: 'Refresh from GitHub' }).click()
  await expect(page.getByRole('alert')).toContainText('last available catalog')
  await expect(page.getByRole('button', { name: 'Configure a copy', exact: true })).toBeEnabled()
  await mount(page, 'app/services/components/ServiceCatalog.vue', { privileges: ['SERVICE_ACCESS'], props: { installed: [] } })
  await expect(page.getByText('Synthetic API preset', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Configure a copy', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Refresh from GitHub' })).toHaveCount(0)
  await mount(page, 'app/services/components/ServicesList.vue', { privileges: ['SERVICE_ACCESS'] })
  await expect(page.getByRole('button', { name: 'Import', exact: true })).toHaveCount(0)
})

function yamlFile(code, label) {
  const yaml = `code: ${code}\nlabel: ${label}\n`
  return { name: `${code}.yaml`, mimeType: 'text/yaml', buffer: Buffer.from(yaml) }
}

test('a conflict from a dismissed import cannot replace the next file preview', async ({ page }, testInfo) => {
  let services = []
  await routes(page)
  await page.route('**/api/services', route => route.fulfill({ json: services }))
  let releaseConflict
  const pending = new Promise(resolve => { releaseConflict = resolve })
  await page.route('**/api/services/import?*', async route => {
    if (route.request().postData() === yamlFile('second-service', 'Second service').buffer.toString()) {
      services = [{ ...preset, id: 8, code: 'second-service', label: 'Second service', can_edit: true, global_params: {} }]
      return route.fulfill({ json: { ...services[0], created: true } })
    }
    await pending
    await route.fulfill({ status: 409, json: { detail: "Service 'first-service' already exists" } })
  })
  await mount(page, 'app/services/components/ServicesList.vue', { privileges: ['SERVICE_ACCESS', 'SERVICE_EDIT'] })
  const openImport = page.getByRole('button', { name: 'Import', exact: true })
  const dialog = page.getByRole('dialog')
  const input = page.locator('input[type=file][accept=".yaml,.yml"]')
  try {
    await openImport.click()
    await input.setInputFiles(yamlFile('first-service', 'First service'))
    await expect(dialog.getByText('First service', { exact: true })).toBeVisible()
    const submitted = page.waitForRequest('**/api/services/import?overwrite=false')
    await dialog.getByRole('button', { name: 'Import', exact: true }).click()
    await submitted
    await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
    await expect(dialog).toHaveCount(0)

    await openImport.click()
    await input.setInputFiles(yamlFile('second-service', 'Second service'))
    await expect(dialog.getByText('Second service', { exact: true })).toBeVisible()
    const response = page.waitForResponse('**/api/services/import?overwrite=false')
    releaseConflict()
    await (await response).finished()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(dialog.getByRole('button', { name: 'Import', exact: true })).toBeEnabled()
    await expect(dialog.getByText('Second service', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('service-import-desktop.png'), animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Import', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('article', { name: 'Second service', exact: true })).toBeVisible()
  } finally {
    releaseConflict()
  }
})

test('YAML replacement needs confirmation and a failed write keeps the same file available for retry', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  let service = { ...preset, id: 7, can_edit: true, can_disable: true, global_params: {} }
  await routes(page)
  await page.route('**/api/services', route => route.fulfill({ json: [service] }))
  const file = yamlFile(preset.code, 'Updated service')
  const submissions = []
  await page.route('**/api/services/import?*', route => {
    const overwrite = new URL(route.request().url()).searchParams.get('overwrite')
    submissions.push({ overwrite, yaml: route.request().postData() })
    if (overwrite === 'false') return route.fulfill({ status: 409, json: { detail: "Service 'synthetic-service' already exists" } })
    if (submissions.length === 2) return route.fulfill({ status: 422, json: { detail: 'Synthetic import rejected' } })
    service = { ...service, label: 'Updated service' }
    return route.fulfill({ json: { ...service, created: false } })
  })
  await mount(page, 'app/index/pages/services.vue', { route: '/services', dark: true, privileges: ['SERVICE_ACCESS', 'SERVICE_EDIT'] })
  await page.getByRole('textbox', { name: 'Search services' }).fill('nonmatching')
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Import a service' })
  const chooser = page.waitForEvent('filechooser')
  await dialog.getByRole('button', { name: 'Click or drop a .yaml file', exact: true }).press('Enter')
  await (await chooser).setFiles(file)
  await expect(dialog.getByText('Updated service', { exact: true })).toBeVisible()
  expect(submissions).toHaveLength(0)

  await dialog.getByRole('button', { name: 'Import', exact: true }).click()
  await expect(dialog.getByText(/synthetic-service.*already exists/)).toBeVisible()
  expect(submissions.map(entry => entry.overwrite)).toEqual(['false'])
  const replace = dialog.getByRole('button', { name: 'Replace', exact: true })
  await replace.click()
  await expect(dialog.getByRole('alert').filter({ hasText: 'Synthetic import rejected' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('service-import-mobile-dark.png'), animations: 'disabled' })
  await replace.click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('article', { name: 'Updated service', exact: true })).toBeVisible()
  expect(submissions.map(entry => entry.overwrite)).toEqual(['false', 'true', 'true'])
  expect(submissions.map(entry => entry.yaml)).toEqual(Array(3).fill(file.buffer.toString()))
})

const mcpService = {
  id: 12, code: 'synthetic-mcp', label: 'Synthetic MCP', description: '', can_edit: true, can_disable: true,
  capabilities: ['http.mcp'], global_params: {},
  mcp_config: { type: 'http', url: 'https://mcp.example.test/original', auth: { type: 'bearer', param: 'token' } },
  connection_schema: { params: { token: { type: 'password', label: 'Temporary token', required: true, default: '' } } },
}

async function openMcpServiceEditor(page, options = {}) {
  await routes(page, [mcpService])
  await jsonRoute(page, '**/api/services/capabilities', [
    { code: 'mcp', label: 'services.capabilityLabels.mcp', builtin: true, protocols: [
      { value: 'http.mcp', capability: 'mcp', label: 'services.protocolLabels.http', builtin: true },
    ] },
  ])
  await mount(page, 'app/index/pages/services.vue', { route: '/services', privileges: ['SERVICE_ACCESS', 'SERVICE_EDIT'], ...options })
  await page.getByRole('article', { name: 'Synthetic MCP', exact: true }).getByRole('button', { name: 'Edit service' }).click()
  return page.getByRole('dialog').filter({ has: page.getByRole('button', { name: 'Test connection', exact: true }) })
}

const mcpDiagnostic = page => page.getByRole('dialog').filter({ has: page.getByRole('button', { name: 'Run test', exact: true }) })
const mcpTestUrl = '**/api/services/test-mcp'

test('an MCP result from a closed dialog cannot appear after reopening', async ({ page }, testInfo) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  const requests = []
  await page.route(mcpTestUrl, async route => {
    requests.push(route.request().postDataJSON())
    if (requests.length === 1) {
      await pending
      return route.fulfill({ json: { success: true, message: 'Obsolete result', diagnostics: [], tools: [{ name: 'obsolete_tool' }] } })
    }
    if (requests.length === 2) return route.fulfill({ status: 422, json: { detail: 'Synthetic connection rejected' } })
    return route.fulfill({ json: {
      success: true, message: 'Current MCP connection',
      diagnostics: [{ stage: 'protocol', status: 'success', message: 'Protocol confirmed', duration_ms: 5 }],
      tools: [{ name: 'current_tool', description: 'Synthetic tool' }],
    } })
  })
  const editor = await openMcpServiceEditor(page)
  const openDiagnostic = editor.getByRole('button', { name: 'Test connection', exact: true })
  const diagnostic = mcpDiagnostic(page)
  const run = diagnostic.getByRole('button', { name: 'Run test', exact: true })
  const token = diagnostic.getByLabel('Temporary token *', { exact: true })
  try {
    await editor.getByRole('textbox', { name: 'URL *', exact: true }).fill('https://mcp.example.test/unsaved')
    await openDiagnostic.click()
    await token.fill('synthetic-first-token')
    const sent = page.waitForRequest(mcpTestUrl)
    await run.click()
    await sent
    await diagnostic.getByRole('button', { name: 'Close', exact: true }).last().click()
    await expect(diagnostic).toHaveCount(0)

    await openDiagnostic.click()
    await expect(token).toHaveValue('')
    const response = page.waitForResponse(mcpTestUrl)
    release()
    await (await response).finished()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(run).toBeEnabled()
    await expect(diagnostic.getByText('Obsolete result', { exact: true })).toHaveCount(0)

    await token.fill('synthetic-current-token')
    await run.click()
    await expect(diagnostic.getByRole('alert').filter({ hasText: 'Synthetic connection rejected' })).toBeVisible()
    await run.click()
    await expect(diagnostic.getByText('Protocol confirmed', { exact: true })).toBeVisible()
    await expect(diagnostic.getByText('current_tool', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('mcp-diagnostic-desktop.png'), animations: 'disabled' })
    expect(requests).toHaveLength(3)
    expect(requests[0].params).toEqual({ token: 'synthetic-first-token' })
    expect(requests[1]).toEqual(requests[2])
    expect(requests[2]).toMatchObject({
      service_id: mcpService.id, code: mcpService.code, mcp_config: { url: 'https://mcp.example.test/unsaved' },
      params: { token: 'synthetic-current-token' },
    })
  } finally {
    release()
  }
})

test('MCP candidate preparation uses the selected agent and its current temporary parameters', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const candidateUrl = '**/api/services/mcp-candidates'
  let release
  const pending = new Promise(resolve => { release = resolve })
  const requests = []
  await jsonRoute(page, '**/api/agents/selection?scope=management', [{ id: 7, label: 'Synthetic agent', has_avatar: false }])
  await page.route(candidateUrl, async route => {
    requests.push(route.request().postDataJSON())
    if (requests.length === 1) {
      await pending
      return route.fulfill({ json: { reference: 'obsolete-reference', expires_in_seconds: 300 } })
    }
    return route.fulfill({ json: { reference: 'current-reference', expires_in_seconds: 300 } })
  })
  const editor = await openMcpServiceEditor(page, { dark: true })
  const diagnostic = mcpDiagnostic(page)
  try {
    await editor.getByRole('button', { name: 'Test connection', exact: true }).click()
    await diagnostic.getByLabel('Agent receiving the MCP candidate', { exact: true }).click()
    await page.getByRole('option', { name: 'Synthetic agent', exact: true }).click()
    const token = diagnostic.getByLabel('Temporary token *', { exact: true })
    const prepare = diagnostic.getByRole('button', { name: 'Prepare candidate for this agent' })
    await token.fill('synthetic-old-token')
    const sent = page.waitForRequest(candidateUrl)
    await prepare.click()
    await sent

    await token.fill('synthetic-new-token')
    await prepare.click()
    const reference = diagnostic.getByLabel('Reference to give to the agent', { exact: true })
    await expect(reference).toHaveValue('current-reference')
    const staleResponse = page.waitForResponse(candidateUrl)
    release()
    await (await staleResponse).finished()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(reference).toHaveValue('current-reference')
    await page.screenshot({ path: testInfo.outputPath('mcp-candidate-mobile-dark.png'), animations: 'disabled' })
    expect(requests).toHaveLength(2)
    expect(requests[0].params).toEqual({ token: 'synthetic-old-token' })
    expect(requests[1]).toMatchObject({
      agent_id: 7,
      definition: { code: mcpService.code, capabilities: ['http.mcp'], mcp_config: { url: mcpService.mcp_config.url } },
      params: { token: 'synthetic-new-token' },
    })
  } finally {
    release()
  }
})
