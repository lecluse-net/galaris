import { test, expect, mount } from './fixtures.mjs'

test('Saved connection tests recover after failure and discard another account’s late result', async ({ page }) => {
  let release, started = false, attempts = 0
  await page.route('**/api/connections/42/test', async route => {
    started = true
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { status: 'success', checks: [{ protocol: 'mcp', status: 'success', message: 'Previous account' }] } }).catch(() => {})
  })
  await page.route('**/api/connections/43/test', route => {
    attempts++
    return attempts === 1 ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({ json: { status: 'unsupported', checks: [{ protocol: 'rest', status: 'unsupported', message: 'No automatic REST check' }] } })
  })
  await mount(page, 'app/connection/components/ConnectionTestButton.vue', { props: { connectionId: 42 } })
  await page.getByRole('button', { name: 'Test', exact: true }).click()
  await expect.poll(() => started).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ connectionId: 43 }))
  await page.getByRole('button', { name: 'Test', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Unable to run the test')
  release()
  await expect(page.getByRole('dialog')).not.toContainText('Previous account')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Test', exact: true }).press('Enter')
  await expect(page.getByRole('dialog')).toContainText('Verification incomplete')
  await expect(page.getByRole('dialog')).toContainText('No automatic REST check')
})

test('Connection permissions preserve saved decisions, reconcile failures and isolate accounts', async ({ page }) => {
  let state = 'default', globalState = 'default', fail = false
  const writes = []
  await page.route('**/api/tools/agents/7/permissions?connection_id=*', route => {
    const other = new URL(route.request().url()).searchParams.get('connection_id') === '43'
    return route.fulfill({ json: { connections: [{ tool_id: 8, tool_code: 'synthetic', tool_label: 'Synthetic',
      connection_id: other ? 43 : 42, active: true, can_disable: true, parameters: {} }], capabilities: [{
      id: '8:tool:lookup', tool_id: 8, tool_label: 'Synthetic', connection_id: other ? 43 : 42,
      name: other ? 'other_lookup' : 'lookup', description: 'Synthetic function', capability_kind: 'tool',
      connection_state: other ? 'default' : state, global_state: globalState, default_state: 'ask',
      effective_state: state === 'default' || other ? (globalState === 'default' ? 'ask' : globalState) : state,
      policy_state: state === 'default' || other ? (globalState === 'default' ? 'ask' : globalState) : state,
      policy_source: state === 'default' || other ? 'software' : 'connection', available: true, runtime_supported: true,
    }], unavailable_catalogs: [] } })
  })
  await page.route('**/api/connections/42/capabilities', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    if (fail) return route.fulfill({ status: 503, json: {} })
    if (body.global_policy) { globalState = body.state; state = 'default' } else state = body.state
    return route.fulfill({ json: { name: 'lookup', connection_state: state, global_state: globalState,
      effective: state !== 'disabled', effective_state: state === 'default' ? 'ask' : state,
      default_state: 'ask', state_source: 'connection' } })
  })
  const props = { connection: { id: 42, tool_id: 8, agent_id: 7, active: true } }
  const privileges = ['PERMISSION_ACCESS', 'PERMISSION_DECIDE', 'PERMISSION_REVOKE']
  const local = page.getByRole('group', { name: 'Local (this connection)', exact: true })
  const global = page.getByRole('group', { name: 'Global (all)', exact: true })
  await mount(page, 'app/connection/components/ConnectionPermissions.vue', { props, privileges })
  await expect(global.getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
  await local.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect(local.getByRole('button', { name: 'Allow', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(writes).toEqual([{ function_name: 'lookup', capability_kind: 'tool', state: 'enabled' }])
  await mount(page, 'app/connection/components/ConnectionPermissions.vue', { props, privileges })
  await expect(local.getByRole('button', { name: 'Allow', exact: true })).toHaveAttribute('aria-pressed', 'true')
  fail = true
  await local.getByRole('button', { name: 'Deny', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(local.getByRole('button', { name: 'Allow', exact: true })).toHaveAttribute('aria-pressed', 'true')
  fail = false
  await mount(page, 'app/connection/components/ConnectionPermissions.vue', { props, privileges: [...privileges, 'AGENT_MANAGE_ALL'] })
  await global.getByRole('button', { name: 'Deny', exact: true }).click()
  await expect(global.getByRole('button', { name: 'Deny', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(local.getByRole('button', { name: 'Inherit', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(writes.at(-1)).toEqual({ function_name: 'lookup', capability_kind: 'tool', state: 'disabled', global_policy: true, inherit_connection: true })
  await page.evaluate(() => window.testApp.setProps({ connection: { id: 43, tool_id: 8, agent_id: 7, active: true } }))
  await expect(page.getByText('other_lookup', { exact: true })).toBeVisible()
  await expect(page.getByText('lookup', { exact: true })).toHaveCount(0)
})
