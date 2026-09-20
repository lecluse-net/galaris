import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const subscription = {
  key: 'openai-codex', code: 'openai-codex', display_name: 'ChatGPT subscription', provider_type: 'openai_compatible', auth_type: 'oauth_device',
  default_base_url: 'https://example.invalid', is_custom: false, configuration_fields: [], connection: { user_id: 1, is_active: false, oauth_connected: false },
}

for (const locale of ['en', 'fr']) {
test(`subscription owner acknowledgement gates saving, survives reload and resets for a new owner (${locale})`, async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 1100 })
  await mount(page, 'app/llm/components/ProviderConfigPanel.vue', { locale, props: { item: subscription, detail: null, users: [{ id: 1, label: 'Alice' }, { id: 2, label: 'Bob' }], activeUserCount: 2 }, privileges: ['LLM_PROVIDER_EDIT'] })
  const save = page.getByRole('button', { name: /^(save|enregistrer)$/i })
  await expect(save).toBeDisabled()
  const ack = page.getByRole('checkbox')
  await ack.check()
  await expect(save).toBeEnabled()
  await save.click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'save').at(-1)?.value)).toMatchObject({ user_id: 1, subscription_acknowledged: true, is_active: false })
  await page.evaluate(() => window.testApp.setProps({ detail: { user_id: 1, is_active: false, subscription_acknowledged: true } }))
  await expect(ack).toBeChecked()
  // Reopening starts a fresh form and must restore the persisted value.
  await mount(page, 'app/llm/components/ProviderConfigPanel.vue', { locale, props: { item: subscription, detail: { user_id: 1, is_active: false, subscription_acknowledged: true }, users: [{ id: 1, label: 'Alice' }, { id: 2, label: 'Bob' }], activeUserCount: 2 }, privileges: ['LLM_PROVIDER_EDIT'] })
  await expect(ack).toBeChecked()
  await ack.uncheck()
  await page.evaluate(() => window.testApp.setProps({ detail: { user_id: 1, is_active: false, subscription_acknowledged: true } }))
  await expect(ack).not.toBeChecked()
  await expect(save).toBeDisabled()
  await ack.check()
  await expect(save).toBeEnabled()
  await page.getByRole('combobox').click()
  await page.getByRole('option', { name: 'Bob', exact: true }).click()
  await expect(ack).not.toBeChecked()
  await expect(save).toBeDisabled()
  const terms = page.locator('a[href="https://openai.com/policies/terms-of-use/"]')
  await expect(terms).toBeVisible()
  await expect(terms).toHaveAttribute('rel', 'noopener noreferrer')
  await setPrivileges(page, [])
  await expect(ack).toBeDisabled()
})
}

