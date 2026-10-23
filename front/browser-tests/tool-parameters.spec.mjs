import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const privileges = ['TOOL_ACCESS', 'TOOL_EDIT', 'CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL']
const region = { type: 'string', required: true, default: 'eu', description: 'Choose the service region.', label: 'Service region',
  options: [{ value: 'eu', label: 'Europe' }, { value: 'us', label: 'United States' }] }
const tool = { id: 81, code: 'synthetic_region', label: 'Synthetic regions', can_edit: true, can_disable: true,
  conversation_enabled: false, connection_schema: { params: { region, note: { type: 'string', label: 'Notes', required: false } } }, global_params: {} }

async function toolsRoutes(page) {
  await jsonRoute(page, '**/api/tools', [tool])
  await jsonRoute(page, '**/api/file-share/bridges', [])
  await jsonRoute(page, '**/api/messenger/bridges', [])
}

for (const [locale, label, choice] of [
  ['fr', 'Réponse par défaut', 'Capture d’écran'],
  ['en', 'Default response', 'Screenshot'],
  ['zh', '默认回复', '屏幕截图'],
]) {
  test(`Internal parameter metadata is translated and custom labels stay literal (${locale})`, async ({ page }) => {
    const definition = {
      type: 'string', label: 'tools.connectionParamLabels.default_output',
      options: [{ value: 'capture', label: 'tools.connectionParamOptions.browser.default_output.screenshot' }],
    }
    // Different codes prove labels come from the declared metadata, not inferred parameter/option names.
    await mount(page, 'app/tools/components/ConnectionParamInput.vue', { locale, props: {
      toolCode: 'browser', name: 'response_mode', definition, modelValue: null,
    } })
    const select = page.getByRole('combobox', { name: label, exact: true })
    await expect(select).toHaveValue('')
    await select.press('ArrowDown')
    await page.getByRole('option', { name: choice, exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toBe('capture')
    await page.evaluate(() => window.testApp.setProps({ modelValue: 'capture' }))
    await expect(select).toHaveValue(choice)

    await page.evaluate(() => window.testApp.setProps({ toolCode: 'synthetic_region' }))
    await expect(page.getByRole('combobox', { name: definition.label, exact: true })).toHaveValue(definition.options[0].label)
    await page.evaluate(() => window.testApp.setProps({ definition: {
      type: 'string', label: 'Région du service', options: [{ value: 'eu', label: 'Europe' }],
    }, modelValue: 'eu' }))
    await expect(page.getByRole('combobox', { name: 'Région du service', exact: true })).toHaveValue('Europe')
  })
}

for (const mobile of [false, true]) {
  test(`Connection choices retain codes, submit values and show inherited labels (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 950 })
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
    await mount(page, 'app/connection/components/ConnectionForm.vue', { privileges, props: {
      connection: { id: 42, agent_id: 7, tool_id: 81, active: false }, connectionParams: { region: 'us', note: 'Preserved text' },
      agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }], toolOptions: [{ id: 81, label: tool.label }], tools: [tool],
    } })
    const select = page.getByRole('combobox', { name: 'Service region *', exact: true })
    await expect(select).toHaveValue('United States')
    await expect(page.getByText('region', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Notes', { exact: true })).toHaveValue('Preserved text')
    await select.press('ArrowDown')
    await page.getByRole('option', { name: 'Europe', exact: true }).click()
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'submit').at(-1)?.value.params)).toEqual({ region: 'eu', note: 'Preserved text' })
    await page.screenshot({ path: testInfo.outputPath('connection-parameters.png'), animations: 'disabled' })

    await mount(page, 'app/connection/components/ConnectionForm.vue', { privileges, dark: true, props: {
      connection: { id: 42, agent_id: 7, tool_id: 81, active: false }, connectionParams: {},
      agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }], toolOptions: [{ id: 81, label: tool.label }],
      tools: [{ ...tool, global_params: { region: { configured: true, value: 'us', forced: false } } }],
    } })
    await page.getByText('Inherited global parameters (1)', { exact: true }).click()
    await expect(page.getByText('United States', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Customize', exact: false }).click()
    await expect(page.getByRole('combobox', { name: 'Service region *', exact: true })).toHaveValue('United States')
  })

  test(`Tool editor saves labels and fixed choices and reopens without losing them (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 950 })
    await toolsRoutes(page)
    const writes = []
    let saved = tool
    await page.route('**/api/tools/81', async route => {
      const data = route.request().postDataJSON()
      writes.push(data)
      if (writes.length === 1) {
        await route.fulfill({ status: 503, json: { detail: 'Synthetic save failure' } })
        return
      }
      saved = { ...tool, ...data }
      await route.fulfill({ json: saved })
    })
    await page.route('**/api/tools', route => route.fulfill({ json: [saved] }))
    await mount(page, 'app/tools/components/ToolsList.vue', { privileges })
    await page.getByRole('tab', { name: 'Custom tools', exact: true }).click()
    const row = page.locator(mobile ? '.tool-mobile-card' : 'tbody tr').filter({ hasText: tool.label })
    await row.getByRole('button', { name: 'Edit tool', exact: true }).click()
    const dialog = page.getByRole('dialog')
    const regionEditor = dialog.locator('.connection-param-editor').filter({ has: page.locator('input[value="region"]') })
    await expect(regionEditor.getByLabel('Parameter label', { exact: true })).toHaveValue('Service region')
    await regionEditor.getByLabel('Parameter label', { exact: true }).fill('Deployment region')
    await regionEditor.getByRole('button', { name: 'Add a fixed choice', exact: true }).click()
    await regionEditor.getByLabel('Value *', { exact: true }).last().fill('eu')
    await regionEditor.getByLabel('Choice label', { exact: true }).last().fill('Asia Pacific')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Invalid choices for', { exact: false })).toBeVisible()
    expect(writes).toEqual([])
    await regionEditor.getByLabel('Value *', { exact: true }).last().fill('ap')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Synthetic save failure', { exact: true })).toBeVisible()
    await expect(regionEditor.getByLabel('Choice label', { exact: true }).last()).toHaveValue('Asia Pacific')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes[0]?.connection_schema.params.region).toMatchObject({
      ...region, label: 'Deployment region', options: [...region.options, { value: 'ap', label: 'Asia Pacific' }],
    })
    await expect(dialog).toHaveCount(0)
    expect(writes).toHaveLength(2)
    await row.getByRole('button', { name: 'Edit tool', exact: true }).click()
    await expect(regionEditor.getByLabel('Parameter label', { exact: true })).toHaveValue('Deployment region')
    await expect(regionEditor.getByLabel('Choice label', { exact: true }).last()).toHaveValue('Asia Pacific')
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(dialog).toHaveCount(0)
  })
}

