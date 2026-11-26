import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const tools = [
  ...['galaris', 'chat', 'memory', 'file_sharing'].map((code, index) => ({
    id: index + 1, code, label: code, description: 'System service description.',
    can_disable: false, can_edit: false,
    connection_schema: { params: code === 'chat' ? {
      'chat.channel_enabled': { type: 'boolean', default: 'true', required: false,
        label: 'services.connectionParamLabels.chatChannel' },
    } : {} }, global_params: {},
  })),
  { id: 5, code: 'matrix', label: 'Optional Service', description: '**Team handbook** for this connector.',
    can_disable: true, can_edit: true, connection_schema: { params: {} }, global_params: {} },
  { id: 6, code: 'empty', label: 'No description', description: '', can_disable: true,
    can_edit: true, connection_schema: { params: {} }, global_params: {} },
]
const connections = tools.slice(0, 5).map(tool => ({ id: tool.id, service_id: tool.id, agent_id: 7, active: true }))
const permissionOptions = rows => rows.map(connection => {
  const tool = tools.find(tool => tool.id === connection.service_id)
  return { ...connection, service_code: tool.code, service_label: tool.label,
    service_can_edit: tool.can_edit, service_can_disable: tool.can_disable }
})
async function connectionRoutes(page, rows) {
  await jsonRoute(page, '**/api/connections?*', rows)
  await jsonRoute(page, '**/api/connections/permission-options?*', permissionOptions(rows))
}

const protocolParameters = {
  'imap_smtp.mail': Object.fromEntries([
    ['imap_host', 'string', '', true], ['imap_port', 'integer', '993', true], ['imap_security', 'string', 'tls', true],
    ['smtp_host', 'string', '', true], ['smtp_port', 'integer', '465', true], ['smtp_security', 'string', 'tls', true],
  ].map(([name, type, value, required], order) => [name, { type, default: value, required, builtin: true, order,
    label: 'services.connectionParamLabels.' + name, section: 'services.protocolSections.' + (name.startsWith('smtp_') ? 'smtp' : 'imap'),
    options: name.endsWith('_security') ? [{ value: 'tls' }, { value: 'starttls' }] : [] }])),
  'caldav.calendar': Object.fromEntries([
    ['source_kind', 'string', 'caldav'],
    ['timezone', 'string', 'Europe/Paris'], ['workday_start', 'string', '09:00'],
    ['workday_end', 'string', '18:00'], ['slot_step_minutes', 'integer', '15'],
  ].map(([name, type, value], order) => [name, { type, default: value, required: false, builtin: true, order,
    label: 'services.connectionParamLabels.' + name,
    options: name === 'source_kind' ? [{ value: 'caldav', label: 'services.connectionParamOptions.calendar.source_kind.caldav' },
      { value: 'ical', label: 'services.connectionParamOptions.calendar.source_kind.ical' }] : [] }])),
}
const mailConnectionDefinitions = Object.fromEntries([
  ['email_address', 'string', true], ['password', 'password', true],
  ['allowed_mailboxes', 'string', false], ['approver_user_id', 'user', false], ['poll_interval_minutes', 'integer', false],
].map(([name, type, required]) => [name, { type, required, builtin: true, default: '', label: 'services.connectionParamLabels.' + name,
  widget: name === 'allowed_mailboxes' ? 'mail_folder_tree' : '' }]))
const mailBindings = Object.fromEntries(Object.entries({ email_address: ['email_address', 'email'], imap_username: ['email_address', 'login'], imap_password: ['password', 'password'],
  smtp_username: ['email_address', 'login'], smtp_password: ['password', 'password'], allowed_mailboxes: ['allowed_mailboxes', 'folders'], approver_user_id: ['approver_user_id', 'user_id'],
  poll_interval_minutes: ['poll_interval_minutes', 'poll_interval_minutes'],
}).map(([role, [legacy_parameter, parameter]]) => [role, { parameter, legacy_parameter, label: 'services.connectionParamLabels.' + role,
  section: 'services.protocolSections.' + (role.startsWith('smtp_') || ['email_address', 'approver_user_id'].includes(role) ? 'smtp' : 'imap'),
  definition: { ...mailConnectionDefinitions[legacy_parameter], ...(parameter === 'login' ? { label: 'services.connectionParamLabels.login' } : {}) } }]))
const calendarBindings = Object.fromEntries([
  ['url', 'url', 'password', true], ['username', 'login', 'string', false], ['password', 'password', 'password', false],
].map(([role, parameter, type, required]) => [role, { parameter, legacy_parameter: role,
  label: 'services.connectionParamLabels.' + role, definition: { type, required, builtin: true, label: 'services.connectionParamLabels.' + role } }]))
const capabilityCatalogue = Object.entries({ mcp: ['http', 'sse', 'stdio'], api: ['rest'],
  file_share: ['nextcloud', 'synthetic_share'], messenger: ['matrix', 'synthetic_messenger'],
  listener: ['webhook'], mail: ['imap_smtp'], calendar: ['caldav'],
}).map(([code, protocols]) => ({ code, label: 'services.capabilityLabels.' + code, builtin: true,
  protocols: protocols.map(protocol => ({ value: protocol + '.' + code, capability: code,
    label: protocol.startsWith('synthetic_') ? 'Synthetic ' + (code === 'file_share' ? 'share' : 'messenger') : 'services.protocolLabels.' + protocol,
    builtin: !protocol.startsWith('synthetic_'), parameters: protocolParameters[protocol + '.' + code] ?? {}, connection_parameters: code === 'mail' ? mailBindings : code === 'calendar' ? calendarBindings : {} })),
}))
async function addCapability(page, label) {
  await page.getByRole('dialog').getByRole('button', { name: 'Add protocol', exact: true }).click()
  const picker = page.getByRole('menu', { name: 'Add protocol', exact: true })
  await picker.getByRole('menuitem', { name: label.split(' · ').at(-1), exact: true }).click()
  await expect(picker).toHaveCount(0)
}
async function removeCapability(page, name) {
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name, exact: true }).click()
  await dialog.getByRole('button', { name: 'Delete protocol', exact: true }).click()
  const confirmation = page.getByRole('dialog').filter({ has: page.getByText(`Delete protocol ${name} from this Service?`, { exact: false }) })
  await expect(dialog.getByRole('tab', { name, exact: true })).toBeVisible()
  await confirmation.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(confirmation).toHaveCount(0)
  await expect(dialog.getByRole('tab', { name, exact: true })).toHaveCount(0)
}

const privileges = ['SERVICE_ACCESS', 'SERVICE_EDIT', 'CONNECTION_ACCESS', 'CONNECTION_EDIT', 'PERMISSION_DECIDE', 'AGENT_MANAGE_ALL']