test('Harness Manager diagnostics display failures, recover on retry and keep both installation guides', async ({ page }) => {
  await jsonRoute(page, '**/api/harness-manager/release', { version: '1.1.0', update_url: 'https://galaris.test/api/harness-manager/updates', sha256: 'test', size: 100 })
  await jsonRoute(page, '**/api/harness-manager/configuration', { manager_url: 'http://manager.example.invalid', galaris_api_url: '', secret_configured: true })
  let healthy = false
  await page.route('**/api/harness-manager/diagnostics', route => route.fulfill({ json: {
    state: healthy ? 'ok' : 'connection_error', manager_url: 'http://manager.example.invalid', galaris_api_url: 'http://galaris.example.invalid',
    public_api_url: 'http://galaris.example.invalid', secret_configured: true, api_url_source: 'APP_HOST', mode_hint: 'remote', api_issue: 'none', runtime_api_check: 'not_checked',
    legacy_environment_detected: false, http_status: healthy ? 200 : null,
  } }))
  await mount(page, 'app/harnesses/components/HarnessManagerHelp.vue')
  await expect(page.getByText(/Cannot connect to the manager/)).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Manager URL', exact: true })).toBeVisible()
  healthy = true
  await page.getByRole('button', { name: /refresh|check/i }).click()
  await expect(page.getByText(/Manager reachable; authentication and supervision contract verified/)).toBeVisible()
  await expect(page.getByText(/Cannot connect to the manager/)).toHaveCount(0)
  await page.getByRole('button', { name: 'Connection help', exact: true }).click()
  await expect(page.getByRole('tab')).toHaveCount(2)
  await page.getByRole('tab').last().click()
  await expect(page.getByText(/Configure connectivity in both directions/)).toBeVisible()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('Harness Manager saves a new key, preserves it on reopen and exports only saved configuration', async ({ page }, testInfo) => {
  let saved = { manager_url: 'http://host.docker.internal:8485', galaris_api_url: '', secret_configured: false }
  const writes = []
  await page.route('**/api/harness-manager/configuration', route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON()
      writes.push(body)
      saved = { manager_url: body.manager_url, galaris_api_url: body.galaris_api_url, secret_configured: Boolean(body.secret || saved.secret_configured) }
    }
    return route.fulfill({ json: saved })
  })
  await jsonRoute(page, '**/api/harness-manager/generate-secret', { secret: 'test-generated-secret' })
  await page.route('**/api/harness-manager/environment', route => route.fulfill({ contentType: 'text/plain', body: 'API_HOST=0.0.0.0\nHARNESS_MANAGER_SECRET=test-generated-secret\n' }))
  let installation
  await page.route('**/api/harness-manager/installation.zip', route => {
    installation = route.request().postDataJSON()
    return route.fulfill({ contentType: 'application/zip', body: 'test-archive' })
  })
  const mountForm = () => mount(page, 'app/harnesses/components/HarnessManagerConfiguration.vue', { privileges: ['PARAMS_EDIT'] })
  await mountForm()
  await page.getByRole('button', { name: 'Generate a new installation key' }).click()
  await page.getByRole('textbox', { name: 'Manager URL', exact: true }).fill('https://manager.example.test')
  await page.getByRole('button', { name: 'Prepare installation', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Generate .env with saved secret' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Download ready-to-install ZIP' })).toBeDisabled()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).first().click()
  await page.getByRole('button', { name: 'Save and check connection' }).click()
  await expect.poll(() => writes).toHaveLength(1)
  expect(writes[0].secret).toBe('test-generated-secret')
  await page.getByRole('button', { name: 'Prepare installation', exact: true }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download ready-to-install ZIP' }).click()
  expect((await downloaded).suggestedFilename()).toBe('harness-manager-installation.zip')
  expect(installation.base_dir).toBe('/opt/galaris-harnesses')
  expect(installation.max_file_size_mb * 1_048_576).toBe(1_000_000)
  expect(installation.max_raw_file_size_mb * 1_048_576).toBe(512_000_000)
  expect(installation).not.toHaveProperty('secret')
  await page.getByText('Advanced host options', { exact: true }).click()
  const textLimit = page.getByLabel('Encrypted text file limit (MB)', { exact: true })
  await expect(textLimit).toHaveValue('1')
  await textLimit.fill('2')
  const secondDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download ready-to-install ZIP' }).click()
  await secondDownload
  expect(installation.max_file_size_mb * 1_048_576).toBe(2_000_000)
  await page.getByRole('button', { name: 'Generate .env with saved secret' }).click()
  await expect(page.locator('pre').filter({ hasText: 'HARNESS_MANAGER_SECRET=test-generated-secret' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath('manager-configuration-mobile.png'), fullPage: true })
  await page.getByRole('textbox', { name: 'Instance directory (BASE_DIR)' }).fill('/srv/harnesses')
  await expect(page.locator('pre').filter({ hasText: 'HARNESS_MANAGER_SECRET=' })).toHaveCount(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).first().click()
  await mountForm()
  await expect(page.getByRole('textbox', { name: 'Manager URL', exact: true })).toHaveValue('https://manager.example.test')
  await expect(page.getByLabel('Shared secret', { exact: true })).toHaveValue('')
  await page.getByRole('button', { name: 'Save and check connection' }).click()
  await expect.poll(() => writes).toHaveLength(2)
  expect(writes[1]).not.toHaveProperty('secret')
  await setPrivileges(page, ['PARAMS_ACCESS'])
  await expect(page.getByRole('button', { name: 'Generate .env with saved secret' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Save and check connection' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Download ready-to-install ZIP' })).toHaveCount(0)
})

