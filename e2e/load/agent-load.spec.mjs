import { randomUUID } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { test, expect } from '@playwright/test'
import { createDocument } from '../documents.mjs'
import { notificationPrompt } from '../notification-prompt.mjs'

const duration = 90_000
const observationTimeout = 120_000
const roles = ['dialogue', 'mission', 'document', 'stop']
const modes = { dialogue: 'load-dialogue', mission: 'task', document: 'normal', stop: 'conversation-control' }

async function json(response) {
  try {
    if (!response.ok()) throw new Error(`${response.status()} ${new URL(response.url()).pathname}: ${(await response.text()).slice(0, 400)}`)
    return await response.json()
  } finally {
    await response.dispose()
  }
}

async function prepare(request, role) {
  const fixture = await json(await request.post('/api/__test/seed?mode=' + modes[role]))
  const { access_token } = await json(await request.post('/api/auth/login-json', {
    data: { email: fixture.email, password: fixture.password },
  }))
  const headers = { Authorization: 'Bearer ' + access_token, 'X-Editorial-Profile-Version': '1' }
  const room = fixture.rooms[0]
  let documentId
  if (role === 'document') {
    const doc = await json(await createDocument(request, { headers, data: {
      owner_agent_id: fixture.agent_id, title: 'Synthetic load document', payload: { text: '<p>Load sample</p>' },
    } }))
    documentId = doc.id
  }
  if (role === 'mission') await json(await request.post('/api/__test/release/' + room))
  return { ...fixture, role, headers, room, documentId, seen: new Set() }
}

async function waitRound(request, actor, find) {
  const until = performance.now() + observationTimeout
  let rows
  do {
    rows = await json(await request.get('/api/__test/rounds/' + actor.room))
    const round = rows.find(find)
    if (round) return round
    if (rows.some(row => row.status === 'ERROR')) throw new Error('Conversation failed: ' + actor.role)
    await delay(350)
  } while (performance.now() < until)
  throw new Error('Round timed out: ' + actor.role + ' ' + JSON.stringify(rows.map(row => row.status)))
}

async function exercise(request, actor, end, counts, stops, documentReads) {
  do {
    if (actor.role === 'document') {
      const started = performance.now()
      const doc = await json(await request.get('/api/documents/' + actor.documentId, { headers: actor.headers }))
      expect(doc.item.id).toBe(actor.documentId)
      expect(doc.item.payload.text).toContain('Load sample')
      documentReads.push(Math.round(performance.now() - started))
    } else {
      await json(await request.post('/api/chat/rooms/' + actor.room + '/messages', { headers: actor.headers,
        data: { client_message_id: randomUUID(), text: 'Demande synthétique de charge.' } }))
      if (actor.role === 'stop') {
        const active = await waitRound(request, actor, row => !actor.seen.has(row.id) && row.status === 'RUNNING')
        await delay(Math.random() * 900)
        const start = performance.now()
        await json(await request.post(`/api/chat/rooms/${actor.room}/activity/${active.id}/control`, {
          headers: actor.headers, data: { action: 'stop', expected_attempt: 1 },
        }))
        await waitRound(request, actor, row => row.id === active.id && row.status === 'CANCELLED')
        stops.push(Math.round(performance.now() - start))
        actor.seen.add(active.id)
      } else {
        const done = await waitRound(request, actor, row => !actor.seen.has(row.id) && row.status === 'SUCCEEDED')
        actor.seen.add(done.id)
      }
    }
    counts[actor.role]++
    await delay(500)
  } while (performance.now() < end)
}

async function browserProbe(page, end, samples) {
  const input = page.locator('.composer-fields textarea')
  const replies = page.locator('.message-row').filter({ hasText: 'Réponse progressive terminée.' })
  do {
    const previous = await replies.count()
    await input.fill('Sonde de charge ' + previous)
    // Measure in the browser clock, from the real key event to a rendered response.
    await page.evaluate(previous => {
      window.loadFirstTextMs = null
      const timeline = document.querySelector('.message-timeline')
      document.querySelector('.composer-fields textarea').addEventListener('keydown', () => {
        const start = performance.now()
        const observer = new MutationObserver(() => {
          const rows = [...timeline.querySelectorAll('.message-row')]
          if (rows.filter(row => row.textContent.includes('Réponse progressive')).length <= previous) return
          observer.disconnect()
          requestAnimationFrame(() => { window.loadFirstTextMs = performance.now() - start })
        })
        observer.observe(timeline, { childList: true, characterData: true, subtree: true })
      }, { once: true })
    }, previous)
    await input.press('Enter')
    await page.waitForFunction(() => window.loadFirstTextMs !== null, null, { timeout: observationTimeout })
    samples.push(Math.round(await page.evaluate(() => window.loadFirstTextMs)))
    await expect(replies).toHaveCount(previous + 1, { timeout: observationTimeout })
    await expect(replies.last()).toHaveAttribute('data-message-id', /.+/)
    await delay(500)
  } while (performance.now() < end)
}