for (const width of [390, 1400]) {
  test(`A provider Service combines Mail and Calendar, preserves them on reopening and configures shared servers (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await routes(page)
    let saved
    let rejectCreate = true
    const writes = []
    function publicRow(body) {
      return { ...saved, ...body, id: 92, has_mail: body.mail_config !== null, has_calendar: body.calendar_config !== null,
        can_edit: true, can_disable: true, global_params: {} }
    }
    await page.route('**/api/services', async route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: saved ? [saved] : [] })
      const body = route.request().postDataJSON()
      writes.push(body)
      if (rejectCreate) { rejectCreate = false; return route.fulfill({ status: 422, json: { detail: 'Synthetic settings failure' } }) }
      saved = publicRow(body)
      return route.fulfill({ status: 201, json: saved })
    })
    await page.route('**/api/services/92', async route => {
      const body = route.request().postDataJSON()
      writes.push(body)
      saved = publicRow(body)
      return route.fulfill({ json: saved })
    })
    await mount(page, 'app/services/components/ServicesList.vue', { privileges, dark: width === 390 })
    await page.getByRole('button', { name: 'New service', exact: true }).click()
    await page.getByRole('button', { name: 'Create a custom service', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Technical name', { exact: false }).fill('synthetic-provider')
    await dialog.getByLabel('Label *', { exact: true }).fill('Synthetic provider')
    await addCapability(page, 'Mail · IMAP & SMTP')
    const binding = name => dialog.getByRole('group', { name, exact: true }).getByRole('combobox', { name: 'Connection parameter', exact: true })
    const mapParameter = async (role, option) => {
      await binding(role).click()
      await page.getByRole('option', { name: option, exact: true }).click()
      await expect(page.getByRole('option')).toHaveCount(0)
    }
    await expect(binding('IMAP password')).toHaveValue('')
    await mapParameter('IMAP username', 'New parameter…')
    await expect(binding('IMAP username')).toHaveValue('login')
    await mapParameter('IMAP password', 'New parameter…')
    await mapParameter('SMTP username', 'login')
    await mapParameter('Email address', 'login')
    await mapParameter('SMTP password', 'password')
    await expect(binding('SMTP password')).toHaveValue('password')
    await mapParameter('Allowed mail folders', 'New parameter…')
    await mapParameter('Inbox polling interval (minutes)', 'New parameter…')
    await expect(dialog.getByLabel('IMAP server *', { exact: true })).toBeVisible()
    await dialog.getByLabel('IMAP server *', { exact: true }).fill('imap.example.test')
    await dialog.getByLabel('SMTP server *', { exact: true }).fill('smtp.example.test')
    await dialog.getByLabel('SMTP port *', { exact: true }).fill('587')
    await expect(dialog.getByRole('textbox', { name: 'Password *', exact: true })).toHaveCount(0)
    await mapParameter('SMTP password', 'New parameter…')
    await expect(binding('SMTP password')).toHaveValue('password_2')
    await addCapability(page, 'Calendar · CalDAV')
    await expect(binding('HTTPS CalDAV URL')).toHaveValue('')
    await mapParameter('HTTPS CalDAV URL', 'New parameter…')
    await mapParameter('Username', 'login')
    await mapParameter('Password', 'password')
    await dialog.getByLabel('Time zone', { exact: true }).fill('Europe/London')
    await dialog.getByLabel('Workday start', { exact: true }).fill('08:30')
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.locator('.q-notification__message')).toContainText('Synthetic settings failure')
    await expect(dialog.getByLabel('Time zone', { exact: true })).toHaveValue('Europe/London')
    await page.screenshot({ path: testInfo.outputPath('calendar-settings.png'), animations: 'disabled' })
    await dialog.getByRole('tab', { name: 'IMAP & SMTP', exact: true }).click()
    await expect(dialog.getByLabel('IMAP server *', { exact: true })).toHaveValue('imap.example.test')
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[1]).toMatchObject({ code: 'synthetic-provider', capabilities: ['imap_smtp.mail', 'caldav.calendar'],
      mail_config: { settings: { imap_host: 'imap.example.test', smtp_host: 'smtp.example.test', smtp_port: '587' },
        param_map: { email_address: 'login', imap_username: 'login', imap_password: 'password', smtp_username: 'login', smtp_password: 'password_2', allowed_mailboxes: 'folders',
          poll_interval_minutes: 'poll_interval_minutes' } },
      calendar_config: { settings: { source_kind: 'caldav', timezone: 'Europe/London', workday_start: '08:30' }, param_map: { url: 'url', username: 'login', password: 'password' } } })
    expect(writes[1]).not.toHaveProperty('global_params')
    expect(Object.keys(writes[1].connection_schema.params)).toEqual(['login', 'password', 'folders', 'poll_interval_minutes', 'password_2', 'url'])
    const row = page.getByRole('article').filter({ hasText: 'Synthetic provider' })
    await expect(row).toContainText('Mail')
    await expect(row).toContainText('Calendar')
    await page.screenshot({ path: testInfo.outputPath('provider-list.png'), animations: 'disabled' })
    // A historical binding is retired when the Service is reopened and saved.
    saved.calendar_config.param_map.action_kind = 'retired-action'
    await row.getByRole('button', { name: 'Edit service', exact: true }).click()
    await expect(dialog.getByRole('tab', { name: 'IMAP & SMTP', exact: true })).toBeVisible()
    await expect(dialog.getByRole('tab', { name: 'CalDAV', exact: true })).toBeVisible()
    await expect(dialog.getByLabel('IMAP server *', { exact: true })).toHaveValue('imap.example.test')
    await expect(dialog.getByLabel('SMTP port *', { exact: true })).toHaveValue('587')
    await expect(binding('SMTP password')).toHaveValue('password_2')
    await expect(binding('Inbox polling interval (minutes)')).toHaveValue('poll_interval_minutes')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[2]).not.toHaveProperty('global_params')
    expect(writes[2].mail_config.param_map).toMatchObject({ imap_password: 'password', smtp_password: 'password_2' })
    expect(writes[2].connection_schema.params.password_2.type).toBe('password')
    expect(writes[2].connection_schema.params.folders.widget).toBe('mail_folder_tree')
    expect(writes[2].calendar_config.param_map).not.toHaveProperty('action_kind')
    await row.getByRole('button', { name: 'Edit service', exact: true }).click()
    await dialog.getByRole('tab', { name: 'CalDAV', exact: true }).click()
    await expect(dialog.getByLabel('Time zone', { exact: true })).toHaveValue('Europe/London')
    await expect(binding('HTTPS CalDAV URL')).toHaveValue('url')
    await expect(binding('Password')).toHaveValue('password')
    await dialog.getByRole('tab', { name: 'IMAP & SMTP', exact: true }).click()
    await dialog.getByRole('button', { name: 'Add protocol', exact: true }).click()
    const picker = page.getByRole('menu', { name: 'Add protocol', exact: true })
    await expect(picker.getByRole('menuitem', { name: 'IMAP & SMTP', exact: true })).toBeDisabled()
    await picker.getByRole('menuitem', { name: 'HTTP', exact: true }).hover()
    await page.screenshot({ path: testInfo.outputPath('protocol-options.png'), animations: 'disabled' })
    await page.keyboard.press('Escape')
    await expect(picker).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('provider-protocols.png'), animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Delete protocol', exact: true }).click()
    const confirmation = page.getByRole('dialog').filter({ hasText: 'Delete protocol IMAP & SMTP from this Service?' })
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(confirmation).toHaveCount(0)
    await expect(dialog.getByRole('tab', { name: 'IMAP & SMTP', exact: true })).toBeVisible()
    await removeCapability(page, 'IMAP & SMTP')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(4)
    expect(writes[3]).toMatchObject({ capabilities: ['caldav.calendar'], mail_config: null,
      calendar_config: { settings: { timezone: 'Europe/London' } } })
    expect(writes[3]).not.toHaveProperty('global_params')
    await expect(dialog).toHaveCount(0)
    await expect(row).not.toContainText('Mail')
    await expect(row).toContainText('Calendar')
  })

  test(`Connection Service selection groups the allowed built-in and custom choices (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await routes(page)
    const locale = width === 390 ? 'fr' : 'en'
    const browserTool = { id: 7, code: 'browser', label: 'Browser', can_edit: false, can_disable: true, connection_schema: { params: {} }, global_params: {} }
    await mount(page, 'app/connection/components/ConnectionForm.vue', { locale, privileges, props: {
      defaultAgentId: 7,
      agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }],
      serviceOptions: [browserTool, tools[4], tools[5]].map(tool => ({ id: tool.id, label: tool.label })),
      tools: [...tools, browserTool],
    } })
    const select = page.getByRole('combobox', { name: locale === 'fr' ? 'Service' : 'Service', exact: true })
    await select.click()
    const popup = page.getByRole('listbox')
    await expect(popup.getByText('Galaris', { exact: true })).toBeVisible()
    await expect(popup.getByText(locale === 'fr' ? 'Personnalisé' : 'Custom', { exact: true })).toBeVisible()
    await expect(popup.getByRole('option', { name: 'Galaris', exact: true })).toHaveCount(0)
    await expect(popup.getByRole('option', { name: locale === 'fr' ? 'Personnalisé' : 'Custom', exact: true })).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('grouped-connection-tools.png'), animations: 'disabled' })
    await popup.getByRole('option', { name: locale === 'fr' ? 'Navigateur' : 'Browser', exact: true }).click()
    await expect(popup).toHaveCount(0)
    await select.click()
    await page.getByRole('option', { name: 'No description', exact: true }).click()
    await page.getByRole('button', { name: locale === 'fr' ? 'Créer' : 'Create', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.find(event => event.name === 'submit')?.value)).toMatchObject({
      data: { agent_id: 7, service_id: 6, active: true },
    })
  })

  test(`Service deletion requires the current impact, retains failures and ignores closed previews (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await routes(page)
    let reads = 0
    let releaseOld
    const oldResponse = new Promise(resolve => { releaseOld = resolve })
    await page.route('**/api/services/6/deletion-impact', async route => {
      reads++
      const read = reads
      if (read === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable impact' } })
      if (read === 2) await oldResponse
      return route.fulfill({ json: { service_id: 6, version: read === 4 ? 'review-2' : 'review-1',
        deleted: [{ kind: 'connections', count: read === 2 ? 99 : read === 4 ? 2 : 1 }], detached_count: 1 } })
    })
    const removals = []
    await page.route('**/api/services/6?*', async route => {
      const url = new URL(route.request().url())
      removals.push(Object.fromEntries(url.searchParams))
      if (removals.length === 1) return route.fulfill({ status: 409, json: { detail: 'Synthetic impact changed' } })
      return route.fulfill({ status: 204 })
    })
    await mount(page, 'app/services/components/ServicesList.vue', { privileges, dark: width === 390 })
    await page.getByRole('tab', { name: 'Custom services', exact: true }).click()
    const row = page.getByRole('article').filter({ hasText: 'No description' })
    const dialog = page.getByRole('dialog')
    const confirm = dialog.getByRole('button', { name: 'Delete', exact: true })
    await row.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Could not calculate related data')
    await expect(confirm).toBeDisabled()
    await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect.poll(() => reads).toBe(2)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await row.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(dialog).toContainText('Agent connections : 1')
    releaseOld()
    await expect(dialog).not.toContainText('99')
    expect(removals).toEqual([])
    await confirm.click()
    await expect(dialog.getByRole('alert')).toContainText('Related data has changed')
    await expect(dialog).toContainText('Agent connections : 2')
    await page.screenshot({ path: testInfo.outputPath('confirmed-tool-deletion.png'), animations: 'disabled' })
    await confirm.click()
    await expect(dialog).toHaveCount(0)
    await expect(row).toHaveCount(0)
    expect(removals).toEqual([
      { cascade: 'true', expected_version: 'review-1' },
      { cascade: 'true', expected_version: 'review-2' },
    ])
    await page.getByRole('tab', { name: 'Galaris built-in services', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Optional Service', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Galaris', exact: true })).toBeVisible()
  })

  test(`REST configuration survives save and reopening, and can be disabled (${width})`, async ({ page }, testInfo) => {
    test.setTimeout(60_000)
    await page.setViewportSize({ width, height: 1000 })
    await routes(page)
    const rows = []
    const writes = []
    const generationRequests = []
    const generatedTask = '0b98f743-fc9a-4829-bec5-0bc4636a2fb9'
    await page.route('**/api/services/91/generate-skill', async route => {
      generationRequests.push(route.request().postDataJSON())
      if (generationRequests.length === 1) {
        return route.fulfill({ status: 503, json: { detail: 'Synthetic task admission failure' } })
      }
      return route.fulfill({ status: 202, json: { task_id: generatedTask } })
    })
    await page.route('**/api/services', async route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: rows })
      const body = route.request().postDataJSON()
      writes.push(body)
      const row = { ...body, id: 91, has_api: !!body.rest_config, can_edit: true, can_disable: true, global_params: {} }
      rows.push(row)
      return route.fulfill({ status: 201, json: row })
    })
    await page.route('**/api/services/91', async route => {
      const body = route.request().postDataJSON()
      writes.push(body)
      Object.assign(rows[0], body, { has_api: !!body.rest_config })
      return route.fulfill({ json: rows[0] })
    })
    await mount(page, 'app/services/components/ServicesList.vue', {
      privileges: [...privileges, 'TASK_EDIT', 'SKILL_EDIT'], dark: width === 390,
    })
    await page.getByRole('button', { name: 'New service', exact: true }).click()
    await page.getByRole('button', { name: 'Create a custom service', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Technical name', { exact: false }).fill('synthetic_rest')
    await dialog.getByLabel('Label *', { exact: true }).fill('Synthetic REST service')
    const createButton = dialog.getByRole('button', { name: 'Create', exact: true })
    await expect(createButton).toBeDisabled()
    await page.screenshot({ path: testInfo.outputPath('empty-protocol-tabs.png'), animations: 'disabled' })
    await dialog.locator('form').evaluate(form => form.requestSubmit())
    await expect(page.locator('.q-notification__message')).toContainText('Add at least one protocol to create the service.')
    expect(writes).toEqual([])
    for (const [name, protocol] of [['MCP', 'HTTP'], ['API', 'REST'], ['File sharing', 'Nextcloud'], ['Messaging', 'Matrix'], ['Listener', 'Webhook'], ['Mail', 'IMAP & SMTP'], ['Calendar', 'CalDAV']]) {
      await addCapability(page, name + ' · ' + protocol)
      await expect(createButton).toBeEnabled()
      await removeCapability(page, protocol)
      await expect(createButton).toBeDisabled()
    }
    await addCapability(page, 'API · REST')
    await expect(dialog.getByRole('tab', { name: 'REST', exact: true })).toBeVisible()
    await expect(dialog.getByText('No authentication', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Secret API token parameter', { exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('group', { name: /^Parameter / })).toHaveCount(0)
    await expect(dialog.getByLabel('API base URL', { exact: true })).toHaveValue('')
    const generate = dialog.getByRole('button', { name: 'Generate a skill', exact: true })
    await expect(generate).toHaveCount(0)
    await dialog.getByLabel('API base URL', { exact: true }).fill('https://api.example.test/v1')
    await page.screenshot({ path: testInfo.outputPath('rest-no-auth.png'), animations: 'disabled' })
    await createButton.click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('tab', { name: 'Custom services', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByText('Synthetic REST service', { exact: true })).toBeVisible()
    expect(writes[0].rest_config.auth.type).toBe('none')
    expect(writes[0].connection_schema.params).toEqual({})

    await page.getByRole('button', { name: 'Edit service', exact: true }).click()
    await dialog.getByRole('tab', { name: 'REST', exact: true }).click()
    await expect(dialog.getByText('No authentication', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('group', { name: /^Parameter / })).toHaveCount(0)
    await dialog.getByLabel('API authentication', { exact: true }).click()
    await page.getByRole('option', { name: 'Bearer token', exact: true }).click()
    await expect(dialog.getByLabel('Secret API token parameter', { exact: true })).toHaveValue('')
    for (const name of ['token', 'token_2']) {
      await dialog.getByLabel('Secret API token parameter', { exact: true }).click()
      await page.getByRole('option', { name: 'New parameter…', exact: true }).click()
      await expect(page.getByRole('option', { name: 'New parameter…', exact: true })).toHaveCount(0)
      await expect(dialog.getByText(name, { exact: true })).toBeVisible()
    }
    await dialog.getByRole('button', { name: 'Add a header', exact: true }).click()
    await dialog.getByLabel('Header name *', { exact: true }).fill('X-Synthetic')
    await dialog.getByLabel('Param containing the value', { exact: true }).click()
    await page.getByRole('option', { name: 'New parameter…', exact: true }).click()
    await expect(page.getByRole('option', { name: 'New parameter…', exact: true })).toHaveCount(0)
    await expect(dialog.getByText('x_synthetic', { exact: true })).toBeVisible()
    const confirmation = page.getByRole('dialog').filter({ hasText: 'Delete parameter' })
    const parameter = name => dialog.getByRole('group', { name: `Parameter ${name}`, exact: true })
    await parameter('token_2').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(confirmation).toContainText('REST API')
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(confirmation).toHaveCount(0)
    await expect(dialog.getByText('token_2', { exact: true })).toBeVisible()
    await parameter('x_synthetic').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(confirmation).toContainText('REST API')
    await page.locator('.q-dialog__backdrop').last().click({ position: { x: 2, y: 2 } })
    await expect(confirmation).toHaveCount(0)
    await expect(parameter('x_synthetic')).toBeVisible()
    await parameter('token_2').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(confirmation).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('used-parameter-confirmation.png'), animations: 'disabled' })
    await confirmation.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(confirmation).toHaveCount(0)
    await expect(parameter('token_2')).toHaveCount(0)
    await dialog.getByLabel('Secret API token parameter', { exact: true }).click()
    await page.getByRole('option', { name: 'token', exact: true }).click()
    await expect(dialog.getByText('Galaris adds no per-operation authorization.', { exact: false })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('rest-configuration.png'), animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[1].rest_config.auth).toMatchObject({ type: 'bearer', param: 'token' })
    expect(writes[1].rest_config.header_params).toEqual({ 'X-Synthetic': 'x_synthetic' })
    expect(writes[1].rest_config.base_url).toBe('https://api.example.test/v1')
    expect(Object.keys(writes[1].connection_schema.params).sort()).toEqual(['token', 'x_synthetic'])
    expect(writes[1].connection_schema.params.token.type).toBe('password')
    expect(writes[1].connection_schema.params.x_synthetic.type).toBe('string')
    await page.getByRole('button', { name: 'Edit service', exact: true }).click()
    await dialog.getByRole('tab', { name: 'REST', exact: true }).click()
    await expect(dialog.getByLabel('API base URL', { exact: true })).toHaveValue('https://api.example.test/v1')
    await expect(dialog.getByText('token', { exact: true })).toBeVisible()
    await expect(dialog.getByText('x_synthetic', { exact: true })).toBeVisible()
    await generate.click()
    await expect(dialog.getByRole('alert')).toHaveText('Synthetic task admission failure')
    await generate.click()
    await expect(dialog.getByRole('link', { name: 'Track the task' })).toHaveAttribute('href', `/task?task_id=${generatedTask}`)
    expect(generationRequests).toHaveLength(2)
    expect(generationRequests[0]).toEqual({ operation_id: expect.any(String) })
    expect(generationRequests[1]).toEqual(generationRequests[0])
    expect(writes).toHaveLength(2)
    await page.screenshot({ path: testInfo.outputPath('rest-skill-task.png'), animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[2].rest_config).toEqual(writes[1].rest_config)
    await page.getByRole('button', { name: 'Edit service', exact: true }).click()
    await removeCapability(page, 'REST')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[3].rest_config).toBeNull()
  })

  test(`Driver parameter menus create and assign typed parameters, including an empty list (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await routes(page)
    const bridgeParams = [{ key: 'password', label: 'Synthetic credential', type: 'password', required: true }]
    await jsonRoute(page, '**/api/file-share/bridges', [
      { service: 'synthetic_share', label: 'Synthetic share', supports_share: true, params: bridgeParams },
    ])
    await jsonRoute(page, '**/api/messenger/bridges', [
      { service: 'synthetic_messenger', label: 'Synthetic messenger', settings: [], params: bridgeParams },
    ])
    let saved
    await page.route('**/api/services', async route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: [] })
      saved = route.request().postDataJSON()
      return route.fulfill({ status: 201, json: { ...saved, id: 92, can_edit: true, can_disable: true, global_params: {} } })
    })
    await mount(page, 'app/services/components/ServicesList.vue', { privileges })
    await page.getByRole('button', { name: 'New service', exact: true }).click()
    await page.getByRole('button', { name: 'Create a custom service', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Technical name', { exact: false }).fill('synthetic_drivers')
    await dialog.getByLabel('Label *', { exact: true }).fill('Synthetic drivers')
    await addCapability(page, 'MCP · HTTP')
    await dialog.getByLabel('URL *', { exact: true }).fill('https://mcp.example.test')
    await dialog.getByLabel('Auth type', { exact: true }).click()
    await page.getByRole('option', { name: 'basic — Authorization: Basic', exact: true }).click()
    const login = dialog.getByLabel('Login param', { exact: true })
    await login.press('ArrowDown')
    await expect(page.getByRole('option', { name: 'New parameter…', exact: true })).toBeVisible()
    await login.press('ArrowDown')
    await login.press('Enter')
    await expect(page.getByRole('option', { name: 'New parameter…', exact: true })).toHaveCount(0)
    await expect(dialog.getByLabel('Name *', { exact: true }).nth(0)).toHaveValue('login')
    await expect(dialog.getByText('login', { exact: true })).toBeVisible()
    await dialog.getByLabel('Password param', { exact: true }).click()
    await page.getByRole('option', { name: 'New parameter…', exact: true }).click()
    await expect(page.getByRole('option', { name: 'New parameter…', exact: true })).toHaveCount(0)
    await expect(dialog.getByLabel('Name *', { exact: true }).nth(1)).toHaveValue('password')
    for (const capability of ['File sharing · Synthetic share', 'Messaging · Synthetic messenger']) {
      await addCapability(page, capability)
      await expect(dialog.getByLabel('Connection parameter', { exact: true })).toHaveCount(1)
      await dialog.getByLabel('Connection parameter', { exact: true }).click()
      await page.getByRole('option', { name: 'New parameter…', exact: true }).click()
      await expect(page.getByRole('option', { name: 'New parameter…', exact: true })).toHaveCount(0)
    }
    for (const [name, usage] of [['password', 'MCP'], ['password_2', 'File sharing'], ['password_3', 'Messaging']]) {
      await dialog.getByRole('group', { name: `Parameter ${name}`, exact: true }).getByRole('button', { name: 'Delete', exact: true }).click()
      const confirmation = page.getByRole('dialog').filter({ hasText: 'Delete parameter' })
      await expect(confirmation.getByRole('listitem')).toHaveText(usage)
      await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(confirmation).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath('created-driver-parameters.png'), animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(saved.mcp_config.auth).toMatchObject({ login_param: 'login', password_param: 'password' })
    expect(saved.file_share_config.param_map).toEqual({ password: 'password_2' })
    expect(saved.messenger_config.param_map).toEqual({ password: 'password_3' })
    expect(Object.fromEntries(Object.entries(saved.connection_schema.params).map(([name, param]) => [name, param.type]))).toEqual({
      login: 'string', password: 'password', password_2: 'password', password_3: 'password',
    })
  })
}

