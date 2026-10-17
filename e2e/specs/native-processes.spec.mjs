import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt =>
    prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
})

async function humanRequestRoom(request, fixture, headers, title) {
  let destination
  await expect.poll(async () => {
    for (const room of fixture.rooms) {
      const history = await (await request.get(`/api/chat/rooms/${room}/messages`, { headers })).json()
      if (history.items.some(message => message.text.includes(title))) {
        destination = room
        return true
      }
    }
    return false
  }, { timeout: 30_000 }).toBe(true)
  return destination
}

for (const mode of ['code', 'human']) {
test(`a real ${mode} IF follows its boolean branch after Dataset code execution`, async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed?mode=process-human')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const user = await (await request.get('/api/auth/me', { headers })).json()
  const output = [{ name: 'variable_1', type: 'int', nullable: false }]
  const graph = { schema_version: 'galaris.bpmn/v2', inputs: [
    { name: 'variable_1', type: 'int', nullable: false, default: { type: 'int', value: 123 } },
    { name: 'variable_2', type: 'string', nullable: false, default: { type: 'string', value: 'mon projet' } },
  ], outputs: output, actors: [{ id: 'executor', name: 'Executor', kind: 'agent', agent_id: fixture.agent_id },
    { id: 'reviewer', name: 'Reviewer', kind: 'human', user_id: user.id }], nodes: [
    { id: 'start', kind: 'start' },
    { id: 'work', kind: 'code', title: 'Update the counter', inputs: [], outputs: output,
      config: { actor: 'executor', dataset_code: true, code: 'return {"variable_1": variable_1}' } },
    { id: 'check', kind: 'if', title: 'Synthetic project decision', config: { mode, actor: mode === 'human' ? 'reviewer' : 'executor',
      prompt: 'Choose whether this invented project should continue.', code: 'return variable_2 != "pas mon projet"' } },
    { id: 'yes', kind: 'end', title: 'Approved' }, { id: 'no', kind: 'end', title: 'Declined' },
  ], flows: [{ id: 'a', source: 'start', target: 'work' }, { id: 'b', source: 'work', target: 'check' },
    { id: 'c', source: 'check', target: 'yes', condition: 'decision' }, { id: 'd', source: 'check', target: 'no' }] }
  const created = await request.post('/api/processes/internal/definitions', { headers, data: {
    agent_id: fixture.agent_id, title: 'Synthetic sandbox and decision workflow',
    description: 'Synthetic decision workflow description', owner: 'user', graph,
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const definition = await created.json()
  await page.goto(`/process/internal/${definition.code}`)
  const description = page.getByRole('textbox', { name: 'Description', exact: true })
  await expect(description).toHaveValue('Synthetic decision workflow description')
  await description.fill('Updated synthetic decision workflow description')
  await expect(page.getByRole('button', { name: /^(True output of|Sortie True de) Synthetic project decision$/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^(False output of|Sortie False de) Synthetic project decision$/ })).toBeVisible()
  await page.getByRole('button', { name: 'Update the counter · work', exact: true }).click()
  await page.getByRole('textbox', { name: /^(Python program|Programme Python)$/ }).fill('return {"variable_1": variable_1 + 1}')
  await page.getByRole('button', { name: /^(Close settings|Fermer les paramètres)$/ }).click()
  const saving = page.waitForResponse(response => response.url().endsWith(`/definitions/${definition.code}`) && response.request().method() === 'PUT')
  await page.getByRole('button', { name: /^(Save|Enregistrer)$/, exact: true }).click()
  expect((await saving).ok()).toBeTruthy()
  await page.reload()
  await expect(description).toHaveValue('Updated synthetic decision workflow description')
  await page.screenshot({ path: test.info().outputPath('process-description.png'), fullPage: true, animations: 'disabled' })
  const launched = await request.post(`/api/processes/internal/definitions/${definition.code}/runs`, { headers, data: { agent_id: fixture.agent_id, input: {} } })
  expect(launched.ok(), await launched.text()).toBeTruthy()
  const { run_id: identity } = await launched.json()
  let observer
  let pendingMetrics
  const notifications = []
  if (mode === 'human') {
    const room = await humanRequestRoom(request, fixture, headers, 'Synthetic project decision')
    await page.goto(`/process/internal/run/${identity}`)
    await expect(page.getByText(/^(Waiting for a reply in messaging|En attente d’une réponse dans la messagerie)$/)).toBeVisible()
    await page.getByRole('button', { name: /^(Pause admissions|Suspendre les admissions)$/ }).click()
    await expect(page.getByText(/^(New activities are paused|Les nouvelles activités sont suspendues)/)).toBeVisible()
    await page.getByRole('button', { name: /^(Resume|Reprendre)$/ }).click()
    await expect.poll(async () => (await (await request.get(`/api/processes/internal/runs/${identity}`, { headers })).json()).paused).toBe(false)
    observer = await page.context().newPage()
    await observer.route(`**/api/processes/internal/runs/${identity}/metrics`, route => {
      if (!pendingMetrics) { pendingMetrics = route; return }
      return route.continue()
    })
    observer.on('websocket', socket => socket.on('framereceived', ({ payload }) => {
      if (typeof payload === 'string' && payload.includes('process_run.update') && payload.includes(identity)) notifications.push(payload)
    }))
    await observer.goto(`/process/internal/run/${identity}`)
    await expect(observer.getByRole('button', { name: 'Synthetic project decision · check', exact: true })).toHaveAttribute('aria-current', 'step')
    await page.goto(`/chat?room=${room}`)
    await page.getByRole('region', { name: 'Synthetic project decision', exact: true }).getByRole('button', { name: 'False', exact: true }).click()
  }
  await expect.poll(async () => (await (await request.get(`/api/processes/internal/runs/${identity}`, { headers })).json()).status,
    { timeout: 30_000 }).toBe('success')
  const run = await (await request.get(`/api/processes/internal/runs/${identity}`, { headers })).json()
  expect(run.output).toEqual({ variable_1: { type: 'int', value: 124 } })
  expect(run.nodes.map(node => node.node_key)).toContain(mode === 'human' ? 'no' : 'yes')
  expect(run.nodes.map(node => node.node_key)).not.toContain(mode === 'human' ? 'yes' : 'no')
  if (observer) {
    await expect(observer.getByRole('button', { name: 'Synthetic project decision · check', exact: true })).not.toHaveAttribute('aria-current', 'step')
    await expect(observer.getByRole('status').filter({ hasText: /^(Completed|Terminée)$/ }).first()).toBeVisible()
    expect(notifications.length).toBeGreaterThan(0)
    // Progress remains usable even while accounting has not responded.
    expect(pendingMetrics).toBeTruthy()
    await pendingMetrics.continue()
    await observer.close()
  }
  await page.goto(`/process/internal/run/${identity}`)
  await expect(page.getByRole('status').filter({ hasText: /^(Completed|Terminée)$/ }).first()).toBeVisible()
})
}

for (const fileOnly of [false, true]) {
test(fileOnly ? 'a file-only chat reply completes its pending process with the original attachment URI'
  : 'typed human activity validates defaults and preserves false and omitted nullable outputs', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const fixture = await (await request.post('/api/__test/seed?mode=process-human')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const user = await (await request.get('/api/auth/me', { headers })).json()
  const outputs = fileOnly ? [{ name: 'report', type: 'File', nullable: false }] : [
    { name: 'accepted', type: 'bool', nullable: false, default: { type: 'bool', value: true } },
    { name: 'note', type: 'string', nullable: true },
  ]
  const response = await request.post('/api/processes/internal/definitions', { headers, data: {
    agent_id: fixture.agent_id, title: 'Synthetic typed review', owner: 'user', graph: {
      schema_version: 'galaris.bpmn/v2', inputs: [], outputs,
      actors: [{ id: 'reviewer', name: 'Reviewer', kind: 'human', user_id: user.id }],
      nodes: [{ id: 'start', kind: 'start' }, { id: 'review', kind: 'human_task', title: 'Synthetic typed review',
        inputs: [], outputs, config: { prompt: 'Review this entirely invented case.', actor: 'reviewer' } }, { id: 'end', kind: 'end' }],
      flows: [{ id: 'a', source: 'start', target: 'review' }, { id: 'b', source: 'review', target: 'end' }],
    },
  } })
  expect(response.ok(), await response.text()).toBeTruthy()
  const definition = await response.json()
  const invalid = structuredClone(definition.graph)
  invalid.nodes[1].outputs[0].default = { type: fileOnly ? 'File' : 'bool', value: null }
  const rejected = await request.put(`/api/processes/internal/definitions/${definition.code}`, { headers,
    data: { graph: invalid, expected_revision: definition.revision } })
  expect(rejected.status()).toBe(422)
  const launched = await request.post(`/api/processes/internal/definitions/${definition.code}/runs`, { headers,
    data: { agent_id: fixture.agent_id, input: {} } })
  expect(launched.ok(), await launched.text()).toBeTruthy()
  const { run_id: identity } = await launched.json()
  const requestRoom = await humanRequestRoom(request, fixture, headers, 'Synthetic typed review')
  await page.goto(`/chat?room=${requestRoom}`)
  await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop =>
    backdrop.click({ position: { x: 380, y: 200 } }))
  await expect(page.locator('.message-timeline')).toContainText('Synthetic typed review', { timeout: 30_000 })
  const composer = page.locator('.composer-fields textarea')
  if (fileOnly) {
    await page.locator('.attachment-file-input').setInputFiles({ name: 'synthetic-review.txt', mimeType: 'text/plain',
      buffer: Buffer.from('Entirely synthetic process review attachment.') })
  } else {
    await composer.fill('Je refuse ce cas, sans commentaire supplémentaire.')
  }
  await composer.press('Enter')
  await expect(page.locator('.message-timeline')).toContainText('Votre réponse a été enregistrée', { timeout: 30_000 })
  await expect.poll(async () => (await (await request.get(`/api/processes/internal/runs/${identity}`, { headers })).json()).status,
    { timeout: 30_000 }).toBe('success')
  const run = await (await request.get(`/api/processes/internal/runs/${identity}`, { headers })).json()
  if (fileOnly) {
    const history = await (await request.get(`/api/chat/rooms/${requestRoom}/messages`, { headers })).json()
    const original = history.items.find(message => message.files.some(file => file.name === 'synthetic-review.txt'))
    expect(original.text).toBe('')
    expect(run.output).toEqual({ report: { type: 'File', value: original.files[0].uri } })
  } else {
    expect(run.output).toEqual({ accepted: { type: 'bool', value: false }, note: { type: 'string', value: null } })
  }
  const dataset = await (await request.get(`/api/datasets/${run.dataset_uri.replace(/^(?:document|data):\/\//, '')}`, { headers })).json()
  expect(JSON.parse(dataset.content).data).toEqual(run.output)
})
}

test('an execution failure stops the run before its next task and displays the error code', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const created = await request.post('/api/processes/internal/definitions', { headers, data: {
    agent_id: fixture.agent_id, title: 'Invented failing process', owner: 'user', graph: {
      nodes: [{ id: 'start', kind: 'start' },
        { id: 'fails', kind: 'program', config: { program_uri: 'document://00000000-0000-0000-0000-000000000001' } },
        { id: 'forbidden', kind: 'task', config: { prompt: 'This task must never be admitted.' } }, { id: 'end', kind: 'end' }],
      flows: [{ id: 'a', source: 'start', target: 'fails' }, { id: 'b', source: 'fails', target: 'forbidden' }, { id: 'c', source: 'forbidden', target: 'end' }],
    },
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const definition = await created.json()
  // This assembled stack has no qualified program executor; that is a real admission failure.
  const launched = await request.post(`/api/processes/internal/definitions/${definition.code}/runs`, { headers,
    data: { agent_id: fixture.agent_id, input: { kept: 'Invented data' }, files: [] } })
  expect(launched.ok(), await launched.text()).toBeTruthy()
  const { run_id: identity } = await launched.json()
  await page.goto(`/process/internal/run/${identity}`)
  await expect(page.getByRole('main').getByRole('alert')).toContainText('node_failed', { timeout: 30_000 })
  await expect(page.getByRole('status').filter({ hasText: /^(Failed|En échec)$/ }).first()).toBeVisible({ timeout: 30_000 })
  const run = await (await request.get(`/api/processes/internal/runs/${identity}`, { headers })).json()
  expect(run.error_code).toBe('node_failed')
  expect(run.nodes.map(node => node.node_key)).not.toContain('forbidden')
  const dataset = await (await request.get(`/api/datasets/${run.dataset_uri.replace(/^(?:document|data):\/\//, '')}`, { headers })).json()
  expect(JSON.parse(dataset.content)).toEqual({ kept: 'Invented data' })
})

test('a visually edited native process runs its saved Task and retains its own graph and Dataset', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const created = await request.post('/api/processes/internal/definitions', { headers, data: {
    agent_id: fixture.agent_id, title: 'Invented native workflow', owner: 'user', graph: {
      schema_version: 'galaris.bpmn/v1', actors: [
        { id: 'executor', name: 'Executor', kind: 'agent', agent_id: fixture.agent_id },
        { id: 'validator', name: 'Validator', kind: 'agent', agent_id: fixture.agent_id },
      ], nodes: [
        { id: 'start', kind: 'start' },
        { id: 'work', kind: 'task', title: 'Draft note', config: { prompt: 'Invent a synthetic note.', actor: 'executor' } },
        { id: 'end', kind: 'end', config: { output: { $expr: 'results.work' } } },
      ], flows: [{ id: 'first', source: 'start', target: 'work' }, { id: 'last', source: 'work', target: 'end' }],
    },
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const definition = await created.json()
  const definitionPath = `/api/processes/internal/definitions/${definition.code}`
  await page.goto(`/process/internal/${definition.code}`)
  await page.getByRole('button', { name: 'Draft note · work', exact: true }).click()
  const instructions = page.getByRole('textbox', { name: /^(Task instructions|Instructions de la tâche)$/ })
  await instructions.fill('Invent a synthetic note from the supplied input.')
  await page.getByRole('button', { name: /^(Fit the diagram|Afficher tout le diagramme)$/ }).click()
  const lane = page.locator('.swimlane').filter({ has: page.getByRole('button', { name: /^(Remove actor Validator|Supprimer l’acteur Validator)$/ }) })
  await lane.scrollIntoViewIfNeeded()
  const nodeBounds = await page.getByRole('button', { name: 'Draft note · work', exact: true }).boundingBox(), laneBounds = await lane.boundingBox()
  expect(nodeBounds).toBeTruthy(); expect(laneBounds).toBeTruthy()
  await page.mouse.move(nodeBounds.x + nodeBounds.width / 2, nodeBounds.y + nodeBounds.height / 2)
  await page.mouse.down()
  await page.mouse.move(nodeBounds.x + nodeBounds.width / 2, laneBounds.y + laneBounds.height / 2, { steps: 8 })
  await page.mouse.up()
  // Actor assignment is checked in the persisted graph and the admitted Run below.
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(definitionPath))
  await page.getByRole('button', { name: /^(Save|Enregistrer)$/ }).click()
  const savedResponse = await saved
  expect(savedResponse.ok()).toBeTruthy()
  expect((await savedResponse.json()).graph.nodes.find(node => node.id === 'work').config.actor).toBe('validator')
  await page.reload()
  await page.getByRole('button', { name: 'Draft note · work', exact: true }).click()
  const admission = await request.post(`${definitionPath}/runs`, { headers,
    data: { agent_id: fixture.agent_id, input: { subject: 'Invented example' } } })
  expect(admission.ok(), await admission.text()).toBeTruthy()
  const { run_id: runId } = await admission.json()
  await page.goto(`/process/internal/run/${runId}`)
  await expect(page.getByRole('button', { name: 'Draft note · work', exact: true })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: /^(Completed|Terminée)$/ }).first()).toBeVisible({ timeout: 30_000 })
  let run
  await expect.poll(async () => {
    const runResponse = await request.get(`/api/processes/internal/runs/${runId}`, { headers })
    expect(runResponse.ok(), await runResponse.text()).toBeTruthy()
    run = await runResponse.json()
    return run.status
  }).toBe('success')
  expect(run.definition_revision).toBe(2)
  expect(run.graph.nodes.find(node => node.id === 'work').config.actor).toBe('validator')
  expect(run.nodes.map(node => node.status)).toEqual(['success', 'success', 'success'])
  const datasetId = run.dataset_uri.replace(/^(?:document|data):\/\//, '')
  const datasetResponse = await request.get(`/api/datasets/${datasetId}`, { headers })
  expect(datasetResponse.ok(), await datasetResponse.text()).toBeTruthy()
  const dataset = await datasetResponse.json()
  expect(dataset.uri).toBe(`data://${datasetId}`)
  expect(JSON.parse(dataset.content)).toEqual({ subject: 'Invented example' })
  expect(JSON.parse(dataset.content)).toEqual(run.output)
  const changed = await request.put(definitionPath, { headers, data: { expected_revision: 2, title: 'Changed next launch',
    graph: { ...run.graph, nodes: run.graph.nodes.map(node => node.id === 'work'
      ? { ...node, config: { ...node.config, prompt: 'A different instruction for future launches.' } } : node) },
  } })
  expect(changed.ok(), await changed.text()).toBeTruthy()
  await page.reload()
  await expect(page.getByRole('status').filter({ hasText: /^(Completed|Terminée)$/ }).first()).toBeVisible()
  const frozen = await (await request.get(`/api/processes/internal/runs/${runId}`, { headers })).json()
  expect(frozen.graph.nodes.find(node => node.id === 'work').config.prompt).toBe('Invent a synthetic note from the supplied input.')
  expect(frozen.definition_revision).toBe(2)
})

test('an activity inserted from a handle waits for its human and resumes after one submitted result', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed?mode=process-human')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const currentUser = await (await request.get('/api/auth/me', { headers })).json()
  expect(currentUser.id).toBeTruthy()
  const created = await request.post('/api/processes/internal/definitions', { headers, data: {
    agent_id: fixture.agent_id, title: 'Invented human review', owner: 'user', graph: {
      actors: [{ id: 'reviewer', name: 'Reviewer', kind: 'human', user_id: currentUser.id }],
      nodes: [{ id: 'start', kind: 'start' }, { id: 'end', kind: 'end' }],
      flows: [{ id: 'initial', source: 'start', target: 'end' }],
    },
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const definition = await created.json()
  const path = `/api/processes/internal/definitions/${definition.code}`
  await page.goto(`/process/internal/${definition.code}`)
  await page.getByRole('button', { name: /^(Output of Start|Sortie de Début)$/ }).click()
  await page.getByText(/^(Human task|Tâche humaine)$/, { exact: true }).click()
  const activityTitle = page.getByRole('dialog', { name: /^(Activity settings|Paramètres de l’activité)$/ }).getByRole('textbox', { name: /^(Title|Titre)$/ })
  // Clicking waits for the newly opened inspector to settle before native paste.
  await activityTitle.click()
  await activityTitle.fill('Review invented note')
  await expect(page.getByRole('button', { name: /^Review invented note · human_task_/ })).toBeVisible()
  await page.getByRole('textbox', { name: /^(Task instructions|Instructions de la tâche)$/ }).fill('Review the invented note and respond.')
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(path))
  await page.getByRole('button', { name: /^(Save|Enregistrer)$/ }).click()
  const savedResponse = await saved
  expect(savedResponse.ok()).toBeTruthy()
  expect((await savedResponse.json()).graph.nodes.find(node => node.kind === 'human_task').title).toBe('Review invented note')
  const admission = await request.post(`${path}/runs`, { headers, data: { agent_id: fixture.agent_id, input: {} } })
  expect(admission.ok(), await admission.text()).toBeTruthy()
  const { run_id: identity } = await admission.json()
  await page.goto(`/process/internal/run/${identity}`)
  await expect.poll(async () => {
    const reply = await request.get(`/api/processes/internal/runs/${identity}`, { headers })
    return (await reply.json()).node_statuses
  }).toMatchObject({ start: 'success' })
  const requestRoom = await humanRequestRoom(request, fixture, headers, 'Review invented note')
  await page.goto(`/chat?room=${requestRoom}`)
  await expect(page.locator('.message-timeline')).toContainText('Review invented note', { timeout: 30_000 })
  await page.locator('.composer-fields textarea').fill('Approved synthetic note')
  await page.locator('.composer-fields textarea').press('Enter')
  await expect(page.locator('.message-timeline')).toContainText('Votre réponse a été enregistrée', { timeout: 30_000 })
  await expect.poll(async () => {
    const reply = await request.get(`/api/processes/internal/runs/${identity}`, { headers })
    return (await reply.json()).status
  }, { timeout: 30_000 }).toBe('success')
  await page.goto(`/process/internal/run/${identity}`)
  await expect(page.getByRole('button', { name: /^(Review invented note · human_task_)/ })).toBeVisible()
  const run = await (await request.get(`/api/processes/internal/runs/${identity}`, { headers })).json()
  expect(run.nodes.map(node => node.status)).toEqual(['success', 'success', 'success'])
  expect(run.output).toEqual({})
  expect(run.nodes.find(node => node.node_key.startsWith('human_task_')).output).toEqual({ text: 'Approved synthetic note' })
})
