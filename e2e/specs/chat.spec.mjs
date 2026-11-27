import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'
import { notificationPrompt } from '../notification-prompt.mjs'

const socketEvents = new WeakMap()
const embeddedConversationDrivers = [['embedded-pydantic', 'internal'], ['embedded-claude', 'claude_embedded']]
test.beforeEach(async ({ page }) => {
  await page.addLocatorHandler(notificationPrompt(page), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  const events = []
  socketEvents.set(page, events)
  page.on('websocket', socket => {
    events.push('websocket opened')
    socket.on('framesent', ({ payload }) => {
      const frame = String(payload)
      if (frame.includes('room.join') || frame.includes('room.leave')) events.push(frame)
    })
    socket.on('framereceived', ({ payload }) => {
      const frame = String(payload)
      if (frame.startsWith('40') || frame.startsWith('44')) events.push(frame)
    })
    socket.on('close', () => events.push('websocket closed'))
  })
})

test.afterEach(async ({ page, request }, info) => {
  if (info.status === info.expectedStatus) return
  const room = new URL(page.url()).searchParams.get('room')
  const diagnostics = {
    socketEvents: socketEvents.get(page),
    rounds: room ? await (await request.get(`/api/__test/rounds/${room}`)).json() : [],
    subscription: room ? await (await request.get(`/api/__test/subscription/${room}`)).json() : null,
    tasks: await (await request.get('/api/__test/tasks')).json(),
  }
  await info.attach('runtime-state', { body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json' })
  console.error('Runtime state on failure:', JSON.stringify(diagnostics))
})

async function prepare(page, request, mode = 'normal', errors) {
  const response = await request.post(`/api/__test/seed?mode=${mode}`)
  expect(response.ok()).toBeTruthy()
  const fixture = await response.json()
  const initialRefresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await initialRefresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await errors?.settle()
  const restoredSession = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto(`/chat?room=${fixture.rooms[0]}`)
  expect((await restoredSession).status()).toBe(200)
  await expect(page.locator('.room-id-copy')).toHaveAttribute('title', fixture.rooms[0])
  await expect(page.locator('.conversation-empty-state')).toBeVisible()
  await expect(page.locator('.composer-fields textarea')).toBeVisible()
  await expect.poll(async () => (
    await (await request.get(`/api/__test/subscription/${fixture.rooms[0]}`)).json()
  ).joined).toBe(true)
  return fixture
}

async function readConversationCalls(request, headers, round) {
  const journal = await request.get('/api/llm-calls', { headers, params: { conversation_round_id: round } })
  expect(journal.ok(), await journal.text()).toBeTruthy()
  return (await journal.json()).filter(call => call.purpose === 'conversation.text')
}

async function send(page, text = 'Vérifie le scénario de streaming') {
  const input = page.locator('.composer-fields textarea')
  await input.fill(text)
  await expect(input).toHaveValue(text)
  expect(await page.evaluate(() => window.isSecureContext)).toBe(true)
  const submitted = performance.now()
  await input.press('Enter')
  // Admission can recover from a concurrent room lock through the real
  // scheduler; its recovery cadence is shortened by the isolated E2E root.
  await expect(page.locator('.message-timeline')).toContainText('Réponse progressive', { timeout: 40_000 })
  await expect(page.locator('.message-timeline')).not.toContainText('terminée.')
  return { submit_to_visible_ms: performance.now() - submitted }
}

async function release(request, room) {
  expect((await request.post(`/api/__test/release/${room}`)).ok()).toBeTruthy()
}

async function final(page) {
  const response = page.locator('.message-row').filter({ hasText: 'Réponse progressive terminée.' })
  await expect(response).toHaveCount(1)
  await expect(response).toHaveAttribute('data-message-id', /.+/)
}

for (const mixed of [false, true]) test(`internal image attachments ${mixed ? 'with a local upload ' : ''}retain their canonical URI and cards after sending and reload`, async ({ page, request }, testInfo) => {
  const errors = collectPageErrors(page)
  const fixture = await prepare(page, request, 'normal', errors)
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=', 'base64')
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` }
  const upload = await request.post(`/api/file-share/files?agent_id=${fixture.agent_id}`, {
    headers, multipart: { upload: { name: 'Synthetic attachment.png', mimeType: 'image/png', buffer: png } },
  })
  expect(upload.ok(), await upload.text()).toBeTruthy()
  const resource = await upload.json()
  expect(resource.uri).toMatch(/^file:\/\//)
  let releaseThumbnail
  if (!mixed) await page.route('**/api/file-share/browser/thumbnail?*', async route => {
    const response = await route.fetch()
    await new Promise(resolve => { releaseThumbnail = resolve })
    await route.fulfill({ response })
  })
  await page.getByRole('button', { name: /^(Ajouter une PJ interne|Add an internal attachment)$/ }).click()
  await page.locator('.file-scheme-uri').filter({ hasText: /^file:\/\/$/ }).click()
  const tile = page.getByRole('button', { name: /^(Select|Sélectionner) Synthetic attachment.png$/ })
  if (!mixed) {
    await expect.poll(() => Boolean(releaseThumbnail)).toBe(true)
    const box = await tile.boundingBox()
    expect(box).not.toBeNull()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    releaseThumbnail()
    await expect(tile.locator('img')).toHaveJSProperty('naturalWidth', 1)
    await page.mouse.up()
  } else await tile.click()
  await expect(tile).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('dialog').getByRole('button', { name: /^(Select|Sélectionner)$/ }).click()
  if (mixed) {
    await page.locator('input[type=file]').setInputFiles({
      name: 'Synthetic local image.png', mimeType: 'image/png', buffer: png,
    })
  }
  const input = page.locator('.composer-fields textarea')
  await expect(input).toHaveValue('')
  await expect(page.getByRole('button', { name: /^(Remove|Retirer) Synthetic attachment.png$/ })).toBeVisible()
  const publication = page.waitForResponse(response => response.request().method() === 'POST'
    && [`/api/chat/rooms/${fixture.rooms[0]}/messages`, `/api/chat/rooms/${fixture.rooms[0]}/attachments`]
      .includes(new URL(response.url()).pathname))
  await input.press('Enter')
  const response = await publication
  expect(response.ok(), await response.text()).toBeTruthy()
  const message = await response.json()
  expect(message.text).toBe('')
  expect(message.resource_uris).toEqual([resource.uri])
  expect(message.files.map(file => file.name)).toEqual(mixed ? ['Synthetic local image.png'] : [])
  const row = page.locator(`[data-message-id="${message.id}"]`)
  const image = row.getByRole('img', { name: 'Synthetic attachment.png', exact: true })
  await expect(image).toBeVisible()
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  const localImage = row.getByRole('img', { name: 'Synthetic local image.png', exact: true })
  if (mixed) {
    await expect(localImage).toBeVisible()
    await expect(localImage).toHaveJSProperty('naturalWidth', 1)
  }
  await release(request, fixture.rooms[0])
  await final(page)
  await errors.settle()
  await page.reload()
  await expect(image).toBeVisible()
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  if (mixed) {
    await expect(localImage).toBeVisible()
    await expect(localImage).toHaveJSProperty('naturalWidth', 1)
  }
  await page.screenshot({ path: testInfo.outputPath('internal-image-attachment.png') })
  await errors.settle()
  expect(errors()).toEqual([])
})

test('an internal task attachment opens its usual modal after sending and reload', async ({ page, request }, testInfo) => {
  const errors = collectPageErrors(page)
  const fixture = await prepare(page, request, 'normal', errors)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}`,
    'X-Editorial-Profile-Version': '1' }
  const created = await request.post('/api/tasks', { headers, data: {
    label: 'Synthetic attached task', objective: '<p>Full objective from the attached task</p>',
    agent_id: fixture.agent_id, status: 'SUCCESS',
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const task = await created.json()
  const sent = await request.post(`/api/chat/rooms/${fixture.rooms[0]}/messages`, { headers, data: {
    client_message_id: crypto.randomUUID(), text: '', resource_uris: [`galaris://task/${task.id}`],
  } })
  expect(sent.ok(), await sent.text()).toBeTruthy()
  const message = await sent.json()
  const preview = page.locator(`[data-message-id="${message.id}"] .resource-preview-main`)
  for (const reload of [false, true]) {
    if (reload) { await errors.settle(); await page.reload() }
    await preview.click()
    await expect(page.getByRole('dialog').locator('.task-detail')).toContainText('Full objective from the attached task')
    await page.screenshot({ path: testInfo.outputPath(`attached-task-${reload ? 'reopened' : 'sent'}.png`), animations: 'disabled' })
    await page.getByRole('dialog').getByRole('button', { name: /^(Close|Fermer)$/, exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await release(request, fixture.rooms[0])
  await errors.settle()
  expect(errors()).toEqual([])
})

test('autosave outages never hold local text and file publication', async ({ page, request }, testInfo) => {
  const errors = collectPageErrors(page)
  const fixture = await prepare(page, request, 'normal', errors)
  let attempts = 0
  await page.route('**/api/chat/rooms/*/draft', route => {
    if (route.request().method() === 'GET') return route.continue()
    attempts += 1
    return route.fulfill({ status: 503, json: { detail: 'Synthetic autosave outage' } })
  })
  await page.route('**/api/chat/rooms/*/draft/files/*', route => {
    attempts += 1
    return route.fulfill({ status: 503, json: { detail: 'Synthetic autosave outage' } })
  })
  await page.locator('.composer-fields textarea').fill('Synthetic locally preserved message')
  await page.locator('.composer-shell input[type=file]').setInputFiles({
    name: 'local-draft.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic local attachment bytes'),
  })
  await expect.poll(() => attempts).toBeGreaterThan(0)
  const receipt = page.waitForResponse(response => response.url().endsWith(`/api/chat/rooms/${fixture.rooms[0]}/attachments`)
    && response.request().method() === 'POST')
  await send(page, 'Synthetic locally preserved message')
  const published = await receipt
  expect(published.status(), await published.text()).toBe(201)
  const message = await published.json()
  expect(message.text).toBe('Synthetic locally preserved message')
  expect(message.files).toHaveLength(1)
  expect(message.files[0].name).toBe('local-draft.txt')
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` }
  const bytes = await request.get(`/api/chat/rooms/${fixture.rooms[0]}/files/${message.files[0].id}`, { headers })
  expect((await bytes.body()).toString()).toBe('Synthetic local attachment bytes')
  await expect(page.locator('.composer-fields textarea')).toHaveValue('')
  await expect(page.locator('.conversation-error')).toHaveCount(0)
  await release(request, fixture.rooms[0])
  await final(page)
  await errors.settle()
  expect(errors()).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('local-send-during-autosave-outage.png'), fullPage: true })
})

test('progress is visible before completion and survives durable handoff and reload', async ({ page, request }, testInfo) => {
  const started = performance.now()
  const fixture = await prepare(page, request)
  const prepareMs = performance.now() - started
  const timing = await send(page)
  await page.evaluate(() => {
    window.handoffViolations = []
    const timeline = document.querySelector('.message-timeline')
    window.handoffObserver = new MutationObserver(() => {
      const count = [...timeline.querySelectorAll('.message-row')]
        .filter(row => row.textContent.includes('Réponse progressive')).length
      if (count !== 1) window.handoffViolations.push(count)
    })
    window.handoffObserver.observe(timeline, { childList: true, subtree: true, characterData: true })
  })
  const released = performance.now()
  await release(request, fixture.rooms[0])
  await final(page)
  const completionMs = performance.now() - released
  const resources = await page.evaluate(() => {
    const totals = {}
    for (const entry of performance.getEntriesByType('resource')) {
      const path = new URL(entry.name).pathname
      const kind = path.startsWith('/api/') ? 'api' : /\.(?:woff2?|ttf|otf)$/.test(path) ? 'fonts'
        : path.endsWith('.js') ? 'js' : path.endsWith('.css') ? 'css' : 'other'
      const group = totals[kind] ??= { requests: 0, transfer_bytes: 0, decoded_bytes: 0 }
      group.requests++
      group.transfer_bytes += entry.transferSize
      group.decoded_bytes += entry.decodedBodySize
    }
    return totals
  })
  await testInfo.attach('chat-journey-performance', { body: JSON.stringify({
    prepare_ms: prepareMs, ...timing, release_to_durable_message_ms: completionMs, resources,
    note: 'Local synthetic runtime; preparation includes login; resources cover the current chat navigation. Service worker blocked, provider completion released explicitly. Not a remote model latency measurement.',
  }), contentType: 'application/json' })
  expect(await page.evaluate(() => {
    window.handoffObserver.disconnect()
    return window.handoffViolations
  })).toEqual([])
  await page.reload()
  await final(page)
})

for (const [mode, driver] of embeddedConversationDrivers) test(
  `human controls pause and resume, then stopping allows a new request (${mode})`, async ({ page, request }) => {
  test.setTimeout(90_000)
  const fixture = await prepare(page, request, mode)
  const [room, otherRoom] = fixture.rooms
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` }
  const readRounds = async () => (await request.get(`/api/__test/rounds/${room}`)).json()
  const readCalls = id => readConversationCalls(request, headers, id)
  try {
    await send(page)
    const [{ id: roundId }] = await readRounds()
    const controlPath = `/api/chat/rooms/${room}/activity/${roundId}/control`
    const stop = (path, expected_attempt, authorization) => request.post(path, {
      headers: authorization, data: { action: 'stop', expected_attempt },
    })
    expect((await stop(controlPath, 1)).status()).toBe(401)
    expect((await stop(`/api/chat/rooms/${otherRoom}/activity/${roundId}/control`, 1, headers)).status()).toBe(404)
    expect((await stop(controlPath, 0, headers)).status()).toBe(409)

    await page.getByRole('button', { name: 'Mettre en pause', exact: true }).click()
    await expect(page.getByText('Réponse en pause', { exact: true })).toBeVisible()
    await expect.poll(async () => (await readCalls(roundId)).map(call => call.status)).toEqual(['cancelled'])
    await page.reload()
    await expect(page.getByText('Réponse en pause', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Reprendre la réponse', exact: true }).click()
    await expect.poll(async () => (await readCalls(roundId)).map(call => call.status).sort()).toEqual(['cancelled', 'running'])
    await expect(page.locator('.message-timeline')).toContainText('Réponse progressive')
    await page.getByRole('button', { name: 'Arrêter la réponse', exact: true }).click()
    await expect(page.locator('.message-bubble--live')).toHaveCount(0)
    await expect.poll(async () => (await readRounds()).find(round => round.id === roundId)?.status).toBe('CANCELLED')
    await expect.poll(async () => (await readCalls(roundId)).map(call => call.status)).toEqual(['cancelled', 'cancelled'])
    const cancelled = await readCalls(roundId)
    expect(new Set(cancelled.map(call => call.id)).size).toBe(2)
    if (driver === 'claude_embedded') {
      const references = cancelled.map(call => call.correlation_ref)
      expect(new Set(references).size).toBe(2)
      for (const reference of references) expect(reference).toMatch(new RegExp(`^round:${roundId}:attempt:[0-9a-f-]+$`))
    }
    await expect(page.locator('.message-row')).toHaveCount(1)
    await page.reload()
    await expect(page.locator('.composer-fields textarea')).toBeVisible()
    await expect(page.locator('.message-row')).toHaveCount(1)
    await expect(page.getByText('Réponse arrêtée', { exact: true })).toHaveCount(0)

    await send(page, 'Vérifie la nouvelle demande synthétique')
    await release(request, room)
    await final(page)
    await page.reload()
    await final(page)
    const rounds = await readRounds()
    expect(rounds.filter(round => round.status === 'CANCELLED')).toHaveLength(1)
    const successful = rounds.filter(round => round.status === 'SUCCEEDED')
    expect(successful).toHaveLength(1)
    const completed = await readCalls(successful[0].id)
    expect(completed).toHaveLength(1)
    expect(completed[0]).toMatchObject({ status: 'completed', conversation_round_id: successful[0].id,
      agent_run_id: successful[0].id, agent_id: fixture.agent_id, llm_id: fixture.model_id })
    expect(cancelled.map(call => call.id)).not.toContain(completed[0].id)
  } finally {
    await release(request, room)
  }
})

test('a second tab opened during execution catches up without duplicate messages', async ({ page, context, request }) => {
  const fixture = await prepare(page, request)
  await send(page)
  const second = await context.newPage()
  await second.goto(`/chat?room=${fixture.rooms[0]}`)
  await expect(second.locator('.composer-fields textarea')).toBeVisible()
  await expect(second.locator('.message-timeline')).toContainText('Réponse progressive')
  await expect(second.locator('.message-timeline')).not.toContainText('terminée.')
  await second.reload()
  await expect(second.locator('.message-timeline')).toContainText('Réponse progressive')
  await expect(second.locator('.message-timeline')).not.toContainText('terminée.')
  await release(request, fixture.rooms[0])
  await final(page)
  await final(second)
  await second.close()
})

test('mobile viewport preserves the response through reload', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const fixture = await prepare(page, request)
  await send(page)
  await release(request, fixture.rooms[0])
  await final(page)
  await page.reload()
  await final(page)
})

test('conversation admission runs a real durable Task and delivers its result once', async ({ page, request }) => {
  test.setTimeout(90_000)
  const fixture = await prepare(page, request, 'task')
  const temporaryReads = []
  page.on('request', request => {
    const url = new URL(request.url())
    if ((url.searchParams.get('from_message_id') ?? '').startsWith('pending:')
      || decodeURIComponent(url.pathname).includes('/messages/pending:')) temporaryReads.push(url.pathname)
  })
  await send(page, 'Vérifie le scénario de streaming document://00000000-0000-4000-8000-000000000399')
  await release(request, fixture.rooms[0])
  const result = page.locator('.message-row').filter({ hasText: 'Résultat durable de la tâche.' })
  await expect(result).toHaveCount(1, { timeout: 40_000 })
  await expect(result).toHaveAttribute('data-message-id', /.+/)
  await page.reload()
  await expect(page.locator('.message-row').filter({ hasText: 'Résultat durable de la tâche.' })).toHaveCount(1)
  expect(temporaryReads).toEqual([])
})

test('a silence warning interrupts a real model call and continues the same durable Task', async ({ page, request }) => {
  test.setTimeout(90_000)
  const fixture = await prepare(page, request, 'call-recovery')
  await send(page)
  await release(request, fixture.rooms[0])
  const state = async () => (await request.get(`/api/__test/call-recovery/${fixture.agent_id}`)).json()
  await expect.poll(async () => (await state()).calls, { timeout: 40_000 }).toBe(1)
  const initial = await state()
  const taskId = initial.task_id
  await expect(page.locator('.agent-task-row')).toContainText('En cours')
  await page.clock.install()
  await page.clock.setSystemTime(new Date(Date.now() + 130_000))
  await page.clock.fastForward(1_000)
  const warning = page.getByRole('alert').filter({ hasText: /Aucune activité reçue|No activity received/ })
  await expect(warning).toBeVisible()
  await page.screenshot({ path: '/artifacts/call-recovery-warning.png' })
  const command = page.waitForResponse(response => response.url().endsWith(`/api/tasks/${taskId}/recover-call`))
  await warning.getByRole('button', { name: /Interrompre l’appel et reprendre|Interrupt call and resume/ }).click()
  expect((await command).ok()).toBeTruthy()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect.poll(async () => {
    const current = await state()
    return current.status === 'SUCCESS' ? 'SUCCESS' : current
  }, { timeout: 35_000 }).toBe('SUCCESS')
  expect(await state()).toMatchObject({ calls: 2, closed: true, guided: true, task_id: taskId,
    status: 'SUCCESS', attempts: initial.attempts, cancel_requested: false })
  await page.reload()
  const row = page.locator('.agent-task-row')
  await row.locator('.agent-task-expansion-toggle').click()
  await expect(row).toContainText('Synthetic guided recovery completed.')
  await page.screenshot({ path: '/artifacts/call-recovery-completed.png' })
})

test('tool progress and final text survive persistence', async ({ page, request }) => {
  const fixture = await prepare(page, request, 'tools')
  await send(page)
  await release(request, fixture.rooms[0])
  await final(page)
  await page.reload()
  await final(page)
  // The durable activity API must retain the tool, not just the final text.
  const result = await page.evaluate(async room => {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/chat/rooms/${room}/activity`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return response.json()
  }, fixture.rooms[0])
  expect(JSON.stringify(result)).toContain('fixture_lookup')
})

test('Task tool details remain inspectable live, after reload and after completion', async ({ page, request }) => {
  test.setTimeout(120_000)
  const errors = collectPageErrors(page)
  const fixture = await prepare(page, request, 'task-tools', errors)
  await send(page)
  await release(request, fixture.rooms[0])
  const row = page.locator('.agent-task-row')
  const inspect = async () => {
    await expect(row).toHaveCount(1, { timeout: 40_000 })
    await row.locator('.agent-task-status-dot').click()
    const dialog = page.getByRole('dialog')
    const tool = dialog.getByRole('button', { name: /fixture_denied/ })
    await expect(tool).toHaveCount(1)
    if (await tool.getAttribute('aria-expanded') !== 'true') await tool.click()
    const detail = dialog.locator('.timeline-item').filter({ has: page.getByRole('button', { name: /fixture_denied/ }) })
    await expect(tool).toContainText('Échec')
    await expect(detail.getByRole('cell', { name: 'Synthetic Task query', exact: true })).toBeVisible()
    await expect(detail.getByRole('region', { name: 'Contenu retourné', exact: true })).toContainText('Synthetic denial')
    await expect(detail.getByRole('cell', { name: '[REDACTED]', exact: true })).toBeVisible()
    await expect(dialog).not.toContainText('synthetic-task-secret')
  }
  try {
    await inspect()
    await errors.settle()
    await page.reload()
    await inspect()
    expect((await request.post(`/api/__test/task-tools/${fixture.agent_id}/release`)).ok()).toBeTruthy()
    await expect(page.getByRole('dialog')).toContainText('Résultat durable de la tâche.', { timeout: 40_000 })
    await page.reload()
    await inspect()
    await page.screenshot({ path: '/artifacts/task-tool-details.png' })
  } finally {
    await request.post(`/api/__test/task-tools/${fixture.agent_id}/release`)
  }
  expect(errors()).toEqual([])
})

for (const [mode, driver] of embeddedConversationDrivers) {
  test(`reconnection catches up when completion happened offline (${mode})`, async ({ page, context, request }) => {
    test.setTimeout(90_000)
    const errors = collectPageErrors(page)
    const fixture = await prepare(page, request, mode, errors)
    const room = fixture.rooms[0]
    const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` }
    let offline = false
    try {
      await send(page)
      await context.setOffline(true)
      offline = true
      await release(request, room)
      let round
      await expect.poll(async () => {
        round = (await (await request.get(`/api/__test/rounds/${room}`)).json())[0]
        return round?.status
      }).toBe('SUCCEEDED')
      await context.setOffline(false)
      offline = false
      await final(page)
      await page.reload()
      await final(page)
      const response = await request.get(`/api/conversations/rounds/${round.id}`, { headers })
      expect(response.ok(), await response.text()).toBeTruthy()
      const detail = await response.json()
      expect(detail.execution_result.metadata).toMatchObject({ driver_code: driver, run_id: round.id })

      const journal = page.waitForResponse(response => {
        const url = new URL(response.url())
        return url.pathname === '/api/llm-calls' && url.searchParams.get('conversation_round_id') === round.id
      }, { timeout: 15_000 })
      const trace = page.locator('.execution-trace').filter({ has: page.getByRole('button', { name: 'Détails', exact: true }) })
      await trace.getByRole('button', { name: 'Détails', exact: true }).click()
      const callResponse = await journal
      expect(callResponse.ok(), await callResponse.text()).toBeTruthy()
      const [primary, ...extra] = (await callResponse.json()).filter(call => call.purpose === 'conversation.text')
      expect(extra).toHaveLength(0)
      expect(primary).toMatchObject({ conversation_round_id: round.id, agent_run_id: round.id,
        agent_id: fixture.agent_id, llm_id: fixture.model_id, total_tokens: 16,
        upstream_request_id: expect.stringMatching(/^chatcmpl-browser-/) })
      if (driver === 'claude_embedded') {
        expect(primary.correlation_ref).toMatch(new RegExp(`^round:${round.id}:attempt:[0-9a-f-]+$`))
      }
      expect(primary.cost).toBeGreaterThan(0)
      expect(detail.execution_result.cost).toBeCloseTo(primary.cost, 8)
      await trace.getByRole('tab', { name: 'Détails', exact: true }).click()
      await expect(trace.getByRole('region', { name: 'Consommation enregistrée' })).toContainText('16 tokens')
    } finally {
      if (offline && !page.isClosed()) await context.setOffline(false)
    }
    await errors.settle()
    expect(errors()).toEqual([])
  })
}

test('delegated chat delivers another account’s messages only while its view is open', async ({ page, request }) => {
  const other = await (await request.post('/api/__test/seed?mode=load-dialogue')).json()
  const received = new Map()
  page.on('websocket', socket => socket.on('framereceived', ({ payload }) => {
    const frame = String(payload)
    if (!frame.startsWith('42[')) return
    const [name, event] = JSON.parse(frame.slice(2))
    if (name === 'chat.message' || name === 'chat.personal_message') received.set(event.data.message_id, name)
  }))
  const own = await prepare(page, request, 'load-dialogue')
  const selfToken = await page.evaluate(() => localStorage.getItem('access_token'))
  const agents = await (await request.get('/api/chat/viewer-agents', { headers: { Authorization: 'Bearer ' + selfToken } })).json()
  const label = agents.find(agent => agent.agent_id === other.agent_id).display_name
  const { access_token: otherToken } = await (await request.post('/api/auth/login-json', {
    data: { email: other.email, password: other.password },
  })).json()
  async function post(room, token) {
    const response = await request.post('/api/chat/rooms/' + room + '/messages', {
      headers: { Authorization: 'Bearer ' + token },
      data: { client_message_id: crypto.randomUUID(), text: 'Message synthétique de vérification.' },
    })
    expect(response.ok()).toBe(true)
    return (await response.json()).id
  }
  async function view(person) {
    const viewer = page.locator('.viewer-select')
    if (!await viewer.isVisible()) await page.getByRole('button', { name: 'Options d’affichage des conversations', exact: true }).click()
    await viewer.getByRole('combobox').click()
    await page.getByRole('option').filter({ has: page.getByText(person, { exact: true }) }).click()
    await expect(viewer).toContainText(person)
    await expect.poll(async () => (await (await request.get('/api/__test/subscription/' + own.rooms[0])).json()).delegated_users)
      .toBe(person === 'Moi' ? 0 : 1)
  }
  await view(label)
  const delegated = await post(other.rooms[0], otherToken)
  await expect.poll(() => received.get(delegated)).toBe('chat.message')
  await view('Moi')
  const unrelated = await post(other.rooms[0], otherToken)
  const personal = await post(own.rooms[0], selfToken)
  await expect.poll(() => received.get(personal)).toBe('chat.personal_message')
  expect(received.has(unrelated)).toBe(false)
})

test('leaving chat stops live stream packets but retains the final message notification', async ({ page, request }) => {
  let subscriptions = []
  const received = []
  page.on('websocket', socket => {
    socket.on('framesent', ({ payload }) => {
      const frame = String(payload)
      if (!frame.startsWith('42')) return
      const [event, data] = JSON.parse(frame.slice(2))
      if (event === 'events.subscribe') subscriptions = data.events
    })
    socket.on('framereceived', ({ payload }) => {
      const frame = String(payload)
      if (frame.startsWith('42')) received.push(JSON.parse(frame.slice(2))[0])
    })
  })
  const fixture = await prepare(page, request)
  await send(page)
  await page.locator('a[href="/params"]').first().click()
  await expect.poll(() => subscriptions).toEqual(['chat.personal_message', 'chat.scope_changed'])
  received.length = 0
  await release(request, fixture.rooms[0])
  await expect.poll(() => received).toContain('chat.personal_message')
  expect(received).not.toContain('chat.runtime')
  expect(received).not.toContain('chat.activity')
  await page.goto(`/chat?room=${fixture.rooms[0]}`)
  await final(page)
})

test('a lost terminal event converges through the durable HTTP projection', async ({ page, request }) => {
  const fixture = await prepare(page, request, 'missing-terminal')
  await send(page)
  await release(request, fixture.rooms[0])
  await final(page)
  await page.reload()
  await final(page)
})

test('failed HTTP projections are retried after the final socket event, without another event', async ({ page, request }) => {
  const fixture = await prepare(page, request)
  await send(page)
  const projection = `**/api/chat/rooms/${fixture.rooms[0]}/**`
  await page.route(projection, route => route.abort('internetdisconnected'))
  await release(request, fixture.rooms[0])
  await expect(page.locator('.message-timeline')).toContainText('Réponse progressive terminée.')
  await expect.poll(async () => (await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json())[0]?.status).toBe('SUCCEEDED')
  await page.unroute(projection)
  await final(page)
  await page.reload()
  await final(page)
})

test('switching rooms isolates live content and preserves the finished response', async ({ page, request }) => {
  const errors = collectPageErrors(page)
  const fixture = await prepare(page, request, 'normal', errors)
  await send(page)
  const otherRoom = page.locator('.conversation-list .room-item:not([aria-current="true"])')
  await expect(otherRoom).toHaveCount(1)
  await otherRoom.click()
  await expect(page).toHaveURL(new RegExp(`/chat\\?room=${fixture.rooms[1]}$`))
  await expect(page.locator('.composer-fields textarea')).toBeVisible()
  await release(request, fixture.rooms[0])
  await expect.poll(async () => (await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json())[0]?.status).toBe('SUCCEEDED')
  await expect(page.locator('.message-timeline')).not.toContainText('Réponse progressive')
  await page.goBack()
  await expect(page.locator('.room-id-copy')).toHaveAttribute('title', fixture.rooms[0])
  await final(page)
  await page.goForward()
  await expect(page.locator('.room-id-copy')).toHaveAttribute('title', fixture.rooms[1])
  await expect(page.locator('.message-timeline')).not.toContainText('Réponse progressive')
  await page.locator('.conversation-list .room-item[aria-current="true"]').click()
  await page.goBack()
  await expect(page.locator('.room-id-copy')).toHaveAttribute('title', fixture.rooms[0])
  await final(page)
  expect(errors()).toEqual([])
})

test('partial provider failure reaches a durable error and leaves the composer usable', async ({ page, request }) => {
  const fixture = await prepare(page, request, 'error')
  await send(page)
  await release(request, fixture.rooms[0])
  await expect.poll(async () => (await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json())[0]?.status).toBe('ERROR_RESOLVED')
  await expect(page.locator('.message-timeline')).toContainText('fixture provider interrupted')
  await expect(page.locator('.composer-fields textarea')).toBeEnabled()
})

for (const [mode] of embeddedConversationDrivers) {
  for (const previousState of ['active', 'paused']) {
    test(`a correction replaces the ${previousState} round and delivers one reply (${mode})`, async ({ page, context, request }) => {
      test.setTimeout(90_000)
      const fixture = await prepare(page, request, mode)
      const [room] = fixture.rooms
      const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` }
      const readRounds = async () => (await request.get(`/api/__test/rounds/${room}`)).json()
      let offline = false
      try {
        await send(page)
        const [{ id: originalRound }] = await readRounds()
        if (previousState === 'paused') {
          await page.getByRole('button', { name: 'Mettre en pause', exact: true }).click()
          await expect(page.getByText('Réponse en pause', { exact: true })).toBeVisible()
          await page.reload()
          await expect(page.getByText('Réponse en pause', { exact: true })).toBeVisible()
        }

        const correction = 'Complète la demande avec cette précision'
        const composer = page.locator('.composer-fields textarea')
        await composer.fill(correction)
        await composer.press('Enter')
        await expect.poll(async () => {
          const rounds = await readRounds()
          return rounds.map(round => round.status).sort()
        }).toEqual(['RUNNING', 'SUPERSEDED'])
        const replacement = (await readRounds()).find(round => round.id !== originalRound)
        await expect.poll(async () => (await readConversationCalls(request, headers, originalRound)).map(call => call.status))
          .toEqual(['cancelled'])
        await expect(page.locator('.message-row').filter({ hasText: 'Réponse progressive' })).toHaveCount(1)

        await context.setOffline(true)
        offline = true
        await release(request, room)
        await expect.poll(async () => {
          const rounds = await readRounds()
          return rounds.map(round => round.status).sort()
        }).toEqual(['SUCCEEDED', 'SUPERSEDED'])
        await context.setOffline(false)
        offline = false
        await final(page)
        await page.reload()
        await final(page)
        await expect(page.locator('.message-row').filter({ hasText: 'Vérifie le scénario de streaming' })).toHaveCount(1)
        await expect(page.locator('.message-row').filter({ hasText: correction })).toHaveCount(1)

        const originalCalls = await readConversationCalls(request, headers, originalRound)
        const replacementCalls = await readConversationCalls(request, headers, replacement.id)
        expect(originalCalls).toHaveLength(1)
        expect(replacementCalls).toHaveLength(1)
        expect(originalCalls[0]).toMatchObject({ status: 'cancelled', agent_run_id: originalRound, conversation_round_id: originalRound })
        expect(replacementCalls[0]).toMatchObject({ status: 'completed', agent_run_id: replacement.id, conversation_round_id: replacement.id })
        expect(replacementCalls[0].id).not.toBe(originalCalls[0].id)
      } finally {
        if (offline && !page.isClosed()) await context.setOffline(false)
        await release(request, room)
      }
    })
  }
}