for (const format of ['environment', 'installation.zip']) {
for (const invalidate of ['edit', 'close']) {
test(`Harness Manager ignores late ${format} exports after ${invalidate} and preserves edits after a failed save`, async ({ page }) => {
  let fail = false
  await page.route('**/api/harness-manager/configuration', route => route.fulfill(fail
    ? { status: 500, json: { detail: 'unavailable' } }
    : { json: { manager_url: 'https://manager.example.test', galaris_api_url: '', secret_configured: true } }))
  let resolveExport
  const pending = new Promise(resolve => { resolveExport = resolve })
  const downloads = []
  page.on('download', download => downloads.push(download))
  await page.route(`**/api/harness-manager/${format}`, async route => {
    await pending
    await route.fulfill({ contentType: 'text/plain', body: 'SECRET=old-export' })
  })
  await mount(page, 'app/harnesses/components/HarnessManagerConfiguration.vue', { privileges: ['PARAMS_EDIT'] })
  await page.getByRole('button', { name: 'Prepare installation', exact: true }).click()
  await page.getByRole('textbox', { name: 'Instance directory (BASE_DIR)' }).fill('/srv/initial')
  const button = format === 'environment' ? 'Generate .env with saved secret' : 'Download ready-to-install ZIP'
  await page.getByRole('button', { name: button }).click()
  if (invalidate === 'edit') {
    await page.getByRole('textbox', { name: 'Instance directory (BASE_DIR)' }).fill('/srv/changed')
  } else {
    await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: 'Prepare installation', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Instance directory (BASE_DIR)' })).toHaveValue('/srv/initial')
  }
  resolveExport()
  await expect(page.getByRole('button', { name: button })).toBeEnabled()
  await expect(page.getByText('SECRET=old-export')).toHaveCount(0)
  expect(downloads).toHaveLength(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).first().click()
  fail = true
  await page.getByRole('textbox', { name: 'Manager URL', exact: true }).fill('https://changed.example.test')
  await page.getByRole('button', { name: 'Save and check connection' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Unable to save' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Manager URL', exact: true })).toHaveValue('https://changed.example.test')
})
}
}

test('configured model availability checks query its provider and update the row', async ({ page }) => {
  const model = { id: 3, label: 'Example model', code: 'example', llm_name: 'example-v1', llm_provider_id: 2, provider_name: 'Example provider', primary_capability: 'chat', service_capabilities: ['chat'], input_text: true, output_text: true, context_length: 8192 }
  await jsonRoute(page, '**/api/llm-providers', [{ id: 2, name: 'Example provider', is_active: true }])
  await jsonRoute(page, '**/api/llm-providers/catalog', { items: [], users: [], active_user_count: 1 })
  await jsonRoute(page, '**/api/llm-providers/llms', [model])
  let available = true
  const requests = []
  await page.route('**/api/llm-providers/2/resources?*', route => {
    requests.push(new URL(route.request().url()).searchParams.get('capability'))
    return route.fulfill({ json: { models: available ? [{ id: 'example-v1' }] : [] } })
  })
  await mount(page, 'app/llm/components/ConfiguredLlmManager.vue', { privileges: ['LLM_PROVIDER_EDIT'] })
  const row = page.locator('tbody tr').filter({ hasText: 'Example model' })
  const check = row.getByRole('button', { name: /check/i })
  await check.click()
  await expect.poll(() => requests).toEqual(['chat'])
  await expect(page.getByRole('alert').filter({ hasText: 'Example model is available' })).toBeVisible()
  available = false
  await check.click()
  await expect.poll(() => requests).toHaveLength(2)
  await expect(page.getByRole('alert').filter({ hasText: 'Example model is unavailable' })).toBeVisible()
})

