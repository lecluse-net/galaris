import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function fixtures(page) {
  await jsonRoute(page, '**/api/harness-manager/release', { version: '1.1.0', update_url: 'https://galaris.test/api/harness-manager/updates', sha256: 'test', size: 100 })
  await jsonRoute(page, '**/api/n8n/settings', { galaris_base_url: 'https://galaris.example.test' })
  await jsonRoute(page, '**/api/params', { params: [] })
  await jsonRoute(page, '**/api/memory/link-reconciliation', {
    after_dream_enabled: false, scheduled_enabled: false, interval_hours: 24,
    next_scheduled_at: null, last_completed_at: null, latest_job_status: null,
  })
  await jsonRoute(page, '**/api/harnesses/catalog?*', [])
  await jsonRoute(page, '**/api/harnesses/execution-configurations', [])
  await jsonRoute(page, '**/api/harness-manager/configuration', { manager_url: 'https://manager.example.test', galaris_api_url: '', secret_configured: true })
  await jsonRoute(page, '**/api/harness-manager/diagnostics', {
    state: 'ok', secret_configured: true, api_url_source: 'APP_HOST', api_issue: 'none',
    runtime_api_check: 'not_checked', legacy_environment_detected: false,
  })
}

async function expandSettings(page) {
  const closed = page.locator('.q-expansion-item--collapsed > .q-expansion-item__container > .q-item:visible')
  while (await closed.count()) {
    const header = closed.first()
    // Manager diagnostics deliberately use an icon-only expansion toggle.
    const toggle = header.locator('.q-expansion-item__toggle-icon')
    await toggle.click()
  }
}

for (const [section, name, label, initial, saved, rejected, tab = 'internal', scale = 1] of [
  ['messaging', 'MESSENGER_MAX_INLINE_MB', 'Maximum inline attachment size (MB)', '3.814697265625', '7.62939453125', '15.2587890625', 'internal', 1.048576],
  ['harnesses', 'PYDANTIC_AI_BINARY_INPUT_MAX_BYTES', 'Maximum binary file size sent to the model (MB)', '20000000', '40000000', '80000000', 'internal', 0.000001],
  ['tasks', 'TASK_AGENT_MAX_REQUESTS', 'Maximum model requests per execution', '120', '150', '200'],
  ['tasks', 'TASK_AGENT_MAX_TOOL_CALLS', 'Maximum tool calls per execution', '800', '1000', '1200'],
  ['logs', 'INCIDENT_TRACE_RETENTION_DAYS', 'Incident trace retention (days)', '30', '60', '90'],
  ['logs', 'LLM_TRACE_RETENTION_DAYS', 'LLM trace retention (days)', '30', '60', '90'],
]) {
  test(`${name} saves, recovers errors and persists on reopen in ${section}`, async ({ page }) => {
    await fixtures(page)
    const param = { name, value: initial, configured: true, secret: false }
    const display = value => String(Number((Number(value) * scale).toFixed(6)))
    await page.route('**/api/params', route => route.fulfill({ json: { params: [param] } }))
    let fail = false
    await page.route(`**/api/params/${name}`, route => {
      if (fail) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
      param.value = route.request().postDataJSON().value
      return route.fulfill({ json: { ...param, status: 'success' } })
    })
    const open = async () => {
      await mount(page, 'core/params/components/PreferencesSectionPage.vue', {
        props: { section }, route: `/params/${section}?tab=${tab}`, privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT'],
      })
      await expandSettings(page)
    }
    await open()
    const field = page.getByLabel(label, { exact: true })
    await expect(field).toHaveValue(display(initial))
    await field.fill(display(saved))
    await field.press('Tab')
    await expect.poll(() => param.value).toBe(saved)
    fail = true
    await field.fill(display(rejected))
    await field.press('Tab')
    await expect(field).toHaveValue(display(saved))
    await page.setViewportSize({ width: 390, height: 844 })
    await open()
    await expect(field).toHaveValue(display(saved))
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await setPrivileges(page, ['PARAMS_ACCESS'])
    if (section !== 'harnesses') await expect(field).toHaveAttribute('readonly', '')
    else await expect(field).not.toBeVisible()
  })
}

