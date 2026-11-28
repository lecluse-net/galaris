import { randomUUID } from 'node:crypto'
import { notificationPrompt } from '../notification-prompt.mjs'
import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('agent consultation shows agents from each of the user’s teams', async ({ page, request }) => {
  const read = async response => {
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const fixture = await read(await request.post('/api/__test/seed'))
  const admin = await read(await request.post('/api/auth/login-json', { data: { email: fixture.email, password: fixture.password } }))
  const headers = { Authorization: `Bearer ${admin.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const unique = randomUUID()
  const credentials = { email: `agent-reader-${unique}@example.com`, password: 'Synthetic-agent-reader-123!' }
  const user = await read(await request.post('/api/auth/users', { headers, data: { ...credentials, language: 'en' } }))
  const privileges = await read(await request.get('/api/authorize/privileges', { headers }))
  const role = await read(await request.post('/api/authorize/roles', { headers, data: { code: `agent-reader-${unique}` } }))
  await read(await request.post(`/api/authorize/roles/${role.id}/privileges`, {
    headers, data: { privilege_ids: ['AGENT_ACCESS', 'CONNECTION_ACCESS'].map(code => privileges.find(privilege => privilege.code === code).id) },
  }))
  await read(await request.post('/api/authorize/assignments', { headers, data: { user_id: user.id, role_id: role.id, is_default: true } }))
  const basis = await read(await request.get(`/api/agents/${fixture.agent_id}`, { headers }))
  const service = await read(await request.post('/api/services', { headers, data: {
    code: `team-connector-${unique}`, label: 'Synthetic team connector',
  } }))

  const teamNames = [`Synthetic North ${fixture.agent_id}`, `Synthetic South ${fixture.agent_id}`]
  for (const [index, name] of teamNames.entries()) {
    const team = await read(await request.post('/api/teams', { headers, data: { name } }))
    const membership = await request.put(`/api/teams/${team.id}/humans/${user.id}`, { headers, data: { present: true } })
    expect(membership.ok(), await membership.text()).toBeTruthy()
    const agent = await read(await request.post('/api/agents', { headers, data: {
      code: `team-reader-${index}-${unique}`, title_id: basis.title_id, team_ids: [team.id],
      first_name: index === 0 ? 'Synthetic North Agent' : 'Synthetic South Agent',
      job_description: '<p>Synthetic team profile</p>',
    } }))
    if (index === 0) await read(await request.post('/api/connections', { headers, data: {
      service_id: service.id, agent_id: agent.id, active: true,
    } }))
  }

  const session = await read(await page.request.post('/api/auth/login-json', { data: credentials }))
  await page.addInitScript(token => localStorage.setItem('access_token', token), session.access_token)
  const errors = collectPageErrors(page)
  await page.goto('/agent')
  const north = page.getByText('Synthetic North Agent', { exact: true })
  const south = page.getByText('Synthetic South Agent', { exact: true })
  await expect(north).toBeVisible()
  await expect(south).toBeVisible()
  await expect(page.locator('.agent-card')).toHaveCount(2)
  await page.getByRole('tab', { name: teamNames[1], exact: true }).click()
  await expect(north).toHaveCount(0)
  await expect(south).toBeVisible()
  await page.locator('.agent-card').getByText('Synthetic team profile', { exact: true }).click()
  const profile = page.getByRole('dialog')
  await expect(profile.getByText('Synthetic team profile', { exact: true })).toBeVisible()
  await expect(profile.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(profile).toHaveCount(0)

  await page.goto('/services?tab=connections')
  const filter = page.getByRole('combobox', { name: 'Filter by agent', exact: true })
  await filter.click()
  const northOption = page.getByRole('option', { name: 'Synthetic North Agent', exact: true })
  await expect(northOption).toBeEnabled()
  await expect(page.getByRole('option', { name: 'Synthetic South Agent', exact: true })).toBeEnabled()
  await northOption.click()
  await expect(filter.locator('..')).toContainText('Synthetic North Agent')
  await expect(page.getByRole('button', { name: 'New Connection', exact: true })).toHaveCount(0)
  const teamConnection = page.locator('.connection-table tbody tr').filter({ hasText: 'Synthetic team connector' })
  await teamConnection.getByRole('button', { name: 'View connection', exact: true }).click()
  const connection = page.getByRole('dialog')
  await expect(connection.getByText('Read only', { exact: true })).toBeVisible()
  await expect(connection.getByText('Synthetic North Agent', { exact: true })).toBeVisible()
  await expect(connection.getByText('Synthetic team connector', { exact: true })).toBeVisible()
  expect(errors()).toEqual([])
})

async function setupAdministration(page, request) {
  const pageErrors = collectPageErrors(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await pageErrors.settle()
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  // Resolve optional onboarding before opening the growing agent catalogue.
  // Its locator handler would otherwise run inside the portrait assertions.
  await pageErrors.settle()
  const promptToDismiss = notificationPrompt(page)
  if (await promptToDismiss.isVisible()) {
    await promptToDismiss.getByRole('button', { name: 'Plus tard', exact: true }).click()
    await expect(promptToDismiss).toBeHidden()
  }
  await page.addLocatorHandler(notificationPrompt(page), async prompt => {
    await prompt.getByRole('button', { name: 'Plus tard', exact: true }).click()
  })
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const prefix = `/api/__test/agent-admin/${fixture.agent_id}`
  const setup = await (await request.post(`${prefix}/setup`)).json()
  const team = await request.post('/api/teams', { headers, data: {
    name: `Synthetic portrait team ${fixture.agent_id}`, manager_user_id: setup.user_id,
  } })
  expect(team.ok(), await team.text()).toBeTruthy()
  // These portraits belong to unassigned agents, even when other teams exist.
  const unassigned = page.locator('body:not(:has([role="dialog"]:visible))')
    .getByRole('tab', { name: /^(No team|Sans équipe)$/, exact: true }).and(page.locator('[aria-selected="false"]'))
  await page.addLocatorHandler(unassigned, tab => tab.click())
  const invoke = async (name, data) => {
    const response = await request.post(`${prefix}/call/${name}`, { data })
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  return { fixture, setup, headers, prefix, invoke, pageErrors }
}

test('the agent form creates and reopens an embedded Claude selection', async ({ page, request }) => {
  const { fixture, headers, pageErrors } = await setupAdministration(page, request)
  const original = await (await request.get(`/api/agents/${fixture.agent_id}`, { headers })).json()
  await page.goto('/agent')
  await page.getByRole('button', { name: 'Nouvel Agent', exact: true }).click()
  const dialog = page.getByRole('dialog').filter({ has: page.getByLabel('Prénom *', { exact: true }) })
  const harness = dialog.getByRole('combobox', { name: 'Harnais', exact: true })
  const chooseHarness = async label => {
    await harness.click()
    await page.getByRole('option', { name: label, exact: true }).click()
    await expect(harness).toHaveValue(label)
  }
  const name = `Claude ${fixture.agent_id}`
  await dialog.getByLabel("Code de l'agent", { exact: true }).fill(`embedded-${fixture.agent_id}`)
  await dialog.getByLabel('Prénom *', { exact: true }).fill(name)
  await dialog.getByRole('combobox', { name: 'Civilité *', exact: true }).click()
  await page.getByRole('option', { name: `${original.title.label} (M)`, exact: true }).click()
  await chooseHarness('Claude Agent')
  const creation = page.waitForResponse(response => new URL(response.url()).pathname === '/api/agents' && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  const created = await creation
  expect(created.status(), await created.text()).toBe(201)
  const saved = await created.json()
  expect(saved).toMatchObject({ agent_driver: 'claude_embedded', task_harness_id: null })
  await expect(dialog).toHaveCount(0)

  const card = page.locator('.agent-card').filter({ has: page.getByText(name, { exact: true }) })
  await expect(card.getByText('Claude Agent', { exact: true })).toBeVisible()
  const open = card.getByRole('button', { name: /Modifier l.agent/ })
  await open.click()
  await expect(harness).toHaveValue('Claude Agent')
  await chooseHarness('Pydantic AI')
  const assignment = page.waitForResponse(response => new URL(response.url()).pathname === `/api/harnesses/agents/${saved.id}` && response.request().method() === 'PUT')
  await dialog.getByRole('button', { name: 'Modifier', exact: true }).click()
  const switched = await assignment
  expect(switched.status(), await switched.text()).toBe(202)
  expect(await switched.json()).toMatchObject({ driver_code: 'internal', internal: true, containerized: false })
  await expect(dialog).toHaveCount(0)
  await expect(card.getByText('Pydantic AI', { exact: true })).toBeVisible()
  await open.click()
  await expect(harness).toHaveValue('Pydantic AI')
  expect(await (await request.get(`/api/agents/${saved.id}`, { headers })).json()).toMatchObject({ agent_driver: 'internal' })
  expect(pageErrors()).toEqual([])
})

test('AgentAdmin creates an agent and generated portraits remain visible after reopening and replacement', async ({ page, request }) => {
  test.setTimeout(90_000)
  const { fixture, setup, headers, prefix, invoke, pageErrors } = await setupAdministration(page, request)
  const created = await invoke('agent_create', { configuration: {
    user_id: setup.user_id, title_id: setup.title_id,
    code: `portrait-${fixture.agent_id}`, first_name: 'Lyra', last_name: `Qualification ${fixture.agent_id}`,
    personality: '<p>Observatrice patiente.</p>', job_title: 'Astronome',
  } })
  expect(created.is_error).toBe(false)
  const target = created.data
  const catalogue = await invoke('agent_service_list', { agent_id: target.id, search: 'browser', limit: 500 })
  expect(catalogue.is_error).toBe(false)
  expect(catalogue.data.items.some(tool => tool.code === 'browser')).toBe(true)
  const errors = []
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (path.startsWith('/api/') && response.status() >= 400) errors.push(`${response.status()} ${path}`)
  })
  await pageErrors.settle()
  await page.goto('/agent')
  await expect(page.getByText(`Lyra Qualification ${fixture.agent_id}`, { exact: true })).toBeVisible()
  const portrait = page.getByRole('img', { name: `Lyra Qualification ${fixture.agent_id}`, exact: true })
  const pixel = () => portrait.evaluate(img => {
    if (!img.complete || !img.naturalWidth) return null
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1
    const context = canvas.getContext('2d')
    context.drawImage(img, 0, 0, 1, 1)
    return [...context.getImageData(0, 0, 1, 1).data].slice(0, 3)
  })
  for (const [instructions, expected] of [['blue backdrop', [0, 0, 255]], ['green backdrop', [0, 128, 0]]]) {
    await page.locator('a[href="/params"]').first().click()
    await expect(page).toHaveURL(/\/params$/)
    const generation = await invoke('agent_avatar_generate', { agent_id: target.id, instructions })
    expect(generation.is_error).toBe(false)
    expect(generation.data.registered).toBe(true)
    expect(generation.data.status).toBe('success')
    await page.locator('a[href="/agent"]').first().click()
    await expect(portrait).toBeVisible()
    await expect.poll(() => portrait.evaluate(img => [img.naturalWidth, img.naturalHeight])).toEqual([500, 313])
    await expect.poll(async () => {
      const rgb = await pixel()
      return rgb !== null && rgb.every((value, index) => Math.abs(value - expected[index]) <= 3)
    }).toBe(true)
    await page.locator('a[href="/params"]').first().click()
    await page.locator('a[href="/agent"]').first().click()
    await expect.poll(async () => {
      const rgb = await pixel()
      return rgb !== null && rgb.every((value, index) => Math.abs(value - expected[index]) <= 3)
    }).toBe(true)
  }
  const read = await (await request.get(`/api/agents/${target.id}`, { headers })).json()
  expect(read.has_avatar).toBe(true)
  expect(read.personality).toBe('<p>Observatrice patiente.</p>')
  await request.post(`${prefix}/revoke`)
  expect((await invoke('agent_service_list', { agent_id: target.id })).is_error).toBe(true)
  expect((await invoke('agent_update', { agent_id: target.id, changes: { job_title: 'Refusé' } })).is_error).toBe(true)
  expect((await (await request.get(`/api/agents/${target.id}`, { headers })).json()).job_title).toBe('Astronome')
  expect([...errors, ...pageErrors()]).toEqual([])
  expect((await request.delete(`/api/agents/${target.id}`, { headers })).status()).toBe(204)
})

test('AgentAdmin title changes refresh the reference catalogue after reopening', async ({ page, request }) => {
  test.setTimeout(90_000)
  const { fixture, headers, invoke, pageErrors } = await setupAdministration(page, request)
  // Shared references must refresh after an external administration operation.
  await page.goto('/agent')
  await page.locator('a[href="/params"]').first().click()
  const originalLabel = `Civilité synthétique ${fixture.agent_id}`
  const renamedLabel = `Civilité renommée ${fixture.agent_id}`
  const title = await invoke('agent_title_create', { configuration: { label: originalLabel, gender: 'F' } })
  expect(title.is_error).toBe(false)
  await page.locator('a[href="/agent"]').first().click()
  await page.getByRole('tab', { name: 'Civilités', exact: true }).click()
  // Browse the reference catalogue through its supported pagination controls.
  const pageSize = page.locator('.q-table__bottom .q-select')
  await pageSize.click()
  await page.getByRole('option', { name: '500', exact: true }).click()
  await expect(page.getByText(originalLabel, { exact: true })).toBeVisible()
  await page.locator('a[href="/params"]').first().click()
  expect((await invoke('agent_title_update', { title_id: title.data.id, changes: { label: renamedLabel } })).is_error).toBe(false)
  await page.locator('a[href="/agent"]').first().click()
  await page.getByRole('tab', { name: 'Civilités', exact: true }).click()
  await pageSize.click()
  await page.getByRole('option', { name: '500', exact: true }).click()
  await expect(page.getByText(renamedLabel, { exact: true })).toBeVisible()
  await expect(page.getByText(originalLabel, { exact: true })).toHaveCount(0)
  expect((await request.delete(`/api/agents/titles/${title.data.id}`, { headers })).status()).toBe(204)
  expect(pageErrors()).toEqual([])
})

test('the avatar button uses the default image profile and refreshes the portrait after reopening', async ({ page, request }, testInfo) => {
  test.setTimeout(90_000)
  const { fixture, setup, headers, invoke, pageErrors } = await setupAdministration(page, request)
  const activated = await request.post(`/api/llm-profiles/${setup.profile_id}/use`, { headers })
  expect(activated.ok(), await activated.text()).toBeTruthy()
  const created = await invoke('agent_create', { configuration: {
    user_id: setup.user_id, title_id: setup.title_id,
    code: `button-portrait-${fixture.agent_id}`, first_name: 'Lyra', last_name: `Portrait ${fixture.agent_id}`,
    personality: '<p>Observatrice patiente.</p>', job_title: 'Astronome', job_description: '<p>Étudier les galaxies.</p>',
  } })
  expect(created.is_error).toBe(false)
  const target = created.data
  await page.goto('/agent')
  const card = page.locator('.agent-card').filter({ has: page.getByText(`Lyra Portrait ${fixture.agent_id}`, { exact: true }) })
  const open = card.getByRole('button', { name: /Modifier l.agent/ })
  await open.click()
  const dialog = page.getByRole('dialog').filter({ has: page.getByLabel('Prénom *', { exact: true }) })
  const generate = dialog.getByRole('button', { name: 'Générer un avatar', exact: true })
  await expect(generate).toBeEnabled()
  await dialog.getByLabel('Prénom *', { exact: true }).fill('Brouillon')
  await expect(generate).toBeDisabled()
  await dialog.getByLabel('Prénom *', { exact: true }).fill('Lyra')
  await generate.click()
  const generationDialog = page.getByRole('dialog').filter({ has: page.getByLabel('Consignes de génération (facultatif)', { exact: true }) })
  await generationDialog.getByLabel('Consignes de génération (facultatif)', { exact: true }).fill('Portrait humain réaliste, cheveux argentés, veste verte et lunettes.')
  await generationDialog.getByRole('button', { name: 'Générer un avatar', exact: true }).click()
  await expect(page.getByText('Avatar généré avec succès', { exact: true })).toBeVisible()
  await expect(dialog.locator('.agent-dialog-avatar img')).toHaveJSProperty('naturalWidth', 500)
  await testInfo.attach('generated-avatar', { body: await dialog.screenshot(), contentType: 'image/png' })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await open.click()
  await expect(dialog.locator('.agent-dialog-avatar img')).toHaveJSProperty('naturalWidth', 500)
  await page.keyboard.press('Escape')
  const removed = await request.put(`/api/llm-profiles/${setup.profile_id}`, { headers, data: { image_llm_id: null } })
  expect(removed.ok(), await removed.text()).toBeTruthy()
  await open.click()
  await expect(generate).toHaveCount(0)
  await expect(dialog.locator('.agent-dialog-avatar img')).toHaveJSProperty('naturalWidth', 500)
  await page.keyboard.press('Escape')
  const saved = await (await request.get(`/api/agents/${target.id}`, { headers })).json()
  expect(saved.has_avatar).toBe(true)
  expect(saved.first_name).toBe('Lyra')
  expect(pageErrors()).toEqual([])
})