test('available models keep long names, prices and actions accessible without horizontal scrolling', async ({ page }, testInfo) => {
  const model = {
    id: 3, label: 'Organisation/ModeleDeRaisonnementAvecUnNomTresLongSansEspace',
    code: 'organisation-modele-raisonnement-production-2026',
    llm_name: 'organisation/model-with-a-long-version-name-2026-09-17',
    llm_provider_id: 2, provider_name: 'FournisseurCompatibleAvecUnNomPersonnaliseTresLongSansEspace',
    primary_capability: 'chat', service_capabilities: ['chat'], input_text: true, output_text: true,
    context_length: 1000000, is_subscription: true,
    cost_per_input_token: 0.000015, cost_per_cached_input_token: 0.000003, cost_per_output_token: 0.000075,
  }
  await jsonRoute(page, '**/api/llm-providers', [{ id: 2, name: model.provider_name, is_active: true }])
  await jsonRoute(page, '**/api/llm-providers/catalog', { items: [], users: [], active_user_count: 1 })
  await jsonRoute(page, '**/api/llm-providers/llms', [model])
  await jsonRoute(page, '**/api/llm-providers/2/resources?*', { models: [{ id: model.llm_name }] })
  await mount(page, 'app/llm/pages/index.vue', {
    locale: 'fr', route: '/llm?tab=models', privileges: ['LLM_PROVIDER_EDIT'],
  })
  for (const width of [1024, 1280, 1440, 768, 600, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    // Reserve the desktop navigation width, as in the application shell.
    await page.locator('.q-page-container').evaluate((element, width) => {
      element.style.paddingLeft = width >= 1024 ? '260px' : '0px'
    }, width)
    await expect(page.locator('.llm-grid-card')).toHaveCount(width < 1024 ? 1 : 0)
    await expect(page.getByText(model.label, { exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => {
      const elements = [document.documentElement, ...document.querySelectorAll('.q-table__middle, th, td, .llm-grid-card, .llm-grid-card *, .llm-toolbar-actions')]
      return elements.filter(element => element.clientWidth > 0 && element.scrollWidth > element.clientWidth + 1)
        .map(element => ({ tag: element.tagName, text: element.textContent?.trim(), overflow: element.scrollWidth - element.clientWidth }))
    }), { message: `No overflowing or clipped model content at ${width}px` }).toEqual([])
    await expect(page.getByText(model.provider_name, { exact: true })).toBeVisible()
    await expect(page.getByText(model.code, { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Modifier', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Supprimer', exact: true })).toBeVisible()
    if ([1024, 1440, 320].includes(width)) {
      await page.screenshot({ path: testInfo.outputPath(`available-models-${width}.png`), fullPage: true })
    }
    await page.getByRole('button', { name: 'Vérifier ce LLM', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: model.label }).last()).toBeVisible()
  }
})

test('manager version differences give appropriate update guidance and authenticated source download', async ({ page }) => {
  let failed = true
  await page.route('**/api/harness-manager/release', route => route.fulfill(failed
    ? { status: 503, json: { detail: 'Unavailable' } }
    : { json: { version: '1.1.0', sha256: 'test', size: 100, update_url: 'https://galaris.test/api/harness-manager/updates' } }))
  await page.route('**/api/harness-manager/release.zip', route => route.fulfill({ contentType: 'application/zip', body: 'test-code-only-archive' }))
  await mount(page, 'app/harnesses/components/HarnessManagerRelease.vue', {
    props: { diagnostics: { manager_version: '1.0.0', expected_version: '1.1.0', version_status: 'update_available' } },
  })
  await expect(page.getByRole('alert')).toContainText('Unable to prepare')
  failed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('A newer manager version is available')
  await page.getByRole('button', { name: 'Update manager', exact: true }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download source ZIP · 1.1.0' }).click()
  expect((await downloaded).suggestedFilename()).toBe('harness-manager-source.zip')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).first().click()
  await page.evaluate(() => window.testApp.setProps({ diagnostics: { manager_version: '1.1.0', version_status: 'current' } }))
  await expect(page.getByRole('status')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ diagnostics: { manager_version: '1.2.0', version_status: 'newer' } }))
  await expect(page.getByRole('status')).toContainText('will not downgrade')
  await page.evaluate(() => window.testApp.setProps({ diagnostics: { manager_version: null, version_status: 'unknown' } }))
  await expect(page.getByRole('status')).toContainText('did not report a usable version')
})
