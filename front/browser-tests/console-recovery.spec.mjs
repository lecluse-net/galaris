import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

for (const active of [true, false]) {
  test(`generating a key, testing and deploying preserve the Console configuration across reopening (${active})`, async ({ page }) => {
    if (!active) await page.setViewportSize({ width: 390, height: 844 })
    const connection = { id: 42, agent_id: 7, service_id: 8, active }
    const params = { host: 'console.example.test', known_host_key: 'synthetic-pinned-host-key' }
    const writes = []
    let failSave = true
    let generated = false
    let tests = 0
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Alice', last_name: 'Example', agent_driver: 'internal' }])
    const tools = [{ id: 8, code: 'console', label: 'Console', can_disable: true, can_edit: false,
      connection_schema: { params: { host: { type: 'string' }, known_host_key: { type: 'password' },
        private_key: { type: 'password' } } }, global_params: {} }]
    await jsonRoute(page, '**/api/services', tools)
    await jsonRoute(page, '**/api/connections/service-options', tools)
    for (const endpoint of ['file-share/bridges', 'messenger/bridges', 'mail/approvers']) {
      await jsonRoute(page, `**/api/${endpoint}`, [])
    }
    await page.route('**/api/connections?*', route => route.fulfill({ json: [connection] }))
    await page.route('**/api/connections/overview?*', route => route.fulfill({ json: [{ ...connection, params, configured_params: [] }] }))
    await page.route('**/api/connections/42/params?*', route => route.fulfill({ json: {
      ...connection, connection_id: 42, params: { host: params.host },
      configured_params: ['known_host_key', ...(generated ? ['private_key'] : [])],
    } }))
    await page.route('**/api/connections/42', route => {
      if (failSave) {
        failSave = false
        return route.abort()
      }
      const { params: changes, ...metadata } = route.request().postDataJSON()
      writes.push(metadata)
      Object.assign(connection, metadata)
      Object.assign(params, changes)
      return route.fulfill({ json: connection })
    })
    await page.route('**/api/console/connections/42/generate-key', route => {
      generated = true
      params.private_key = 'synthetic-private-key'
      return route.fulfill({ json: { connection_id: 42, public_key: 'ssh-ed25519 AAAASyntheticPublicKey' } })
    })
    await page.route('**/api/console/connections/42/test', route => {
      tests++
      const authenticated = Boolean(params.private_key && params.known_host_key)
      return route.fulfill({ json: { connection_id: 42, status: {
        reachable: true, authenticated, host_key_verified: authenticated, home_writable: true, sftp_available: true, mode: 'standard',
      } } })
    })
    await jsonRoute(page, '**/api/console/connections/42/install-editor', {
      connection_id: 42, port: 32123, version: '4.141.0', ready: true, already_installed: false,
    })
    await mount(page, 'app/connection/components/ConnectionList.vue', {
      shell: true, dark: !active,
      privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL'],
    })
    if (!active) await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 200 } })
    await page.getByRole('button', { name: 'All', exact: true }).click()
    for (const action of ['Generate key', 'Test', 'Deploy code editor']) {
      await page.getByRole('button', { name: 'Edit', exact: true }).click()
      const form = page.getByRole('dialog').first()
      // Unsaved activation changes must not take effect during a technical action.
      await form.getByRole('switch', { name: 'Active connection', exact: true }).click()
      const tools = form.getByText('SSH configuration tools', { exact: true }).locator('..')
      const button = tools.getByRole('button', { name: action, exact: true })
      if (action === 'Generate key') {
        await tools.getByRole('button', { name: 'Test', exact: true }).click()
        await expect(page.getByRole('alert').filter({ hasText: 'Generate an SSH key' })).toBeVisible()
        expect(tests).toBe(0)
        await button.click()
        await expect(page.getByRole('alert').filter({ hasText: 'SSH action failed' })).toBeVisible()
        expect(generated).toBe(false)
        await button.click()
        await expect(form.getByText(/grep.*ssh-ed25519 AAAASyntheticPublicKey/)).toBeVisible()
      } else if (action === 'Test') {
        await button.click()
        await expect(page.getByRole('dialog').last()).toContainText('"authenticated": true')
        await page.getByRole('dialog').last().getByRole('button', { name: 'Close', exact: true }).last().click()
      } else {
        await button.click()
        await expect(form.getByRole('status')).toContainText('The editor is deployed and its access is configured')
      }
      expect(writes.at(-1).active).toBe(active)
      await form.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
    }
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(page.getByRole('switch', { name: 'Active connection', exact: true })).toHaveAttribute('aria-checked', String(active))
    expect(connection.active).toBe(active)
    expect(writes).toHaveLength(3)
    expect(tests).toBe(1)
  })
}