const sectionCatalogs = {
  system: ['systemFields'],
  language: ['languageFields'], memory: ['memorySessionFields', 'memoryContextFields', 'memoryAutomationFields', 'memoryStorageFields'],
  dream: ['dreamFields', 'dreamAttachmentFields', 'dreamLinkReconciliationFields'], voice: ['voiceFields'],
  audio: ['audioMeetingSummaryFields', 'audioVideoSummaryFields'],
  process: ['processGeneralFields', 'processAdvancedFields'],
  tasks: ['taskSchedulerFields', 'taskRetryFields', 'taskCreationFields', 'taskBudgetFields', 'taskCollaborationFields'],
  search: ['searchFields'], instructions: ['executorInstructionFields'],
  messaging: ['commonMessagingFields'], harnesses: [], janus: [], logs: ['traceRetentionFields'],
}

test('megabyte preferences preserve unchanged byte limits and reject invalid sizes before saving', async ({ page }) => {
  await fixtures(page)
  const param = { name: 'PYDANTIC_AI_BINARY_INPUT_MAX_BYTES', value: '20971521', configured: true, secret: false }
  await jsonRoute(page, '**/api/params', { params: [param] })
  const writes = []
  await page.route(`**/api/params/${param.name}`, route => {
    param.value = route.request().postDataJSON().value
    writes.push(param.value)
    return route.fulfill({ json: { ...param, status: 'success' } })
  })
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', {
    props: { section: 'harnesses' }, route: '/params/harnesses?tab=internal', privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT'],
  })
  const field = page.getByLabel('Maximum binary file size sent to the model (MB)', { exact: true })
  await expect(field).toHaveValue('20.971521')
  await field.focus()
  await field.press('Tab')
  expect(writes).toEqual([])
  for (const invalid of ['', '-1', '2000']) {
    await field.fill(invalid)
    await field.press('Tab')
    await expect(page.getByText(/Enter a size in MB within the allowed limits/)).toBeVisible()
    expect(writes).toEqual([])
  }
  await field.fill('2.5')
  await field.press('Tab')
  await expect.poll(() => writes).toEqual(['2500000'])
  await expect(field).toHaveValue('2.5')
})

for (const [section, catalogs] of Object.entries(sectionCatalogs)) {
  test(`preferences ${section}: every existing setting remains available on desktop and mobile`, async ({ page }, testInfo) => {
    await fixtures(page)
    await mount(page, 'core/params/components/PreferencesSectionPage.vue', {
      props: { section }, privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT', 'TASK_PURGE', 'LLM_CALL_PURGE', 'INCIDENT_PURGE'],
    })
    await expect(page.locator('.settings-panel')).toBeVisible()
    await expect(page.locator('.q-expansion-item--expanded')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath(`${section}-desktop.png`), fullPage: true })
    await expandSettings(page)
    const labels = await page.evaluate(async catalogs => {
      const catalog = await import('/core/params/settingsCatalog.ts')
      const { i18n } = await import('/core/i18n/index.ts')
      return catalogs.flatMap(key => catalog[key]).map(field => i18n.global.t(field.labelKey))
    }, catalogs)
    for (const label of labels) await expect(page.getByText(label, { exact: true }).first()).toBeVisible()
    if (section === 'process') await expect(page.getByLabel('n8n URL', { exact: true })).toBeVisible()
    if (section === 'janus') await expect(page.locator('input')).toHaveCount(1)
    if (section === 'logs') {
      for (const label of ['Purge processed tasks', 'Purge LLM calls', 'Empty the error log']) {
        await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible()
      }
    }
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.testApp.dark(true))
    for (const label of labels) await expect(page.getByText(label, { exact: true }).first()).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const opened = page.locator('.q-expansion-item--expanded > .q-expansion-item__container > .q-item:visible')
    while (await opened.count()) await opened.first().locator('.q-expansion-item__toggle-icon').click()
    await expect(page.locator('.q-expansion-item__content:visible')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath(`${section}-mobile-dark.png`), fullPage: true })
  })
}

