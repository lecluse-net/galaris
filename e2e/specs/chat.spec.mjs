import { test, expect } from '@playwright/test'

const socketEvents = new WeakMap()
test.beforeEach(async ({ page }) => {
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

async function prepare(page, request, mode = 'normal') {
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

async function send(page) {
  const input = page.locator('.composer-fields textarea')
  await input.fill('Vérifie le scénario de streaming')
  await expect(input).toHaveValue('Vérifie le scénario de streaming')
  expect(await page.evaluate(() => window.isSecureContext)).toBe(true)
  await input.press('Enter')
  await expect(page.locator('.message-timeline')).toContainText('Réponse progressive')
  await expect(page.locator('.message-timeline')).not.toContainText('terminée.')
}

async function release(request, room) {
  expect((await request.post(`/api/__test/release/${room}`)).ok()).toBeTruthy()
}

async function final(page) {
  const response = page.locator('.message-row').filter({ hasText: 'Réponse progressive terminée.' })
  await expect(response).toHaveCount(1)
  await expect(response).toHaveAttribute('data-message-id', /.+/)
}

test('progress is visible before completion and survives durable handoff and reload', async ({ page, request }) => {
  const fixture = await prepare(page, request)
  await send(page)
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
  await release(request, fixture.rooms[0])
  await final(page)
  expect(await page.evaluate(() => {
    window.handoffObserver.disconnect()
    return window.handoffViolations
  })).toEqual([])
  await page.reload()
  await final(page)
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
  const fixture = await prepare(page, request, 'task')
  await send(page)
  await release(request, fixture.rooms[0])
  const result = page.locator('.message-row').filter({ hasText: 'Résultat durable de la tâche.' })
  await expect(result).toHaveCount(1, { timeout: 40_000 })
  await expect(result).toHaveAttribute('data-message-id', /.+/)
  await page.reload()
  await expect(page.locator('.message-row').filter({ hasText: 'Résultat durable de la tâche.' })).toHaveCount(1)
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

test('reconnection catches up when completion happened offline', async ({ page, context, request }) => {
  const fixture = await prepare(page, request)
  await send(page)
  await context.setOffline(true)
  await release(request, fixture.rooms[0])
  await expect.poll(async () => (await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json())[0]?.status).toBe('SUCCEEDED')
  await context.setOffline(false)
  await final(page)
  await page.reload()
  await final(page)
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
  await expect.poll(() => subscriptions).toEqual(['chat.message'])
  received.length = 0
  await release(request, fixture.rooms[0])
  await expect.poll(() => received).toContain('chat.message')
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
  const fixture = await prepare(page, request)
  await send(page)
  await page.goto(`/chat?room=${fixture.rooms[1]}`)
  await expect(page.locator('.composer-fields textarea')).toBeVisible()
  await release(request, fixture.rooms[0])
  await expect.poll(async () => (await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json())[0]?.status).toBe('SUCCEEDED')
  await expect(page.locator('.message-timeline')).not.toContainText('Réponse progressive')
  await page.goto(`/chat?room=${fixture.rooms[0]}`)
  await final(page)
})

test('partial provider failure reaches a durable error and leaves the composer usable', async ({ page, request }) => {
  const fixture = await prepare(page, request, 'error')
  await send(page)
  await release(request, fixture.rooms[0])
  await expect.poll(async () => (await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json())[0]?.status).toBe('ERROR_RESOLVED')
  await expect(page.locator('.message-timeline')).toContainText('fixture provider interrupted')
  await expect(page.locator('.composer-fields textarea')).toBeEnabled()
})

test('a correction supersedes the active round and survives offline completion without duplicate delivery', async ({ page, context, request }) => {
  const fixture = await prepare(page, request, 'interruptible')
  await send(page)
  const composer = page.locator('.composer-fields textarea')
  await composer.fill('Complète la demande avec cette précision')
  await composer.press('Enter')
  await expect.poll(async () => {
    const rounds = await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json()
    return rounds.map(round => round.status).sort()
  }).toEqual(['RUNNING', 'SUPERSEDED'])
  await expect(page.locator('.message-row').filter({ hasText: 'Réponse progressive' })).toHaveCount(1)
  await context.setOffline(true)
  await release(request, fixture.rooms[0])
  await expect.poll(async () => {
    const rounds = await (await request.get(`/api/__test/rounds/${fixture.rooms[0]}`)).json()
    return rounds.map(round => round.status).sort()
  }).toEqual(['SUCCEEDED', 'SUPERSEDED'])
  await context.setOffline(false)
  await final(page)
  await page.reload()
  await final(page)
  await expect(page.locator('.message-row').filter({ hasText: 'Vérifie le scénario de streaming' })).toHaveCount(1)
  await expect(page.locator('.message-row').filter({ hasText: 'Complète la demande avec cette précision' })).toHaveCount(1)
})