test('Global parameters display fixed choices and store their codes', async ({ page }) => {
  await toolsRoutes(page)
  await jsonRoute(page, '**/api/tools/81/global-params', { tool_id: 81, params: { region: { configured: true, value: 'eu', forced: false } } })
  const writes = []
  await page.route('**/api/tools/81/global-params', route => {
    if (route.request().method() === 'PUT') writes.push(route.request().postDataJSON())
    return route.fulfill({ json: { tool_id: 81, params: { region: { configured: true, value: 'eu', forced: false } } } })
  })
  await mount(page, 'app/tools/components/ToolsList.vue', { privileges })
  await page.getByRole('tab', { name: 'Custom tools', exact: true }).click()
  await page.getByRole('button', { name: 'Global parameters', exact: true }).click()
  await page.getByRole('combobox', { name: 'Service region *', exact: true }).click()
  await page.getByRole('option', { name: 'United States', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes[0]?.params.region.value).toBe('us')
})

const indexingName = 'tools.fileindexing'
const indexing = { type: 'string', required: false, default: 'excluded', builtin: true,
  label: 'tools.connectionParamLabels.fileindexing', description: 'tools.connectionParamDescriptions.fileindexing',
  options: ['excluded', 'known_uris'].map(value => ({ value, label: `tools.connectionParamOptions.fileindexing.${value}` })) }

for (const [locale, label, choice, globalButton, save] of [
  ['fr', 'Indexation des fichiers', 'Uniquement les fichiers déjà connus', 'Paramètres globaux', 'Enregistrer'],
  ['en', 'File indexing', 'Only files already known', 'Global parameters', 'Save'],
  ['zh', '文件索引', '仅已知文件', '全局参数', '保存'],
]) {
  test(`Platform parameters on a custom Tool use the usual translated global controls (${locale})`, async ({ page }) => {
    await toolsRoutes(page)
    const indexedTool = { ...tool, connection_schema: { params: { [indexingName]: indexing } } }
    await jsonRoute(page, '**/api/tools', [indexedTool])
    const writes = []
    await page.route('**/api/tools/81/global-params', route => {
      if (route.request().method() === 'PUT') writes.push(route.request().postDataJSON())
      return route.fulfill({ json: { tool_id: 81, params: { [indexingName]: { configured: true, value: 'excluded', forced: false } } } })
    })
    await mount(page, 'app/tools/components/ToolsList.vue', { locale, privileges })
    await page.getByRole('tab', { name: locale === 'fr' ? 'Outils personnalisés' : locale === 'zh' ? '自定义工具' : 'Custom tools', exact: true }).click()
    await page.getByRole('button', { name: globalButton, exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(indexingName, { exact: true })).toBeVisible()
    await dialog.getByRole('combobox', { name: label, exact: true }).press('ArrowDown')
    await page.getByRole('option', { name: choice, exact: true }).click()
    await dialog.getByRole('button', { name: save, exact: true }).click()
    await expect.poll(() => writes[0]?.params[indexingName]).toMatchObject({ value: 'known_uris', forced: false })
  })
}

for (const mobile of [false, true]) {
  test(`Embedded Console saves its standard parameter override and retains a failed draft (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 950 })
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
    let releaseProvision
    const provisioning = new Promise(resolve => { releaseProvision = resolve })
    let provisions = 0
    await page.route('**/api/console/embedded/provision', async route => {
      if (++provisions === 1) await provisioning
      await route.fulfill({ json: { connection_id: 42, agent_id: 7, agent_code: 'synthetic-agent' } })
    })
    const writes = []
    await page.route('**/api/connections/42/params/bulk', route => {
      writes.push(route.request().postDataJSON())
      return writes.length === 1
        ? route.fulfill({ status: 503, json: { detail: 'Synthetic parameter save failure' } })
        : route.fulfill({ json: [] })
    })
    await mount(page, 'app/connection/components/ConnectionForm.vue', { privileges, props: {
      connection: { id: 42, agent_id: 7, tool_id: 81, active: true }, connectionParams: { host: 'ssh-executor' },
      agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }], toolOptions: [{ id: 81, label: 'Console' }],
      tools: [{ ...tool, code: 'console', connection_schema: { params: { host: { type: 'string' }, [indexingName]: indexing } },
        global_params: { [indexingName]: { configured: true, value: 'known_uris', forced: false } } }],
    } })
    await page.getByText('Inherited global parameters (1)', { exact: true }).click()
    await expect(page.getByText('Only files already known', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Customize', exact: false }).click()
    const select = page.getByRole('combobox', { name: 'File indexing', exact: true })
    await select.press('ArrowDown')
    await page.getByRole('option', { name: 'Disabled', exact: true }).click()
    await page.getByRole('button', { name: 'Use local console', exact: true }).click()
    await expect.poll(() => provisions).toBe(1)
    await select.press('ArrowDown')
    await page.getByRole('option', { name: 'Only files already known', exact: true }).click()
    releaseProvision()
    await expect(page.getByText('Synthetic parameter save failure', { exact: false })).toBeVisible()
    expect(writes[0].params[indexingName]).toBe('excluded')
    await expect(select).toHaveValue('Only files already known')
    await page.getByRole('button', { name: 'Use local console', exact: true }).click()
    await expect.poll(() => writes.length).toBe(2)
    expect(writes[1]).toEqual({ connection_id: 42, params: { [indexingName]: 'known_uris' } })
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'configured').length)).toBe(1)
  })
}

for (const mobile of [false, true]) {
  test(`Native management scope belongs to the connection and retains its value (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
    const name = 'tools.management_scope'
    const scopeTool = { ...tool, id: 82, code: 'skills', label: 'Skills', can_edit: false,
      connection_schema: { params: { [name]: { type: 'string', required: false, default: 'usage', builtin: true,
        label: 'tools.connectionParamLabels.managementScope', description: 'tools.connectionParamDescriptions.managementScope',
        options: ['usage', 'personal', 'team', 'all'].map(value => ({ value, label: `tools.connectionParamOptions.managementScope.${value}` })),
      } } }, global_params: {} }
    const props = { connection: { id: 43, agent_id: 7, tool_id: 82, active: true },
      connectionParams: { [name]: 'personal' },
      agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }],
      toolOptions: [{ id: 82, label: 'Skills' }], tools: [scopeTool] }
    await mount(page, 'app/connection/components/ConnectionForm.vue', { privileges, props })
    const select = page.getByRole('combobox', { name: 'Management scope', exact: true })
    await expect(select).toHaveValue('Management for this agent only')
    await select.click()
    await expect(page.getByRole('option')).toHaveText(['Usage without modification rights', 'Management for this agent only', 'Team management', 'Global management without restrictions'])
    await page.getByRole('option', { name: 'Team management', exact: true }).click()
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'submit').at(-1)?.value.params)).toEqual({ [name]: 'team' })
    await page.evaluate(() => window.testApp.setProps({ connectionParams: { 'tools.management_scope': 'team' } }))
    await expect(select).toHaveValue('Team management')
    await page.screenshot({ path: testInfo.outputPath('connection-management-scope.png'), animations: 'disabled', fullPage: true })
    await mount(page, 'app/connection/components/ConnectionForm.vue', {
      privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'], props,
    })
    await expect(page.getByText('Management for this agent only', { exact: true })).toBeVisible()
    await expect(page.getByRole('combobox', { name: 'Management scope', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'submit').at(-1)?.value.params)).toEqual({})
  })
}