test('a legacy console helper can be upgraded, retried after failure and rechecked without edit rights', async ({ page }) => {
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Alice', last_name: 'Example', agent_driver: 'internal' }])
  const status = { reachable: true, authenticated: true, host_key_verified: true, home_writable: true, sftp_available: true, galaris_exec_available: true, operation_recovery_available: false, mode: 'enhanced' }
  await page.route('**/api/console/connections/42/test', route => route.fulfill({ json: { connection_id: 42, status } }))
  let installs = 0
  await page.route('**/api/console/connections/42/install-helper', route => {
    installs++
    if (installs === 1) return route.fulfill({ status: 502, json: { detail: 'Upload interrupted' } })
    status.operation_recovery_available = true
    return route.fulfill({ json: { connection_id: 42, version: '2', path: '/home/agent/.galaris/bin/galaris-exec', status } })
  })
  await mount(page, 'app/connection/components/ConnectionForm.vue', {
    privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'],
    props: {
      connection: { id: 42, agent_id: 7, service_id: 8, active: true },
      connectionParams: { host: 'console.example.test' },
      configuredParams: ['private_key', 'known_host_key'],
      agentOptions: [{ value: 7, label: 'Alice', agentDriver: 'internal' }],
      serviceOptions: [{ id: 8, label: 'Console' }],
      tools: [{ id: 8, label: 'Console', code: 'console', connection_schema: { params: { host: { type: 'string' } } } }],
    },
  })
  await page.evaluate(() => window.testApp.setProps({
    persistForAction: async payload => ({ id: 42, ...payload.data }),
  }))
  await page.getByRole('button', { name: 'Test', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const install = dialog.getByRole('button', { name: /galaris-exec/i })
  await expect(install).toBeVisible()
  await install.click()
  await expect(page.getByRole('alert').filter({ hasText: 'Upload interrupted' })).toBeVisible()
  await expect(install).toBeVisible()
  await install.click()
  await expect(install).toHaveCount(0)
  await expect(dialog).toContainText('"operation_recovery_available": true')
  await dialog.getByRole('button', { name: 'Close', exact: true }).last().click()
  await page.getByRole('button', { name: 'Test', exact: true }).click()
  await expect(install).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).last().click()
  status.operation_recovery_available = false
  await setPrivileges(page, ['CONNECTION_ACCESS'])
  await page.getByRole('button', { name: 'Test', exact: true }).click()
  await expect(dialog).toContainText('"operation_recovery_available": false')
  await expect(install).toHaveCount(0)
  expect(installs).toBe(2)
})

test('the code editor deploys directly without a prior SSH test, retries failures and preserves its secret on save', async ({ page }) => {
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Alice', last_name: 'Example', agent_driver: 'internal' }])
  const status = { reachable: true, authenticated: true, host_key_verified: true, home_writable: true, sftp_available: true, mode: 'standard' }
  await jsonRoute(page, '**/api/console/connections/42/test', { connection_id: 42, status })
  let installs = 0
  let release
  const waiting = new Promise(resolve => { release = resolve })
  let releaseLate
  const late = new Promise(resolve => { releaseLate = resolve })
  const upgradeRequests = []
  await page.route('**/api/console/connections/42/install-editor*', async route => {
    upgradeRequests.push(new URL(route.request().url()).searchParams.get('upgrade'))
    installs++
    if (installs === 1) return route.fulfill({ status: 502, json: { detail: 'Synthetic Docker access failure' } })
    await (installs === 3 ? late : waiting)
    return route.fulfill({ json: { connection_id: 42, port: 32123, version: '4.141.0', ready: true, already_installed: false } })
  })
  await mount(page, 'app/connection/components/ConnectionForm.vue', {
    privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'],
    props: {
      connection: { id: 42, agent_id: 7, service_id: 8, active: true },
      connectionParams: { host: 'console.example.test' },
      agentOptions: [{ value: 7, label: 'Alice', agentDriver: 'internal' }], serviceOptions: [{ id: 8, label: 'Console' }],
      tools: [{ id: 8, label: 'Console', code: 'console', connection_schema: { params: {
        host: { type: 'string' }, code_runtime_port: { type: 'integer' }, code_runtime_token: { type: 'password' },
      } } }],
    },
  })
  await page.evaluate(() => window.testApp.setProps({ persistForAction: async payload => ({ id: 42, ...payload.data }) }))
  const deploy = page.getByRole('button', { name: 'Deploy code editor', exact: true })
  await expect(deploy).toBeEnabled()
  await deploy.hover()
  await expect(page.getByRole('tooltip')).toBeVisible()
  await expect(page.getByRole('tooltip')).toHaveText(/\S/)
  await deploy.click()
  await expect(page.getByRole('alert').filter({ hasText: 'Synthetic Docker access failure' })).toBeVisible()
  const request = page.waitForRequest('**/api/console/connections/42/install-editor*')
  await deploy.click()
  await request
  await expect(deploy).toBeDisabled()
  release()
  await expect(page.getByRole('status')).toContainText('The editor is deployed and its access is configured')
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  const submitted = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'submit').at(-1))
  expect(submitted.args[0].params.code_runtime_port).toBe('32123')
  expect(submitted.args[0].params).not.toHaveProperty('code_runtime_token')
  await expect(deploy).toHaveCount(0)
  await expect(page.getByText('Editors on active SSH connections are checked on every Galaris update', { exact: false })).toBeVisible()
  // A configured editor is maintained by deployment; a new connection can still install it.
  await page.evaluate(() => window.testApp.setProps({
    connection: { id: 42, agent_id: 7, service_id: 8, active: true },
    connectionParams: { host: 'console.example.test' },
  }))
  const pending = page.waitForRequest('**/api/console/connections/42/install-editor*')
  await deploy.click()
  await pending
  await page.evaluate(() => window.testApp.setProps({
    connection: { id: 84, agent_id: 7, service_id: 8, active: true },
    connectionParams: { host: 'second-console.example.test' },
  }))
  await expect(page.getByRole('button', { name: 'Test', exact: true })).toBeEnabled()
  releaseLate()
  await expect(page.getByRole('status')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ tools: [{
    id: 8, label: 'Console', code: 'console', connection_schema: { params: { host: { type: 'string' } } },
    global_params: { code_runtime_token: { configured: true, forced: true, secret: true } },
  }] }))
  await expect(deploy).toBeEnabled()
  await deploy.click()
  await expect(page.getByRole('alert').filter({ hasText: 'Editor access is imposed by the global configuration' })).toBeVisible()
  await setPrivileges(page, ['CONNECTION_ACCESS'])
  await expect(deploy).toHaveCount(0)
  expect(installs).toBe(3)
  expect(upgradeRequests).toEqual([null, null, null])
})