for (const mobile of [false, true]) {
  for (const defaultState of ['enabled', 'disabled', 'ask']) {
    test(`Global function policies are explicit and connections can inherit (${mobile ? 'mobile' : 'desktop'}, ${defaultState})`, async ({ page }) => {
      await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
      await routes(page)
      await connectionRoutes(page, [connections[4]])
      const locale = mobile ? 'fr' : 'en'
      const labels = mobile
        ? { enabled: 'Activé', disabled: 'Désactivé', ask: 'Sur demande', inherit: 'Hériter', global: 'Global (tous)', connection: 'Cette connexion' }
        : { enabled: 'Enabled', disabled: 'Disabled', ask: 'Ask', inherit: 'Inherit', global: 'Global (all)', connection: 'This connection' }
      const policy = {
        key: 'tool:external_read', name: 'external_read', description: 'Read synthetic content.', capability_kind: 'tool',
        connection_state: 'enabled', global_state: 'default', default_state: defaultState,
        effective_state: 'enabled', effective: true, state_source: 'connection',
      }
      const writes = []
      let finishFirstWrite
      const firstWriteReady = new Promise(resolve => { finishFirstWrite = resolve })
      await page.route('**/api/connections/5/functions', route => route.fulfill({ json: {
        success: true, message: '', functions: [policy, {
          ...policy, key: 'tool:external_list', name: 'external_list',
          connection_state: 'default', global_state: 'enabled',
          effective_state: 'enabled', state_source: 'tool',
        }, {
          ...policy, key: 'tool:external_approve', name: 'external_approve',
          connection_state: 'default', global_state: 'ask',
          effective_state: 'ask', state_source: 'tool',
        }, {
          ...policy, key: 'tool:external_blocked', name: 'external_blocked',
          connection_state: 'disabled', global_state: 'enabled',
          effective_state: 'disabled', effective: false, state_source: 'connection',
        }],
      } }))
      await page.route('**/api/connections/5/capabilities', async route => {
        const request = route.request().postDataJSON()
        writes.push(request)
        if (writes.length === 1) await firstWriteReady
        policy[request.global_policy ? 'global_state' : 'connection_state'] = request.state
        if (request.global_policy && request.inherit_connection) policy.connection_state = 'default'
        const globalState = policy.global_state === 'default' ? policy.default_state : policy.global_state
        policy.effective_state = policy.connection_state === 'default' ? globalState : policy.connection_state
        policy.effective = policy.effective_state !== 'disabled'
        policy.state_source = policy.connection_state === 'default' ? 'tool' : 'connection'
        return route.fulfill({ json: { ...policy, local_override_count: policy.connection_state === 'default' ? 0 : 1 } })
      })
      await mount(page, 'app/connection/components/AuthorizationManager.vue', { locale, privileges })
      const stateFilter = page.getByRole('group', { name: mobile ? 'Effectif' : 'Effective', exact: true })
      const functionRows = page.locator(mobile ? '.authorization-mobile-card' : 'tbody tr')
      for (const [label, names] of [
        [mobile ? 'Actives' : 'Active', ['external_read', 'external_list']],
        [mobile ? 'Inactives' : 'Inactive', ['external_blocked']],
        [labels.ask, ['external_approve']],
      ]) {
        await stateFilter.getByRole('button', { name: label, exact: true }).click()
        await expect(functionRows).toHaveCount(names.length)
        for (const name of names) await expect(functionRows.filter({ hasText: name })).toBeVisible()
      }
      // Reopening keeps the request-authorization filter and its effective inherited policy.
      await mount(page, 'app/connection/components/AuthorizationManager.vue', { locale, privileges })
      await expect(functionRows).toHaveCount(1)
      await expect(functionRows).toContainText('external_approve')
      await stateFilter.getByRole('button', { name: mobile ? 'Toutes' : 'All', exact: true }).click()
      await expect(functionRows).toHaveCount(4)
      const global = page.getByRole('group', { name: `${labels.global}: external_read`, exact: true })
      const local = page.getByRole('group', { name: `${labels.connection}: external_read`, exact: true })
      const otherGlobal = page.getByRole('group', { name: `${labels.global}: external_list`, exact: true })
      // A local override leaves no global button selected, while both groups stay usable.
      for (const button of await global.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      await expect(local.getByRole('button', { name: labels.enabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await global.getByRole('button').all()) await expect(button).toBeEnabled()
      for (const button of await otherGlobal.getByRole('button').all()) await expect(button).toBeEnabled()
      expect(writes).toEqual([])
      const row = page.locator(mobile ? '.authorization-mobile-card' : 'tbody tr').filter({ hasText: 'external_read' })
      await setPrivileges(page, ['CONNECTION_ACCESS'])
      await expect(row.getByRole('group')).toHaveCount(0)
      await expect(row.getByText(labels.inherit, { exact: true })).toHaveCount(0)
      await expect(row.getByText(labels[defaultState], { exact: true }).first()).toBeVisible()
      await setPrivileges(page, privileges)
      await expect(global.getByRole('button')).toHaveCount(3)
      await expect(global.getByRole('button', { name: labels.inherit, exact: true })).toHaveCount(0)
      for (const state of ['enabled', 'disabled', 'ask']) {
        await expect(global.getByRole('button', { name: labels[state], exact: true })).toBeVisible()
        await expect(global.getByRole('button', { name: labels[state], exact: true })).toBeEnabled()
      }
      await expect(local.getByRole('button')).toHaveCount(3)
      await expect(local.getByRole('button', { name: labels.inherit, exact: true })).toHaveCount(0)
      // Clicking a global choice saves it and clears this connection's override together.
      await global.getByRole('button', { name: labels[defaultState], exact: true }).click()
      await expect.poll(() => writes).toEqual([
        { function_name: 'external_read', state: defaultState, capability_kind: 'tool', global_policy: true, inherit_connection: true },
      ])
      for (const group of [global, local]) {
        for (const button of await group.getByRole('button').all()) await expect(button).toBeEnabled()
      }
      await expect(global.getByRole('button', { name: labels[defaultState], exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      for (const button of await otherGlobal.getByRole('button').all()) await expect(button).toBeEnabled()
      // More choices remain usable before the first response. Global writes must
      // still take effect even if the user's final choice is a local override.
      await local.getByRole('button', { name: labels.ask, exact: true }).click()
      await expect(local.getByRole('button', { name: labels.ask, exact: true })).toHaveAttribute('aria-pressed', 'true')
      await global.getByRole('button', { name: labels.disabled, exact: true }).click()
      await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      await local.getByRole('button', { name: labels.enabled, exact: true }).click()
      await expect(local.getByRole('button', { name: labels.enabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await global.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      expect(writes).toHaveLength(1)
      finishFirstWrite()
      await expect(local).toHaveAttribute('aria-busy', 'false')
      expect(writes).toEqual([
        { function_name: 'external_read', state: defaultState, capability_kind: 'tool', global_policy: true, inherit_connection: true },
        { function_name: 'external_read', state: 'ask', capability_kind: 'tool' },
        { function_name: 'external_read', state: 'disabled', capability_kind: 'tool', global_policy: true, inherit_connection: true },
        { function_name: 'external_read', state: 'enabled', capability_kind: 'tool' },
      ])
      expect(policy.global_state).toBe('disabled')
      expect(policy.connection_state).toBe('enabled')
      await expect(local.getByRole('button', { name: labels.enabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      await global.getByRole('button', { name: labels.disabled, exact: true }).focus()
      await page.keyboard.press('Enter')
      await expect(global).toHaveAttribute('aria-busy', 'false')
      expect(writes).toHaveLength(5)
      await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const state of ['enabled', 'ask', 'disabled']) {
        await local.getByRole('button', { name: labels[state], exact: true }).click()
        await expect.poll(() => writes.at(-1)).toEqual({ function_name: 'external_read', state, capability_kind: 'tool' })
        for (const button of await global.getByRole('button').all()) await expect(button).toBeEnabled()
        for (const button of await otherGlobal.getByRole('button').all()) await expect(button).toBeEnabled()
        for (const button of await global.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
        await expect(local.getByRole('button', { name: labels[state], exact: true })).toHaveAttribute('aria-pressed', 'true')
        if (mobile) await expect(row.getByText(labels[state], { exact: true })).toBeVisible()
        await global.getByRole('button', { name: labels.disabled, exact: true }).click()
        await expect.poll(() => writes.at(-1)).toEqual({ function_name: 'external_read', state: 'disabled', capability_kind: 'tool', global_policy: true, inherit_connection: true })
        for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
        for (const button of await global.getByRole('button').all()) await expect(button).toBeEnabled()
        await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      }
      for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      if (mobile) await expect(row.getByText(labels.disabled, { exact: true })).toBeVisible()
      await expect(global).toHaveAttribute('aria-busy', 'false')
      await mount(page, 'app/connection/components/AuthorizationManager.vue', { locale, privileges })
      await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      await setPrivileges(page, ['CONNECTION_ACCESS'])
      await expect(row.getByRole('group')).toHaveCount(0)
      await expect(row.getByText(labels.inherit, { exact: true })).toHaveCount(1)
      await expect(row.getByText(labels.disabled, { exact: true }).first()).toBeVisible()
    })
  }
}

for (const mobile of [false, true]) {
  test(`Policy saves survive failures, connection changes and reopening (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await routes(page)
    const second = { id: 12, service_id: 5, agent_id: 7, active: true }
    await connectionRoutes(page, [connections[4], second])
    const names = ['external_read', 'external_list']
    const globals = Object.fromEntries(names.map(name => [name, 'enabled']))
    const locals = { 5: { external_read: 'default', external_list: 'default' }, 12: { external_read: 'ask', external_list: 'default' } }
    const resolve = (id, name) => ({
      key: `tool:${name}`, name, description: 'Synthetic capability.', capability_kind: 'tool',
      connection_state: locals[id][name], global_state: globals[name], default_state: 'enabled',
      effective_state: locals[id][name] === 'default' ? globals[name] : locals[id][name],
      effective: (locals[id][name] === 'default' ? globals[name] : locals[id][name]) !== 'disabled',
      state_source: locals[id][name] === 'default' ? 'tool' : 'connection',
    })
    const reads = [], writes = []
    let gate = null, outcome = 'success'
    function holdNextWrite(result = 'success') {
      outcome = result
      let release
      gate = new Promise(resolve => { release = resolve })
      return () => release()
    }
    for (const id of [5, 12]) {
      await page.route(`**/api/connections/${id}/functions`, route => {
        reads.push(id)
        return route.fulfill({ json: { success: true, message: '', functions: names.map(name => resolve(id, name)) } })
      })
      await page.route(`**/api/connections/${id}/capabilities`, async route => {
        const request = route.request().postDataJSON()
        const waiting = gate, result = outcome
        gate = null; outcome = 'success'
        writes.push({ id, ...request })
        if (waiting) await waiting
        if (result !== 'reject') {
          if (request.global_policy) globals[request.function_name] = request.state
          if (!request.global_policy || request.inherit_connection) locals[id][request.function_name] = request.global_policy ? 'default' : request.state
        }
        return route.fulfill(result === 'success'
          ? { json: resolve(id, request.function_name) }
          : { status: 500, json: { detail: 'Synthetic save failure' } })
      })
    }
    await mount(page, 'app/connection/components/AuthorizationManager.vue', { privileges })
    const selector = page.getByRole('combobox').nth(2)
    // Equal labels are intentional: choose by option position to select each connection.
    async function selectConnection(index) {
      await selector.click()
      await page.getByRole('option', { name: 'Alice Example — Optional Service', exact: true }).nth(index).click()
    }
    await selectConnection(0)
    const global = page.getByRole('group', { name: 'Global (all): external_read', exact: true })
    const local = page.getByRole('group', { name: 'This connection: external_read', exact: true })
    const otherLocal = page.getByRole('group', { name: 'This connection: external_list', exact: true })
    const releaseGlobal = holdNextWrite()
    await global.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    await local.getByRole('button', { name: 'Ask', exact: true }).click()
    await otherLocal.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect(otherLocal).toHaveAttribute('aria-busy', 'false')
    expect(writes.map(write => write.function_name)).toEqual(['external_read', 'external_list'])
    await selectConnection(1)
    await expect(local).toHaveCount(0)
    expect(reads).toEqual([5])
    releaseGlobal()
    await expect(local.getByRole('button', { name: 'Ask', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(reads).toEqual([5, 12])
    expect(locals[5].external_read).toBe('ask')
    expect(globals.external_read).toBe('disabled')
    expect(writes.map(write => write.id)).toEqual([5, 5, 5])
    // A rejected older choice must not discard the newer queued choice.
    const releaseRejected = holdNextWrite('reject')
    await local.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(4)
    await local.getByRole('button', { name: 'Enabled', exact: true }).click()
    await expect(local.getByRole('button', { name: 'Enabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    releaseRejected()
    await expect(local).toHaveAttribute('aria-busy', 'false')
    expect(locals[12].external_read).toBe('enabled')
    await expect(local.getByRole('button', { name: 'Enabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    // An error can occur after persistence. Read back the actual saved rule.
    const releaseLost = holdNextWrite('committed_error')
    await local.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(6)
    releaseLost()
    await expect.poll(() => reads).toEqual([5, 12, 12])
    await expect(local.getByRole('button', { name: 'Disabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await local.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(local).toHaveAttribute('aria-busy', 'false')
    expect(locals[12].external_read).toBe('ask')
    // Reopening the component retains the ordered writes and waits before reading.
    const releaseReopened = holdNextWrite()
    await local.getByRole('button', { name: 'Enabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(8)
    await local.getByRole('button', { name: 'Disabled', exact: true }).click()
    await connectionRoutes(page, [second])
    await page.evaluate(async privileges => {
      await window.testApp.mount({ component: 'app/connection/components/AuthorizationManager.vue', privileges })
    }, privileges)
    await expect(local).toHaveCount(0)
    expect(reads).toEqual([5, 12, 12])
    releaseReopened()
    await expect(local.getByRole('button', { name: 'Disabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(locals[12].external_read).toBe('disabled')
    expect(writes.at(-1)).toMatchObject({ id: 12, state: 'disabled' })
    expect(locals[5].external_list).toBe('disabled')
  })
}

for (const [locale, description, publicLabel, askChoice, allowChoice, saveLabel] of [
  ['fr', 'Permettre les demandes d’accès au réseau local (bloqué par défaut)', 'Accès aux sites publics', 'Autorisation par site', 'Sites publics autorisés', 'Modifier'],
  ['en', 'Allow local network permission requests (blocked by default)', 'Public site access', 'Per-site approval', 'Public sites allowed', 'Edit'],
  ['zh', '允许请求本地网络访问权限（默认阻止）', '公共网站访问', '按网站审批', '允许公共网站', '编辑'],
]) {
  test(`Browser connection descriptions are translated (${locale})`, async ({ page }) => {
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
    const params = Object.fromEntries(['allow_local_network', 'network_filter_mode', 'network_filter', 'permission_methods'].map(name => [name, {
      type: name === 'allow_local_network' ? 'boolean' : 'string', required: false, description: 'Server description',
    }]))
    params.allow_local_network.default = 'false'
    params.public_access_mode = { type: 'string', required: false, default: 'ask', description: 'Server description',
      label: 'services.connectionParamLabels.public_access_mode',
      options: ['allow', 'ask'].map(value => ({ value, label: `services.connectionParamOptions.browser.public_access_mode.${value}` })) }
    await mount(page, 'app/connection/components/ConnectionForm.vue', {
      locale, privileges,
      props: {
        connection: { id: 42, agent_id: 7, service_id: 8, active: true }, connectionParams: {},
        agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }],
        serviceOptions: [{ id: 8, label: 'Browser' }],
        tools: [{ id: 8, label: 'Browser', code: 'browser', connection_schema: { params } }],
      },
    })
    await expect(page.getByText(description, { exact: true })).toBeVisible()
    await expect(page.locator('.param-desc').filter({ hasText: 'services.connectionParamDescriptions' })).toHaveCount(0)
    await expect(page.getByText('Server description', { exact: true })).toHaveCount(0)
    const access = page.getByRole('combobox', { name: publicLabel, exact: true })
    await expect(access).toHaveValue(askChoice)
    await access.press('ArrowDown')
    await page.getByRole('option', { name: allowChoice, exact: true }).click()
    await page.getByRole('button', { name: saveLabel, exact: true }).click()
    await expect.poll(() => page.evaluate(() => {
      const params = window.testApp.events.filter(event => event.name === 'submit').at(-1)?.value.params
      return params && { public_access_mode: params.public_access_mode, allow_local_network: params.allow_local_network }
    })).toEqual({ public_access_mode: 'allow', allow_local_network: 'false' })
  })
}

test('Protocol catalogue retries and plugin entries survive saving and reopening', async ({ page }) => {
  await routes(page)
  const plugin = { code: 'sensors', label: 'Vendor sensors', builtin: false,
    protocols: [{ value: 'vendor.sensors', capability: 'sensors', label: 'VendorLink', builtin: false }] }
  let attempts = 0
  await page.route('**/api/services/capabilities', route => {
    attempts++
    return route.fulfill(attempts === 1 ? { status: 503, json: { detail: 'Temporary catalogue outage' } } : { json: [...capabilityCatalogue, plugin] })
  })
  let saved
  const writes = []
  await page.route('**/api/services', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: saved ? [saved] : [] })
    const body = route.request().postDataJSON()
    writes.push(body)
    saved = { ...body, id: 94, can_edit: true, can_disable: true, global_params: {} }
    return route.fulfill({ status: 201, json: saved })
  })
  await page.route('**/api/services/94', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    saved = { ...saved, ...body }
    return route.fulfill({ json: saved })
  })
  await mount(page, 'app/services/components/ServicesList.vue', { privileges })
  await page.getByRole('button', { name: 'New service', exact: true }).click()
    await page.getByRole('button', { name: 'Create a custom service', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('tab')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Add protocol', exact: true }).click()
  const picker = page.getByRole('menu', { name: 'Add protocol', exact: true })
  await expect(picker.getByRole('alert')).toContainText('Unable to load the available protocols.')
  await expect(picker.getByRole('menuitem')).toHaveCount(0)
  await picker.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(picker.getByRole('alert')).toHaveCount(0)
  // Escape closes the menu and preserves the empty editor.
  await page.keyboard.press('Escape')
  await expect(picker).toHaveCount(0)
  await expect(dialog.getByRole('tab')).toHaveCount(0)
  await dialog.getByLabel('Technical name', { exact: false }).fill('synthetic_sensors')
  await dialog.getByLabel('Label *', { exact: true }).fill('Synthetic sensors')
  await dialog.getByRole('button', { name: 'Add protocol', exact: true }).click()
  const custom = 'vendor.sensors'
  await picker.getByRole('menuitem', { name: 'VendorLink', exact: true }).click()
  await expect(picker).toHaveCount(0)
  await expect(dialog.getByRole('tab', { name: 'VendorLink', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes[0].capabilities).toEqual([custom])
  await page.getByRole('button', { name: 'Edit service', exact: true }).click()
  await expect(dialog.getByRole('tab', { name: 'VendorLink', exact: true })).toBeVisible()
  await dialog.getByLabel('Label *', { exact: true }).fill('Renamed synthetic sensors')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes[1].capabilities).toEqual([custom])
})

async function routes(page) {
  await jsonRoute(page, '**/api/services/catalog', { source: 'bundled', revision: 'bundled', refresh_failed: false, entries: [] })
  await jsonRoute(page, '**/api/agents/selection?*', [{ id: 7, label: 'Alice Example', agent_driver: 'internal' }])
  await jsonRoute(page, '**/api/services/capabilities', capabilityCatalogue)
  await jsonRoute(page, '**/api/services', tools)
  await jsonRoute(page, '**/api/connections/service-options', tools)
  await jsonRoute(page, '**/api/file-share/bridges', [])
  await jsonRoute(page, '**/api/messenger/bridges', [])
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Alice', last_name: 'Example', agent_driver: 'internal' }])
  await jsonRoute(page, '**/api/mail/approvers', [])
  await connectionRoutes(page, connections)
  await jsonRoute(page, '**/api/connections/overview?*', connections.map(connection => ({ ...connection, params: {}, configured_params: [] })))
  for (const connection of connections) {
    await jsonRoute(page, `**/api/connections/${connection.id}/params?*`, { ...connection, connection_id: connection.id, params: {}, configured_params: [] })
    await jsonRoute(page, `**/api/connections/${connection.id}/functions`, {
      success: true, message: '', functions: [{
        name: connection.id === 5 ? 'external_read' : 'system_read', description: 'Read authorized content.',
        key: connection.id === 5 ? 'tool:external_read' : 'tool:system_read', capability_kind: 'tool',
        default_state: 'enabled', effective_state: 'enabled', state_source: 'connection',
        connection_state: connection.id === 5 ? 'default' : 'enabled',
        global_state: connection.id === 5 ? 'default' : 'enabled', effective: true,
      }],
    })
  }
}

for (const mobile of [false, true]) {
  for (const component of ['ConnectionList', 'AuthorizationManager']) {
    test(`Service origin filters retain selectable tools and their connections (${component}, ${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
      await routes(page)
      const customConnection = { id: 6, service_id: 6, agent_id: 7, active: true }
      await connectionRoutes(page, [...connections, customConnection])
      await jsonRoute(page, '**/api/connections/overview?*', [...connections, customConnection].map(connection => ({ ...connection, params: {}, configured_params: [] })))
      await jsonRoute(page, '**/api/connections/6/params?*', { connection_id: 6, params: {}, configured_params: [] })
      await jsonRoute(page, '**/api/connections/6/functions', { success: true, functions: [] })
      let releaseOptions = () => {}
      if (component === 'AuthorizationManager') {
        const ready = new Promise(resolve => { releaseOptions = resolve })
        await page.route('**/api/connections/permission-options?*', async route => {
          await ready
          await route.fulfill({ json: permissionOptions([...connections, customConnection]) })
        })
      }
      await mount(page, `app/connection/components/${component}.vue`, { privileges, dark: mobile })
      const filter = page.getByRole('combobox', { name: 'Filter by service', exact: true })
      if (component === 'AuthorizationManager') {
        try {
          await expect(filter).toBeDisabled()
          await page.screenshot({ path: testInfo.outputPath('tool-filter-loading.png'), animations: 'disabled' })
        } finally { releaseOptions() }
      }
      await expect(filter).toBeEnabled()
      await filter.press('ArrowDown')
      const popup = page.getByRole('listbox')
      await expect(popup.getByText('Galaris', { exact: true }).first()).toBeVisible()
      await expect(popup.getByText('Custom', { exact: true })).toBeVisible()
      await expect(popup.getByRole('option', { name: 'Custom', exact: true })).toHaveCount(0)
      await page.getByRole('option', { name: 'No description', exact: true }).click()
      if (component === 'ConnectionList') {
        const rows = page.locator(mobile ? '.connection-mobile-card' : 'tbody tr')
        await expect(rows).toHaveCount(1)
        await expect(rows).toContainText('No description')
        await expect(rows).toContainText('Custom')
      } else {
        const selection = page.getByRole('combobox', { name: 'Select a connection (agent + connector)', exact: true })
        await expect(selection).toHaveValue('Alice Example — No description')
        await expect(page.getByRole('status').filter({ hasText: 'Custom' })).toBeVisible()
      }
      await filter.click()
      await page.getByRole('option', { name: 'Optional Service', exact: true }).click()
      await expect(page.getByRole('option', { name: 'Optional Service', exact: true })).toHaveCount(0)
      await page.screenshot({ path: testInfo.outputPath('tool-origin-filter.png'), animations: 'disabled' })
      if (component === 'ConnectionList') {
        const rows = page.locator(mobile ? '.connection-mobile-card' : 'tbody tr')
        await expect(rows).toHaveCount(1)
        await expect(rows).toContainText('Optional Service')
        await expect(rows).toContainText('Custom')
      } else {
        await expect(page.getByRole('combobox', { name: 'Select a connection (agent + connector)', exact: true })).toHaveValue('Alice Example — Optional Service')
        await expect(page.getByText('external_read', { exact: true })).toBeVisible()
      }
      await page.locator('.q-field').filter({ has: filter }).locator('.q-field__focusable-action').click()
      await expect(filter).toHaveValue('')
      if (component === 'ConnectionList') {
        await expect(page.locator(mobile ? '.connection-mobile-card' : 'tbody tr')).toHaveCount(6)
      }
    })
  }

  test(`Service search filters localized content across pages and can be cleared (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await routes(page)
    const catalogue = [
      ...tools,
      ...Array.from({ length: 50 }, (_, index) => ({
        ...tools[5], id: 100 + index, code: `synthetic_${index}`, label: `Synthetic tool ${index}`,
      })),
      { ...tools[5], id: 200, code: 'remote_archive', label: 'Équipe distante', description: 'Synthetic archive connector.' },
    ]
    await jsonRoute(page, '**/api/services', catalogue)
    const locale = mobile ? 'fr' : 'en'
    await mount(page, 'app/services/components/ServicesList.vue', { locale, privileges: ['SERVICE_ACCESS'] })
    await page.getByRole('tab', { name: mobile ? 'Services internes à Galaris' : 'Galaris built-in services', exact: true }).click()
    const rows = page.getByRole('article')
    const search = page.getByRole('textbox', { name: mobile ? 'Rechercher un service' : 'Search services', exact: true })
    await expect(rows).toHaveCount(4)
    await expect(rows.filter({ hasText: 'Optional Service' })).toHaveCount(0)
    const customTab = page.getByRole('tab', { name: mobile ? 'Services personnalisés' : 'Custom services', exact: true })
    const galarisTab = page.getByRole('tab', { name: mobile ? 'Services internes à Galaris' : 'Galaris built-in services', exact: true })
    await customTab.click()
    await expect(rows).toHaveCount(50)
    await expect(rows.filter({ hasText: 'Optional Service' })).toBeVisible()
    await expect(rows.filter({ hasText: 'Équipe distante' })).toHaveCount(0)
    for (const query of [' REMOTE_ARCHIVE ', 'EQUIPE DISTANTE', 'archive connector']) {
      await search.fill(query)
      await expect(rows).toHaveCount(1)
      await expect(rows).toContainText('Équipe distante')
    }
    await page.screenshot({ path: testInfo.outputPath('tool-search.png'), animations: 'disabled' })
    await galarisTab.click()
    await search.fill(mobile ? 'mémoire' : 'memory')
    await expect(page.getByRole('article', { name: mobile ? 'Mémoire' : 'Memory', exact: true })).toBeVisible()
    await expect(rows.filter({ hasText: 'Équipe distante' })).toHaveCount(0)
    await search.fill('TEAM HANDBOOK')
    await expect(rows).toHaveCount(0)
    await customTab.click()
    await expect(rows).toHaveCount(1)
    await expect(rows).toContainText('Optional Service')
    await search.fill('no-such-synthetic-tool')
    await expect(rows).toHaveCount(0)
    await expect(page.locator('.q-table__bottom--nodata')).toBeVisible()
    await customTab.click()
    await search.fill('   ')
    await expect(rows).toHaveCount(50)
    await search.fill('remote_archive')
    await expect(rows).toHaveCount(1)
    await page.locator('.tools-search').getByRole('button').press('Enter')
    await expect(search).toHaveValue('')
    await expect(rows).toHaveCount(50)
  })

  test(`Service descriptions reopen without service-wide conversation switches (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await routes(page)
    await mount(page, 'app/services/components/ServicesList.vue', { privileges })
    await page.getByRole('tab', { name: 'Galaris built-in services', exact: true }).click()
    const rows = page.getByRole('article')
    for (const name of ['Galaris', 'Chat', 'Memory', 'File sharing']) {
      const row = rows.filter({ has: page.getByRole('button', { name, exact: true }) })
      await expect(row.getByRole('switch')).toHaveCount(0)
      await expect(row.getByRole('img', { name: 'Mandatory system service' })).toBeVisible()
      await expect(row.getByRole('button', { name: 'Export', exact: true })).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath('internal-service-cards.png'), animations: 'disabled' })
    await rows.filter({ has: page.getByRole('button', { name: 'Galaris', exact: true }) }).getByText('galaris', { exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Coordinate agents')
    const headings = page.getByRole('dialog').getByRole('heading', { level: 2 })
    await expect(headings.first()).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('tool-description.png'), animations: 'disabled' })
    await headings.last().scrollIntoViewIfNeeded()
    await expect(headings.last()).toBeVisible()
    await page.getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByRole('tab', { name: 'Custom services', exact: true }).click()
    await page.getByRole('button', { name: 'Optional Service', exact: true }).click()
    await expect(page.getByRole('dialog').locator('strong')).toHaveText('Team handbook')
    // The backdrop closes the description, and reopening retains its content.
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: 'Optional Service', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Team handbook')
    await page.keyboard.press('Escape')
    await expect(rows.filter({ hasText: 'Optional Service' }).getByRole('switch')).toHaveCount(0)
    await page.getByRole('tab', { name: 'Custom services', exact: true }).click()
    await expect(page.getByRole('button', { name: 'No description', exact: true })).toHaveCount(0)
    await page.getByText('No description', { exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test(`Chat channel settings preserve the mandatory connection (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await routes(page)
    await jsonRoute(page, '**/api/connections/service-options', tools.map(tool => tool.code === 'chat' ? {
      ...tool, global_params: { 'chat.channel_enabled': { value: 'true', configured: true } },
    } : tool))
    let channel
    await page.route('**/api/connections/2/params?*', route => route.fulfill({ json: {
      ...connections[1], connection_id: 2,
      params: channel === undefined ? {} : { 'chat.channel_enabled': channel }, configured_params: [],
    } }))
    await page.route('**/api/connections/2', route => {
      expect(route.request().method()).toBe('PATCH')
      const update = route.request().postDataJSON()
      expect(update).toMatchObject({ agent_id: 7, service_id: 2, active: true })
      channel = update.params['chat.channel_enabled']
      return route.fulfill({ json: connections[1] })
    })
    await mount(page, 'app/connection/components/ConnectionList.vue', { privileges, dark: mobile })
    const rows = page.locator(mobile ? '.connection-mobile-card' : 'tbody tr')
    await expect(rows).toHaveCount(5)
    for (let i = 0; i < 4; i++) {
      const row = rows.nth(i)
      await expect(row.getByRole('switch')).toBeDisabled()
      await expect(row.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
      // Diagnostics and permission inspection remain usable on mandatory services.
      await expect(row.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(i === 1 ? 1 : 0)
      await expect(row.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0)
    }
    await expect(rows.nth(4).getByRole('switch')).toBeEnabled()
    const chat = rows.filter({ hasText: 'Chat' })
    const open = chat.getByRole('button', { name: 'Edit', exact: true })
    await open.click()
    const dialog = page.getByRole('dialog')
    await dialog.getByText('Inherited global parameters (1)', { exact: true }).click()
    await dialog.getByRole('button', { name: 'Customize', exact: true }).click()
    const internalChannel = dialog.getByRole('switch', { name: 'Internal channel' })
    await expect(internalChannel).toHaveAttribute('aria-checked', 'true')
    await internalChannel.press('Space')
    await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(channel).toBe('false')
    await open.click()
    await expect(internalChannel).toHaveAttribute('aria-checked', 'false')
    await expect(chat.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
    await dialog.screenshot({ path: testInfo.outputPath('chat-channel-settings.png'), animations: 'disabled' })
  })
}

for (const mobile of [false, true]) {
test(`Conversation access is edited on the Service and fixed for built-ins (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
  await routes(page)
  const writes = []
  const allowed = new Set()
  let fail = true
  await jsonRoute(page, '**/api/services', tools.map(tool => ({
    ...tool, has_function_permissions: tool.id === 1 || tool.id === 5, has_mcp: tool.id === 5,
  })))
  await jsonRoute(page, '**/api/services/1/conversation-tools', {
    tools: [
      { name: 'agent_get', source: 'native', enabled: true },
      { name: 'task_get', source: 'native', enabled: false },
    ],
    discovery_incomplete: false,
    next_connection_id: null,
  })
  await page.route(url => url.pathname.endsWith('/api/services/5/conversation-tools/discover'), route => {
    const following = new URL(route.request().url()).searchParams.get('after_connection_id') === '15'
    return route.fulfill({ json: {
      tools: [...new Set(['external_read', following ? 'external_list' : 'external_search', ...allowed])]
        .map(name => ({ name, source: 'external', enabled: allowed.has(name) })),
      discovery_incomplete: true,
      next_connection_id: following ? null : 15,
    } })
  })
  await page.route('**/api/services/5/conversation-tools', route => {
    const data = route.request().postDataJSON()
    expect(data.source).toBe('external')
    if (fail) { fail = false; return route.fulfill({ status: 503, json: {} }) }
    if (data.enabled) allowed.add(data.name)
    else allowed.delete(data.name)
    return route.fulfill({ json: { enabled: data.enabled } })
  })
  await page.route('**/api/connections/1/capabilities', route => {
    writes.push(route.request().postDataJSON())
    return route.fulfill({ json: { name: 'system_read', connection_state: 'ask', global_state: 'enabled',
      effective: true, effective_state: 'ask', default_state: 'enabled', state_source: 'connection' } })
  })
  await mount(page, 'app/index/pages/services.vue', { route: '/services?tab=authorizations', privileges, dark: mobile })
  const selector = page.getByRole('combobox').nth(2)
  await selector.click()
  await page.getByRole('option', { name: 'Alice Example — Galaris', exact: true }).click()
  await expect(page.getByText('system_read', { exact: true })).toBeVisible()
  const row = page.locator(mobile ? '.authorization-mobile-card' : 'tbody tr')
  await expect(page.getByRole('switch', { name: 'Allow system_read in conversation' })).toHaveCount(0)
  await expect(page.getByText('This system service and its connection are mandatory.', { exact: false })).toBeVisible()
  await row.getByRole('group', { name: 'This connection: system_read' }).getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(() => writes).toEqual([{ function_name: 'system_read', state: 'ask', capability_kind: 'tool' }])
  await expect(row.getByRole('group', { name: 'This connection: system_read' }).getByRole('button', { name: 'Ask', exact: true })).toHaveAttribute('aria-pressed', 'true')
  if (mobile) await expect(row).toContainText('Ask')
  await page.getByRole('tab', { name: 'Services', exact: true }).click()
  const card = page.getByRole('article', { name: 'Optional Service', exact: true })
  const open = card.getByRole('button', { name: 'Conversation tools', exact: true })
  await open.click()
  const dialog = page.getByRole('dialog')
  const read = dialog.getByRole('switch', { name: 'Allow external_read in conversation (MCP server)' })
  const list = dialog.getByRole('switch', { name: 'Allow external_list in conversation (MCP server)' })
  await expect(dialog).toContainText('This setting applies to all agents.')
  await expect(read).toHaveAttribute('aria-checked', 'false')
  await read.press('Enter')
  await expect(dialog.getByRole('alert')).toContainText('Unable to save conversation access.')
  await expect(read).toHaveAttribute('aria-checked', 'false')
  await read.click()
  await expect(read).toHaveAttribute('aria-checked', 'true')
  await dialog.getByRole('button', { name: 'Check more connections' }).click()
  await expect(list).toHaveAttribute('aria-checked', 'false')
  await expect(read).toHaveCount(1)
  await expect(read).toHaveAttribute('aria-checked', 'true')
  await expect(dialog.getByRole('switch', { name: 'Allow external_search in conversation (MCP server)' })).toBeVisible()
  await dialog.getByRole('textbox', { name: 'Exact MCP tool name' }).fill('account_only_tool')
  await dialog.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect(dialog.getByRole('switch', { name: 'Allow account_only_tool in conversation (MCP server)' }))
    .toHaveAttribute('aria-checked', 'true')
  await expect(dialog.getByRole('textbox', { name: 'Exact MCP tool name' })).toHaveValue('')
  await expect(dialog.getByText('Enter a valid MCP tool name.')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('service-conversation-tools.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await open.click()
  await expect(read).toHaveAttribute('aria-checked', 'true')
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'Galaris built-in services', exact: true }).click()
  await page.getByRole('article', { name: 'Galaris', exact: true })
    .getByRole('button', { name: 'Conversation tools', exact: true }).click()
  await expect(dialog.getByRole('row').filter({ hasText: 'agent_get' }).getByText('Allowed', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('row').filter({ hasText: 'task_get' }).getByText('Disabled', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('switch')).toHaveCount(0)
})
}