test('Saving a scoped connection uses one request, preserves failures and reopens with its saved scope', async ({ page }) => {
  const name = 'tools.management_scope'
  const scopedTool = { ...tool, id: 82, code: 'skills', label: 'Skills', can_edit: false,
    connection_schema: { params: { [name]: { type: 'string', required: false, default: 'usage', builtin: true,
      label: 'tools.connectionParamLabels.managementScope',
      options: ['usage', 'personal', 'team', 'all'].map(value => ({ value, label: `tools.connectionParamOptions.managementScope.${value}` })),
    } } }, global_params: {} }
  let connection = { id: 43, agent_id: 7, tool_id: 82, active: true }
  let params = { [name]: 'personal' }
  const writes = []
  await jsonRoute(page, '**/api/tools', [scopedTool])
  await jsonRoute(page, '**/api/file-share/bridges', [])
  await jsonRoute(page, '**/api/messenger/bridges', [])
  await jsonRoute(page, '**/api/mail/approvers', [])
  await jsonRoute(page, '**/api/mail/status', { enabled: false })
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, code: 'synthetic-agent', first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
  await page.route('**/api/connections?*', route => route.fulfill({ json: [connection] }))
  await page.route('**/api/connections/43/params?*', route => route.fulfill({ json: {
    connection_id: 43, tool_id: 82, agent_id: 7, params, configured_params: [],
  } }))
  await page.route('**/api/connections/43', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    if (writes.length === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic configuration failure' } })
    params = body.params
    connection = { ...connection, active: body.active }
    return route.fulfill({ json: connection })
  })
  await mount(page, 'app/connection/components/ConnectionList.vue', { privileges })
  const row = page.locator('tbody tr').filter({ hasText: 'Skills' })
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const scope = dialog.getByRole('combobox', { name: 'Management scope', exact: true })
  await scope.click()
  await page.getByRole('option', { name: 'Team management', exact: true }).click()
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Synthetic configuration failure')
  await expect(scope).toHaveValue('Team management')
  expect(params[name]).toBe('personal')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toHaveLength(2)
  expect(writes[1]).toMatchObject({ active: true, params: { [name]: 'team' } })
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(scope).toHaveValue('Team management')
})