function p95(samples) {
  return [...samples].sort((a, b) => a - b)[Math.ceil(samples.length * .95) - 1] ?? null
}

for (const users of [30, 50]) test(users + ' authenticated users sustain mixed agent traffic', async ({ playwright, request, browser, baseURL }, info) => {
  const actors = []
  const probes = []
  const inboxPages = []
  const contexts = []
  try {
    for (let i = 0; i < users; i++) {
      const role = roles[i % roles.length]
      if (role === 'dialogue' && probes.length < 3) {
        const owner = await json(await request.post('/api/__test/seed?mode=load-dialogue'))
        const page = await browser.newPage({ baseURL, serviceWorkers: 'block', viewport: { width: 1440, height: 1000 } })
        probes.push({ page, ...owner, room: owner.rooms[0] })
        continue
      }
      const session = await playwright.request.newContext({ baseURL })
      contexts.push(session)
      actors.push({ ...await prepare(session, role), session })
    }
    const traffic = { lists: 0, inbox: 0, other_room_details: 0, selected_messages: 0, other_messages: 0, impersonated_messages: 0 }
    function observe(page, room) {
      page.on('request', request => {
        if (request.method() !== 'GET') return
        const path = new URL(request.url()).pathname
        if (path === '/api/chat/rooms') traffic.lists++
        if (path === '/api/chat/inbox') traffic.inbox++
        if (/^\/api\/chat\/rooms\/[\w-]+$/.test(path) && !path.endsWith('/' + room)) traffic.other_room_details++
      })
      page.on('websocket', socket => socket.on('framereceived', ({ payload }) => {
        const frame = String(payload)
        if (!frame.startsWith('42[')) return
        const [name, message] = JSON.parse(frame.slice(2))
        if (name !== 'chat.message' && name !== 'chat.personal_message') return
        if (message.data.personal_room === false) traffic.impersonated_messages++
        if (message.data.room_id === room) traffic.selected_messages++
        else traffic.other_messages++
      }))
    }
    for (const probe of probes) {
      observe(probe.page, probe.room)
      await openRoom(probe, request)
    }
    // The API workers exercise mixed traffic while their actual browser tabs
    // keep the application's personal inbox mounted outside Chat.
    for (let i = 0; i < actors.length; i += 4) {
      await Promise.all(actors.slice(i, i + 4).map(async actor => {
        const page = await browser.newPage({ baseURL, serviceWorkers: 'block', storageState: {
          cookies: [], origins: [{ origin: new URL(baseURL).origin, localStorage: [
            { name: 'access_token', value: actor.headers.Authorization.slice(7) },
          ] }],
        } })
        inboxPages.push(page)
        observe(page, actor.room)
        await Promise.all([page.waitForResponse(r => new URL(r.url()).pathname === '/api/chat/inbox' && r.ok()), page.goto('/params')])
      }))
    }
    const connected = async () => (await json(await request.get('/api/__test/subscription/' + probes[0].room))).personal_users
    await expect.poll(connected).toBe(users)
    for (const key of Object.keys(traffic)) traffic[key] = 0
    await runLoad({ actors, probes, request, info, users, traffic })
    expect(await connected()).toBe(users)
    expect(traffic.impersonated_messages).toBe(0)
    expect(traffic.selected_messages).toBeGreaterThan(0)
  } finally {
    await Promise.all(inboxPages.map(page => page.close()))
    await Promise.all(probes.map(probe => probe.page.close()))
    await Promise.all(contexts.map(context => context.dispose()))
  }
})

async function openRoom(probe, request) {
  const { page } = probe
  await page.addLocatorHandler(notificationPrompt(page), modal => modal.getByRole('button', { name: 'Plus tard' }).click())
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(probe.email)
  await page.locator('input[type=password]').fill(probe.password)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await page.goto('/chat?room=' + probe.room)
  await expect(page.locator('.room-id-copy')).toHaveAttribute('title', probe.room)
  await expect.poll(async () => (await json(await request.get('/api/__test/subscription/' + probe.room))).joined).toBe(true)
}

