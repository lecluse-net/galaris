import { test, expect } from '@playwright/test'

for (const mobile of [false, true]) {
  test(`ToolAdmin prepares a secret candidate and administers a Tool (${mobile ? 'mobile' : 'desktop'})`, async ({ page, request }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    const fixture = await (await request.post('/api/__test/seed')).json()
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login')
    await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
    await page.locator('button[type=submit]').click()
    const session = await (await login).json()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    const headers = { Authorization: `Bearer ${session.access_token}` }
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (path.startsWith('/api/') && response.status() >= 400) errors.push(`${response.status()} ${path}`)
    })
    const tools = await (await request.get('/api/tools', { headers })).json()
    const admin = tools.find(tool => tool.code === 'tool_admin')
    expect(admin.conversation_enabled).toBe(false)
    const grants = await (await request.get(`/api/connections?tool_id=${admin.id}&agent_id=${fixture.agent_id}`, { headers })).json()
    const grant = grants.length ? grants[0] : await (await request.post('/api/connections', {
      headers, data: { tool_id: admin.id, agent_id: fixture.agent_id, active: false },
    })).json()
    expect(grant.active).toBe(false)
    expect((await request.patch(`/api/connections/${grant.id}`, { headers, data: { active: true } })).ok()).toBeTruthy()
    const invoke = async (name, data = {}) => {
      const response = await request.post(`/api/__test/tool-admin/${fixture.agent_id}/${name}`, { data })
      expect(response.ok(), await response.text()).toBeTruthy()
      return response.json()
    }
    const allowed = async (name, data) => {
      const response = await invoke(name, data)
      expect(response.success, JSON.stringify(response)).toBe(true)
      return response
    }
    const code = `candidate_${fixture.agent_id}`
    await page.goto('/tools')
    if (mobile) await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 150 } })
    await page.getByRole('button', { name: 'Nouvel outil', exact: true }).click()
    const editor = page.getByRole('dialog').first()
    await editor.getByLabel('Nom technique *', { exact: true }).fill(code)
    await editor.getByLabel('Libellé *', { exact: true }).fill('Synthetic ToolAdmin candidate')
    await editor.getByRole('button', { name: 'Ajouter un param', exact: true }).click()
    await editor.getByLabel('Nom *', { exact: true }).fill('token')
    await editor.getByRole('combobox', { name: 'Type', exact: true }).press('ArrowDown')
    await page.getByRole('option', { name: 'password', exact: true }).click()
    await editor.getByRole('switch', { name: 'Activer MCP', exact: true }).check()
    await editor.getByLabel('URL *', { exact: true }).fill('http://127.0.0.1:8000/api/__test/mcp/')
    await editor.getByRole('combobox', { name: "Type d'auth", exact: true }).press('ArrowDown')
    await page.getByRole('option', { name: 'bearer — Authorization: Bearer', exact: true }).click()
    await editor.getByRole('combobox', { name: 'Param contenant le token', exact: true }).press('ArrowDown')
    await page.getByRole('option', { name: 'token', exact: true }).click()
    await editor.getByRole('button', { name: 'Tester la connexion', exact: true }).click()
    const diagnostic = page.getByRole('dialog').last()
    const secret = `synthetic-browser-secret-${fixture.agent_id}`
    await diagnostic.getByLabel('token *', { exact: true }).fill(secret)
    await diagnostic.getByRole('combobox', { name: 'Agent destinataire du candidat MCP', exact: true }).press('ArrowDown')
    const agent = await (await request.get(`/api/agents/${fixture.agent_id}`, { headers })).json()
    await page.getByRole('option', { name: `${agent.first_name} ${agent.last_name}`, exact: true }).click()
    await diagnostic.getByRole('button', { name: 'Préparer le candidat pour cet agent', exact: true }).focus()
    await page.keyboard.press('Enter')
    const referenceInput = diagnostic.getByLabel('Référence à transmettre à l’agent', { exact: true })
    await expect(referenceInput).toBeVisible()
    const reference = await referenceInput.inputValue()
    expect(reference).not.toContain(secret)
    const before = await allowed('tool_admin_list', { search: code })
    expect(before.total).toBe(0)
    const tested = await allowed('tool_admin_mcp_test', { candidate_reference: reference })
    expect(tested.diagnostic.success, JSON.stringify(tested)).toBe(true)
    expect(tested.diagnostic.tools.map(tool => tool.name)).toContain('lookup')
    expect(JSON.stringify(tested)).not.toContain(secret)
    expect((await (await request.get('/api/__test/tool-admin/business-calls')).json()).calls).toEqual([])
    // Closing clears the temporary inputs; reopening cannot display the secret/reference.
    if (mobile) await page.keyboard.press('Escape')
    else await page.locator('.q-dialog__backdrop').last().click({ position: { x: 2, y: 2 } })
    await expect(page.getByRole('dialog')).toHaveCount(1)
    await editor.getByRole('button', { name: 'Tester la connexion', exact: true }).click()
    await expect(page.getByRole('dialog').last().getByLabel('token *', { exact: true })).toHaveValue('')
    await expect(page.getByLabel('Référence à transmettre à l’agent', { exact: true })).toHaveCount(0)
    await page.getByRole('dialog').last().getByRole('button', { name: 'Fermer', exact: true }).first().click()
    await expect(page.getByRole('dialog')).toHaveCount(1)
    await editor.getByRole('button', { name: 'Fermer', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const created = await allowed('tool_admin_create', { candidate_reference: reference })
    expect(created.persisted).toBe(true)
    expect(JSON.stringify(created)).not.toContain(secret)
    const toolId = created.tool.id
    const connected = await allowed('tool_admin_connection_create', {
      tool_id: toolId, agent_id: fixture.agent_id, expected_version: created.version,
    })
    const connectionId = connected.connection.id
    expect(connected.connection.active).toBe(false)
    expect(connected.connection.effective_params.token.configured).toBe(true)
    const connectionTest = await allowed('tool_admin_connection_test', { connection_id: connectionId })
    expect(connectionTest.diagnostic.success).toBe(true)
    const active = await allowed('tool_admin_connection_update', {
      connection_id: connectionId, active: true, expected_version: connected.version,
    })
    const functions = await allowed('tool_admin_connection_function_list', { connection_id: connectionId })
    expect(functions.items.find(fn => fn.name === 'lookup').available).toBe(true)
    const revoked = await allowed('tool_admin_connection_function_set', {
      connection_id: connectionId, function_name: 'lookup', state: 'disabled', expected_version: active.version,
    })
    expect(revoked.function.effective).toBe(false)
    await page.reload()
    await expect(page.getByText(code, { exact: true })).toBeVisible()
    const current = await allowed('tool_admin_get', { tool_id: toolId })
    const blocked = await invoke('tool_admin_delete', { tool_id: toolId, expected_version: current.version })
    expect(blocked.error.kind).toBe('dependencies_blocking')
    await allowed('tool_admin_connection_delete', { connection_id: connectionId, expected_version: revoked.version })
    const detached = await allowed('tool_admin_get', { tool_id: toolId })
    await allowed('tool_admin_delete', { tool_id: toolId, expected_version: detached.version })
    await page.reload()
    await expect(page.getByText(code, { exact: true })).toHaveCount(0)
    expect(errors).toEqual([])
  })
}
