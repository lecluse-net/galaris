import { readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { test, expect } from '@playwright/test'

test.use({ serviceWorkers: 'allow' })

test('a deployed update automatically replaces the cached shell while preserving the authenticated conversation', async ({ page, request }) => {
  const directory = '/pwa-site' // Unique Compose volume, never the source or live deployment.
  const originalHtml = await readFile(`${directory}/index.html`, 'utf8')
  const originalWorker = await readFile(`${directory}/sw.js`, 'utf8')
  for (const path of ['/sw.js', '/registerSW.js', '/index.html']) {
    const response = await request.get(path)
    expect(response.status()).toBe(200)
    expect(response.headers()['cache-control']).toBe('no-cache, no-store, must-revalidate')
  }
  const manifestEntry = /"revision":"[^"]+","url":"index.html"/g
  expect([...originalWorker.matchAll(manifestEntry)]).toHaveLength(1)
  async function deploy(version) {
    const html = originalHtml.replace('</head>', `<meta name="e2e-build" content="${version}"></head>`)
    const revision = createHash('md5').update(html).digest('hex')
    // Like a new build, renew unchanged assets as well as index.html.
    const worker = originalWorker.replace(/"revision":"([^"]+)","url":"([^"]+)"/g,
      (_entry, previous, url) => `"revision":"${version}-${url === 'index.html' ? revision : previous}","url":"${url}"`)
    await writeFile(`${directory}/index.html`, html)
    await writeFile(`${directory}/sw.js`, worker)
  }
  try {
    await deploy('A')
    const fixture = await (await request.post('/api/__test/seed')).json()
    const initialRefresh = page.waitForResponse(r => r.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login')
    await initialRefresh
    await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
    expect(await page.evaluate(() => new URL(navigator.serviceWorker.controller.scriptURL).pathname)).toBe('/sw.js')
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    await page.locator('button[type=submit]').click()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    await page.goto(`/chat?room=${fixture.rooms[0]}`)
    await expect(page.locator('meta[name="e2e-build"]')).toHaveAttribute('content', 'A')
    const composer = page.locator('.composer-fields textarea')
    await expect(composer).toBeVisible()
    await composer.fill('Conversation conservée pendant la mise à jour PWA')
    await composer.press('Enter')
    await expect(page.locator('.message-timeline')).toContainText('Réponse progressive')
    await request.post(`/api/__test/release/${fixture.rooms[0]}`)
    const reply = page.locator('.message-row').filter({ hasText: 'Réponse progressive terminée.' })
    await expect(reply).toHaveAttribute('data-message-id', /.+/)
    const messageId = await reply.getAttribute('data-message-id')
    const otherTab = await page.context().newPage()
    await otherTab.goto(`/chat?room=${fixture.rooms[0]}`)
    await expect(otherTab.locator('meta[name="e2e-build"]')).toHaveAttribute('content', 'A')
    await expect(otherTab.locator('.composer-fields textarea')).toBeVisible()
    await page.bringToFront()
    await expect.poll(() => page.evaluate(() => document.visibilityState)).toBe('visible')
    const cacheKeys = () => page.evaluate(async () => {
      const keys = await Promise.all((await caches.keys()).map(async name => (await (await caches.open(name)).keys()).map(request => request.url)))
      return keys.flat().filter(url => url.includes('__WB_REVISION__'))
    })
    const previousKeys = await cacheKeys()
    expect(previousKeys.length).toBeGreaterThan(0)
    await page.clock.install()
    // Offline clients keep their working shell and session until connectivity returns.
    await page.context().setOffline(true)
    await page.clock.fastForward(60_001)
    await expect(page.locator('meta[name="e2e-build"]')).toHaveAttribute('content', 'A')
    await page.context().setOffline(false)
    // A failed deployment must not destroy the usable cache either.
    await writeFile(`${directory}/sw.js`, 'this is not valid JavaScript')
    await page.clock.fastForward(60_001)
    await expect(page.locator('meta[name="e2e-build"]')).toHaveAttribute('content', 'A')
    const refreshes = []
    // Either tab can renew the shared session; the other reuses its token under
    // the session lock. Observe both before deploying, since either may update first.
    page.context().on('response', response => { if (response.url().endsWith('/api/auth/refresh')) refreshes.push(response.status()) })
    await deploy('B')
    // Registration and worker installation run outside the simulated page clock.
    // Keep advancing periodic checks while those asynchronous browser jobs settle.
    // Never invoke update() or reload() from the test: the app must recover itself.
    await expect.poll(async () => {
      await page.clock.fastForward(60_001)
      return page.locator('meta[name="e2e-build"]').getAttribute('content')
    }).toBe('B')
    await expect.poll(() => refreshes).toContain(200)
    await expect(reply).toHaveCount(1)
    await expect(reply).toHaveAttribute('data-message-id', messageId)
    await expect(composer).toBeVisible()
    await expect(otherTab.locator('meta[name="e2e-build"]')).toHaveAttribute('content', 'B')
    await expect(otherTab.locator('.composer-fields textarea')).toBeVisible()
    const currentKeys = await cacheKeys()
    expect(currentKeys.length).toBeGreaterThan(0)
    expect(currentKeys.filter(key => previousKeys.includes(key))).toEqual([])
    await otherTab.close()
    const reopened = await page.context().newPage()
    await reopened.goto(`/chat?room=${fixture.rooms[0]}`)
    await expect(reopened.locator('meta[name="e2e-build"]')).toHaveAttribute('content', 'B')
    await expect(reopened.locator('.composer-fields textarea')).toBeVisible()
  } finally {
    await writeFile(`${directory}/index.html`, originalHtml)
    await writeFile(`${directory}/sw.js`, originalWorker)
  }
})