async function runLoad({ actors, probes, request, info, users, traffic }) {
  const ids = actors.filter(actor => actor.role === 'mission').map(actor => actor.agent_id)
  const rooms = [...probes, ...actors].map(actor => actor.room)
  const counts = { dialogue: 0, mission: 0, document: 0, stop: 0 }
  const samples = [], stops = [], documentReads = [], queue = []
  const started = performance.now()
  const end = started + duration
  async function sampleQueue() {
    const { tasks: groups, rounds, worker_slots, notifications } = await json(await request.post('/api/__test/load/counts', {
      data: { agent_ids: ids, room_ids: rooms },
    }))
    const pending = Object.entries(groups).filter(([phase]) => !['SUCCESS', 'ERROR'].includes(phase))
    const point = { ms: Math.round(performance.now() - started), pending: pending.reduce((n, [, v]) => n + v, 0),
      worker_slots, notifications, waiting_rounds: rounds.FROZEN ?? 0, success: groups.SUCCESS ?? 0, error: groups.ERROR ?? 0 }
    queue.push(point)
    return point
  }
  async function sampleWindow() {
    do {
      await sampleQueue()
      await delay(1000)
    } while (performance.now() < end)
    return sampleQueue()
  }
  const [windowResult, ...work] = await Promise.allSettled([sampleWindow(), ...probes.map(({ page }) => browserProbe(page, end, samples)),
    ...actors.map(actor => exercise(actor.session, actor, end, counts, stops, documentReads))])
  if (windowResult.status === 'rejected') throw windowResult.reason
  const failures = work.filter(result => result.status === 'rejected').map(result => String(result.reason))
  const last = windowResult.value
  await expect.poll(async () => {
    const point = await sampleQueue()
    const settled = ['DELIVERED', 'SKIPPED', 'UNKNOWN'].reduce((n, state) => n + (point.notifications[state] ?? 0), 0)
    return point.pending === 0 && point.success + point.error >= counts.mission && settled >= counts.mission
  }, { timeout: observationTimeout }).toBe(true)
  const drained = queue.at(-1)
  const { timings, attempts_ms } = await json(await request.post('/api/__test/load/timings', {
    data: { agent_ids: ids, room_ids: rooms, browser_room_ids: probes.map(probe => probe.room) },
  }))
  const report = { users, browser_sessions: users, interactive_chat_probes: probes.length, worker_slots: last.worker_slots,
    durable_p95_ms: Object.fromEntries(Object.entries(timings).map(([name, values]) => [name, p95(values)])),
    attempts: Object.fromEntries(Object.entries(attempts_ms).map(([role, values]) => [
      role, { count: values.length, total_ms: values.reduce((sum, value) => sum + value, 0), p95_ms: p95(values) },
    ])),
    notifications_at_window_end: last.notifications, notifications_after_drain: drained.notifications,
    window_ms: last.ms, counts_including_drain: counts, probe_samples: samples.length,
    first_visible_ms_p95: p95(samples), stop_samples: stops.length, stop_ms_p95: p95(stops),
    first_visible_over_65s: samples.filter(ms => ms > 65_000).length, document_ms_p95: p95(documentReads),
    missions_per_minute: +(60_000 * last.success / last.ms).toFixed(1), backlog_at_window_end: last.pending,
    backlog_peak: Math.max(...queue.map(point => point.pending)), drain_ms: drained.ms - last.ms,
    waiting_rounds_peak: Math.max(...queue.map(point => point.waiting_rounds)),
    waiting_rounds_at_window_end: last.waiting_rounds, completed_after_drain: drained.success, traffic, failures }
  console.log('AGENT_LOAD ' + JSON.stringify(report))
  await info.attach('agent-load', { body: JSON.stringify({ ...report, queue, timings, first_visible_ms: samples, stop_ms: stops, document_ms: documentReads }), contentType: 'application/json' })
  expect(failures).toEqual([])
  expect(drained.error).toBe(0)
  expect(drained.notifications.UNKNOWN ?? 0).toBe(0)
  // The synthetic mission produces a reply and never sends it through a tool.
  expect(drained.notifications.DELIVERED ?? 0).toBe(counts.mission)
  expect(timings.notification).toHaveLength(drained.notifications.DELIVERED ?? 0)
  expect(timings.mission_queue).toHaveLength(counts.mission)
  expect(timings.browser_queue).toHaveLength(samples.length)
  expect(attempts_ms.dialogue.length).toBeGreaterThanOrEqual(counts.dialogue + samples.length)
  expect(attempts_ms.mission.length).toBeGreaterThanOrEqual(counts.mission)
  expect(attempts_ms.stop.length).toBeGreaterThanOrEqual(counts.stop)
  expect(drained.waiting_rounds).toBe(0)
  expect(drained.success).toBe(counts.mission)
  for (const count of [...Object.values(counts), samples.length]) expect(count).toBeGreaterThan(0)
}
