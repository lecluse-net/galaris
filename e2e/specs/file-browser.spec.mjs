import { createDocument } from '../documents.mjs'
import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [1440, 390]) test(`Files browses real agent resources and reopens previews at ${width}px`, async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const errors = collectPageErrors(page)
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok(), await seeded.text()).toBeTruthy()
  const fixture = await seeded.json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const checked = async response => { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }
  const agents = await checked(await request.get('/api/agents/selection?scope=management', { headers }))
  const agent = agents.find(agent => agent.id === fixture.agent_id)
  expect(agent).toBeTruthy()
  const uploaded = await checked(await request.post(`/api/file-share/files?agent_id=${fixture.agent_id}`, { headers,
    multipart: { upload: { name: 'Synthetic browser.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic assembled file content') } } }))
  // Synthetic FFmpeg testsrc2: 160x90, 12 fps, 2 seconds, H.264 baseline/yuv420p, faststart.
  // Decode a real MP4 rather than inferring codec support from a browser-created WebM.
  const video = await checked(await request.post(`/api/file-share/files?agent_id=${fixture.agent_id}`, { headers,
    multipart: { upload: { name: 'Synthetic video.mp4', mimeType: 'video/mp4', buffer: await readFile(new URL('../fixtures/synthetic-video.mp4', import.meta.url)) } } }))
  const document = await checked(await createDocument(request, {
    headers: { ...headers, 'X-Editorial-Profile-Version': '1' }, data: {
      owner_agent_id: fixture.agent_id, title: 'Synthetic browser document', node_kind: 'document',
      media_type: 'text/html', payload: { text: '<p>Synthetic assembled document content</p>' },
    },
  }))
  expect(document.id).toBeTruthy()
  await checked(await request.post(`/api/documents/${document.id}/attachments?actor_agent_id=${fixture.agent_id}`, {
    headers, multipart: { file: { name: 'Synthetic appendix.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic assembled attachment content') } },
  }))
  await errors.settle()
  await page.goto('/files')
  await expect(page.getByRole('heading', { name: 'Fichiers', exact: true })).toBeVisible()
  // Close the initially open mobile drawer once the destination page is ready;
  // a global handler can race the login transition and click an already hidden backdrop.
  if (width < 1024 && await page.locator('.q-drawer__backdrop').isVisible()) {
    await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 150 } })
  }
  await page.getByRole('button', { name: `Explorer les fichiers de ${agent.label}`, exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Agent', exact: true })).toBeVisible()
  if (width < 1024) await page.getByRole('button', { name: 'Afficher les emplacements', exact: true }).click()
  await page.getByText('Galaris managed file', { exact: true }).click()
  const file = page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic browser.txt', exact: true })
  await expect(file).toBeVisible()
  const back = () => page.evaluate(() => window.history.back())
  const forward = () => page.evaluate(() => window.history.forward())
  await back()
  await expect(file).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: 'Agent', exact: true })).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.get('uri')).toBeNull()
  await forward()
  await expect(file).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.get('uri')).toBe('file://')
  for (let index = 0; index < 2; index++) {
    await file.click()
    await expect(page.getByRole('dialog').getByText('Synthetic assembled file content', { exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await file.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Renommer', exact: true }).click()
  await page.getByRole('dialog').getByRole('textbox').fill('Synthetic renamed.txt')
  await page.getByRole('dialog').getByRole('button', { name: 'Renommer', exact: true }).click()
  const renamed = page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic renamed.txt', exact: true })
  await expect(renamed).toBeVisible()
  const renamedInfo = await checked(await request.get(`/api/file-share/browser/info?agent_id=${fixture.agent_id}&uri=${encodeURIComponent(uploaded.uri)}`, { headers }))
  expect(renamedInfo.name).toBe('Synthetic renamed.txt')
  await page.getByRole('button', { name: 'Actions pour Synthetic renamed.txt', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Supprimer', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Annuler', exact: true }).click()
  await expect(renamed).toBeVisible()
  await renamed.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Supprimer', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Supprimer', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(renamed).toHaveCount(0)
  const removed = await request.get(`/api/file-share/browser/info?agent_id=${fixture.agent_id}&uri=${encodeURIComponent(uploaded.uri)}`, { headers })
  expect(removed.status()).toBe(404)
  await page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic appendix.txt', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Synthetic assembled attachment content', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('files-page.png'), fullPage: true })
  const ranges = []
  page.on('response', response => {
    if (response.url().includes('/file-share/browser/media/') && response.request().method() === 'GET') ranges.push(response)
  })
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic video.mp4', exact: true }).click()
    const player = page.getByRole('dialog').locator('video')
    await expect.poll(() => player.evaluate(element => ({
      ready: element.readyState >= 1,
      error: element.error ? { code: element.error.code, message: element.error.message } : null,
    }))).toEqual({ ready: true, error: null })
    await player.evaluate(element => { element.muted = true; return element.play() })
    await expect.poll(() => player.evaluate(element => element.currentTime)).toBeGreaterThan(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  expect(ranges.length).toBeGreaterThanOrEqual(2)
  for (const response of ranges) {
    expect(response.status()).toBe(206)
    expect(response.headers()['content-range']).toMatch(/^bytes /)
    expect(response.request().headers().authorization).toBeUndefined()
  }
  const grant = await checked(await request.post(`/api/file-share/browser/media?agent_id=${fixture.agent_id}&uri=${encodeURIComponent(video.uri)}`, { headers }))
  const tail = await request.get(grant.url, { headers: { Range: 'bytes=-8' } })
  expect(tail.status()).toBe(206)
  expect((await tail.body()).length).toBe(8)
  if (width < 1024 && !(await page.getByText('Galaris document', { exact: true }).isVisible())) {
    await page.getByRole('button', { name: 'Afficher les emplacements', exact: true }).click()
  }
  await page.getByText('Galaris document', { exact: true }).click()
  await page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic browser document', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Synthetic assembled document content', { exact: true })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer', exact: true }).first().click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await back()
  await expect(page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic appendix.txt', exact: true })).toBeVisible()
  await forward()
  await expect(page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic browser document', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic browser document', exact: true })).toBeVisible()
  await errors.settle()
  expect(errors()).toEqual([])
})
