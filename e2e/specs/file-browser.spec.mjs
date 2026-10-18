import { test, expect } from '@playwright/test'
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
  await checked(await request.post(`/api/file-share/files?agent_id=${fixture.agent_id}`, { headers,
    multipart: { upload: { name: 'Synthetic browser.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic assembled file content') } } }))
  const document = await checked(await request.post('/api/memory/items', {
    headers: { ...headers, 'X-Editorial-Profile-Version': '1' }, data: {
      owner_agent_id: fixture.agent_id, title: 'Synthetic browser document', node_kind: 'document',
      media_type: 'text/html', payload: { text: '<p>Synthetic assembled document content</p>' },
    },
  }))
  expect(document.id).toBeTruthy()
  await checked(await request.post(`/api/memory/documents/${document.id}/attachments?actor_agent_id=${fixture.agent_id}`, {
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
  for (let index = 0; index < 2; index++) {
    await file.click()
    await expect(page.getByRole('dialog').getByText('Synthetic assembled file content', { exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic appendix.txt', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Synthetic assembled attachment content', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('files-page.png'), fullPage: true })
  if (width < 1024 && !(await page.getByText('Galaris document', { exact: true }).isVisible())) {
    await page.getByRole('button', { name: 'Afficher les emplacements', exact: true }).click()
  }
  await page.getByText('Galaris document', { exact: true }).click()
  await page.locator('.file-main').getByRole('button', { name: 'Ouvrir Synthetic browser document', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Synthetic assembled document content', { exact: true })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer', exact: true }).first().click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await errors.settle()
  expect(errors()).toEqual([])
})