test('advanced task settings retain prompt drafts, save values, recover errors and enforce rights', async ({ page }) => {
  await fixtures(page)
  const retry = { name: 'TASK_ACTION_MAX_ATTEMPTS', value: '3', configured: true, secret: false }
  const prompt = { name: 'ai.task-objective-system-prompt', value: 'Existing custom objective', configured: true, secret: false,
    prompt: { default_value: 'Default objective', customized: true, default_changed: false } }
  await jsonRoute(page, '**/api/params', { params: [retry, prompt] })
  let fail = false
  const updates = []
  await page.route('**/api/params/TASK_ACTION_MAX_ATTEMPTS', route => {
    const body = route.request().postDataJSON()
    updates.push(body)
    if (fail) return route.fulfill({ status: 500, json: { detail: 'Unavailable' } })
    retry.value = body.value
    return route.fulfill({ json: { ...retry, status: 'ok' } })
  })
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', {
    props: { section: 'tasks' }, privileges: ['PARAMS_EDIT'],
  })
  const attempts = page.getByLabel('Application-error attempts', { exact: true })
  await expect(attempts).not.toBeVisible()
  const retries = page.getByRole('button', { name: /Retries/ })
  await retries.press('Enter')
  await expect(attempts).toHaveValue('3')
  await attempts.fill('5')
  await attempts.press('Tab')
  await expect.poll(() => updates.at(-1)?.value).toBe('5')
  await retries.click()
  await retries.click()
  await expect(attempts).toHaveValue('5')
  fail = true
  await attempts.fill('7')
  await attempts.press('Tab')
  await expect.poll(() => updates.at(-1)?.value).toBe('7')
  await expect(attempts).toHaveValue('5')

  const planning = page.getByRole('button', { name: /Task creation/ })
  await planning.click()
  const planner = page.locator('.prompt-editor').filter({ hasText: 'Task-objective system prompt' }).locator('textarea')
  await expect(planner).toHaveValue('Existing custom objective')
  await planner.fill('Unsaved objective draft')
  await planning.click()
  await planning.click()
  await expect(planner).toHaveValue('Unsaved objective draft')
  await setPrivileges(page, [])
  await expect(attempts).not.toBeEditable()
  await expect(planner).not.toBeEditable()
})

test('changing messaging provider closes its advanced controls and shows the correct settings', async ({ page }) => {
  await fixtures(page)
  await mount(page, 'core/params/components/MessagingSettingsPanel.vue', { privileges: ['PARAMS_EDIT'] })
  await page.getByRole('tab', { name: /Matrix/ }).click()
  const server = page.getByLabel('Matrix homeserver URL', { exact: true })
  await expect(server).toBeVisible()
  await page.getByText('Advanced settings', { exact: true }).click()
  await page.getByRole('tab', { name: /WhatsApp/ }).click()
  await expect(server).not.toBeVisible()
  await expect(page.locator('.q-expansion-item--expanded')).toHaveCount(0)
  await expandSettings(page)
  await expect(page.getByLabel('Graph API URL', { exact: true })).toBeVisible()
})

test('harness provider preferences keep global defaults and installation help accessible', async ({ page }, testInfo) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/params', { params: [
    { name: 'hermes.default.config', value: 'max_turns: 42', secret: false, configured: true },
    { name: 'hermes.default.data-env', value: 'EXAMPLE=value', secret: false, configured: true },
  ] })
  await mount(page, 'core/params/pages/harnesses/[provider].vue', {
    route: '/params/harnesses/hermes', privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT'],
  })
  // The component test router has a catch-all route; supply the real route parameter.
  await page.evaluate(async () => {
    window.testApp.router.addRoute({ path: '/params/harnesses/:provider', component: { render: () => null } })
    await window.testApp.router.push('/params/harnesses/hermes')
  })
  await expect(page.locator('.harness-preferences__content')).toBeVisible()
  await expect(page.locator('.q-expansion-item--expanded')).toHaveCount(0)
  await expandSettings(page)
  await expect(page.locator('textarea').first()).toHaveValue('max_turns: 42')
  await expect(page.locator('textarea').last()).toHaveValue('EXAMPLE=value')
  await expect(page.getByRole('link', { name: 'Official documentation' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.testApp.dark(true))
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('hermes-mobile-dark.png'), fullPage: true })
})
