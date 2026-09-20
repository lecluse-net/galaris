import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

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
      connection: { id: 42, agent_id: 7, tool_id: 8, active: true },
      connectionParams: { host: 'console.example.test' },
      agentOptions: [{ value: 7, label: 'Alice', agentDriver: 'internal' }],
      toolOptions: [{ id: 8, label: 'Console' }],
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
