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
    const installed = { ...preset, id: 7, can_edit: true, can_disable: true, global_params: {}, conversation_enabled: false }
    await routes(page, [installed])
    let writes = [], reject = true
    await page.route('**/api/services', route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: [installed] })
      const body = route.request().postDataJSON(); writes.push(body)
      if (reject) { reject = false; return route.fulfill({ status: 422, json: { detail: 'Synthetic save failure' } }) }
      return route.fulfill({ status: 201, json: { ...body, id: 8, can_edit: true, can_disable: true, global_params: {} } })
    })
    await mount(page, 'app/services/components/ServicesList.vue', { dark, privileges: ['SERVICE_ACCESS', 'SERVICE_EDIT'] })
    await page.getByRole('tab', { name: 'Catalog', exact: true }).click()
    await expect(page.getByText('Synthetic API preset', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`catalog-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: 'Configure a copy', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Technical name *', { exact: true })).toHaveValue('synthetic-service-2')
    await expect(dialog.locator('img')).toHaveAttribute('src', /^data:image\/svg\+xml/)
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
  await page.getByRole('tab', { name: 'Catalog', exact: true }).click()
  await page.getByRole('button', { name: 'Refresh from GitHub' }).click()
  await expect(page.getByRole('alert')).toContainText('last available catalog')
  await expect(page.getByRole('button', { name: 'Configure a copy', exact: true })).toBeEnabled()
  await mount(page, 'app/services/components/ServicesList.vue', { privileges: ['SERVICE_ACCESS'] })
  await page.getByRole('tab', { name: 'Catalog', exact: true }).click()
  await expect(page.getByText('Synthetic API preset', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Configure a copy', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Refresh from GitHub' })).toHaveCount(0)
})
