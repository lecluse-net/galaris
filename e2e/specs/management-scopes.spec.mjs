import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'
import { selectOption } from '../select-option.mjs'

test('five administrative Tools retain a human-selected scope and enforce it on native MCP calls', async ({ page, request }) => {
  test.setTimeout(180_000)
  const errors = collectPageErrors(page)
  const checked = async response => {
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.status() === 204 ? null : response.json()
  }
  const fixture = await checked(await request.post('/api/__test/seed'))
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt =>
    prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const editorial = { ...headers, 'X-Editorial-Profile-Version': '1' }
  const prefix = `/api/__test/agent-admin/${fixture.agent_id}`
  const setup = await checked(await request.post(`${prefix}/setup`))
  const peer = await checked(await request.post('/api/agents', { headers: editorial, data: {
    user_id: setup.user_id, title_id: setup.title_id, code: `scope-peer-${fixture.agent_id}`,
    first_name: 'Synthetic', last_name: `Scope peer ${fixture.agent_id}`,
  } }))
  const team = await checked(await request.post('/api/teams', { headers, data: { name: `Synthetic scope team ${fixture.agent_id}` } }))
  for (const agent of [fixture.agent_id, peer.id]) {
    await checked(await request.put(`/api/agents/teams/${team.id}/members/${agent}`, { headers, data: { present: true } }))
  }
  const tools = await checked(await request.get('/api/tools', { headers }))
  const connectionFor = async (code, agentId) => {
    const tool = tools.find(item => item.code === code)
    const records = await checked(await request.get(`/api/connections?tool_id=${tool.id}&agent_id=${agentId}`, { headers }))
    return records[0] ?? checked(await request.post('/api/connections', { headers, data: { tool_id: tool.id, agent_id: agentId, active: true } }))
  }
  const chat = await connectionFor('chat', peer.id)
  await checked(await request.patch(`/api/connections/${chat.id}`, { headers, data: { active: true } }))
  await checked(await request.post('/api/chat/rooms', { headers, data: { agent_id: peer.id } }))
  const referrers = await checked(await request.get(`/api/goals/referrers/messenger?agent_id=${peer.id}`, { headers }))
  const referrer = referrers.find(item => item.is_current_user)
  expect(referrer).toBeTruthy()
  const goal = await checked(await request.post('/api/goals', { headers: editorial, data: {
    agent_id: peer.id, title: 'Synthetic scoped Goal', description: '<p>Entirely synthetic scope check.</p>', active: false,
    referrer: { type: 'MESSENGER', connection_id: referrer.connection_id, user_id: referrer.user_id, display_name: referrer.display_name },
  } }))
  const process = await checked(await request.post('/api/processes/internal/definitions', { headers, data: {
    agent_id: peer.id, owner: 'agent', owner_id: peer.id, title: 'Synthetic scoped process',
    code: `scope-process-${fixture.agent_id}`, graph: {
      nodes: [{ id: 'start', kind: 'start' }, { id: 'end', kind: 'end' }],
      flows: [{ id: 'done', source: 'start', target: 'end' }],
    },
  } }))
  const domains = [
    { code: 'agent_admin', label: 'AgentAdmin', function: 'agent_update', args: { agent_id: peer.id, changes: { job_title: 'Synthetic scoped update' } } },
    { code: 'tool_admin', label: 'ToolAdmin', function: 'tool_admin_connection_list', args: { agent_id: peer.id } },
    { code: 'process_admin', label: 'Administration des processus', function: 'process_admin_get', args: { process_id: process.id } },
    { code: 'goal_management', label: 'Gestion des objectifs', function: 'goal_update', args: { goal_id: goal.id, expected_revision: goal.revision, title: 'Synthetic updated Goal' } },
    { code: 'galaris_admin', label: 'Administration Galaris', function: 'llm_calls', args: { date_debut: '2026-01-01T00:00:00Z', date_fin: '2026-12-31T23:59:59Z' } },
  ]
  const invoke = async domain => {
    if (domain.code === 'goal_management') {
      const current = await checked(await request.get(`/api/goals/${goal.id}`, { headers }))
      domain.args.expected_revision = current.revision
    }
    const result = await checked(await request.post(`${prefix}/call/${domain.function}`, { data: domain.args }))
    const data = domain.code === 'tool_admin' && typeof result.data === 'string' ? JSON.parse(result.data) : result.data
    return { ...result, data, is_error: result.is_error || data?.success === false }
  }
  const caller = await checked(await request.get(`/api/agents/${fixture.agent_id}`, { headers }))
  for (const domain of domains) {
    const connection = await connectionFor(domain.code, fixture.agent_id)
    const scope = async value => checked(await request.patch(`/api/connections/${connection.id}`, {
      headers, data: { active: true, params: { 'tools.management_scope': value } },
    }))
    await scope('usage')
    await checked(await request.put(`/api/connections/${connection.id}/functions/${domain.function}`, { headers, data: { state: 'enabled' } }))
    expect((await invoke(domain)).is_error, `${domain.code}: usage must not administer`).toBe(true)
    await page.goto('/tools?tab=connections')
    await selectOption(page, page.getByRole('combobox', { name: 'Filtrer par agent', exact: true }), `${caller.first_name} ${caller.last_name}`)
    const row = page.locator('tbody tr').filter({ hasText: domain.label })
    await expect(row).toHaveCount(1)
    await row.getByRole('button', { name: 'Modifier', exact: true }).click()
    const dialog = page.getByRole('dialog')
    const selector = dialog.getByRole('combobox', { name: 'Portée de gestion', exact: true })
    await selectOption(page, selector, 'Gestion de niveau équipe')
    const saved = page.waitForResponse(response => response.url().endsWith(`/api/connections/${connection.id}`)
      && response.request().method() === 'PATCH')
    await dialog.getByRole('button', { name: 'Modifier', exact: true }).click()
    expect((await saved).ok()).toBeTruthy()
    await expect(dialog).toHaveCount(0)
    await row.getByRole('button', { name: 'Modifier', exact: true }).click()
    await expect(selector).toHaveValue('Gestion de niveau équipe')
    await dialog.getByRole('button', { name: 'Fermer', exact: true }).click()
    const result = await invoke(domain)
    expect(result.is_error, `${domain.code}: ${JSON.stringify(result)}`).toBe(false)
    if (domain.code === 'goal_management') domain.args.expected_revision = result.data.revision
    if (domain.code === 'agent_admin') {
      const self = await checked(await request.post(`${prefix}/call/agent_update`, {
        data: { agent_id: fixture.agent_id, changes: { job_title: 'Forbidden self mutation' } },
      }))
      expect(self.is_error).toBe(true)
    }
    await checked(await request.put(`/api/agents/teams/${team.id}/members/${peer.id}`, { headers, data: { present: false } }))
    if (domain.code !== 'galaris_admin') expect((await invoke(domain)).is_error, `${domain.code}: removed teammate`).toBe(true)
    await scope('all')
    expect((await invoke(domain)).is_error, `${domain.code}: global scope`).toBe(false)
    await checked(await request.put(`/api/agents/teams/${team.id}/members/${peer.id}`, { headers, data: { present: true } }))
    await scope('usage')
    expect((await invoke(domain)).is_error, `${domain.code}: live scope revocation`).toBe(true)
  }
  await test.step('Process Lab saves a native Dataset and executes its synthetic case', async () => {
    await page.goto('/lab/processes')
    await page.getByRole('spinbutton', { name: 'Agent exécutant', exact: true }).fill(String(peer.id))
    await page.getByRole('textbox', { name: 'Code immuable', exact: true }).fill(process.code)
    await page.getByRole('textbox', { name: 'Titre', exact: true }).fill('Synthetic native Dataset campaign')
    const saved = page.waitForResponse(response => response.url().endsWith('/evaluation/process-campaigns/datasets')
      && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Enregistrer les cas synthétiques', exact: true }).click()
    const dataset = await checked(await saved)
    expect(dataset.dataset_uri).toBe(`data://${dataset.dataset_id}`)
    await expect(page.getByRole('textbox', { name: 'Jeu de données d’entrées synthétiques', exact: true })).toHaveValue(dataset.dataset_uri)
    const started = page.waitForResponse(response => response.url().endsWith('/evaluation/process-campaigns')
      && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Démarrer les runs réels', exact: true }).click()
    const campaign = await checked(await started)
    expect(campaign.dataset_uri).toBe(dataset.dataset_uri)
    await expect.poll(async () => (await checked(await request.get(`/api/evaluation/process-campaigns/${campaign.id}`, { headers }))).status,
      { timeout: 30_000 }).toBe('completed')
    await expect(page.getByRole('cell', { name: 'success', exact: true })).toBeVisible()
    await page.reload()
    await page.getByRole('textbox', { name: 'Identifiant de campagne', exact: true }).fill(campaign.id)
    await page.getByRole('button', { name: 'Afficher une campagne', exact: true }).click()
    await expect(page.getByRole('cell', { name: 'success', exact: true })).toBeVisible()
  })
  expect(errors()).toEqual([])
})
