import { createDocument } from '../documents.mjs'
import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'
import { withSidebarDismissal } from '../sidebar.mjs'

for (const width of [1440, 390]) test(`attachment names survive document and file-browser reopening at ${width}px`, async ({ page, request }, info) => {
  const errors = collectPageErrors(page)
  await page.setViewportSize({ width, height: 1000 })
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
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const created = await createDocument(request, { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic attachment rename', node_kind: 'document',
    media_type: 'text/html', payload: { text: '<p>Preserved document body</p>' },
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const document = await created.json()
  const uploaded = await request.post(`/api/documents/${document.id}/attachments?actor_agent_id=${fixture.agent_id}`, {
    headers, multipart: { file: { name: 'Original.txt', mimeType: 'text/plain', buffer: Buffer.from('Entirely synthetic attachment') } },
  })
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy()
  const attachment = await uploaded.json()
  const before = (await (await request.get(`/api/documents/${document.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  await errors.settle()
  await page.goto(`/documents?document_id=${document.id}`)
  await page.locator('.document-attachments__item').filter({ hasText: 'Original.txt' }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Renommer', exact: true }).click()
  const dialog = page.getByRole('dialog').filter({ hasText: 'Renommer le fichier' })
  await dialog.getByRole('textbox', { name: 'Nom du fichier', exact: true }).fill('Final résumé.txt')
  const saved = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/attachments/${attachment.id}`))
  await dialog.getByRole('textbox', { name: 'Nom du fichier', exact: true }).press('Enter')
  expect((await saved).ok()).toBeTruthy()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('.document-attachments__item')).toContainText('Final résumé.txt')
  await info.attach('renamed-attachment', { body: await page.screenshot(), contentType: 'image/png' })
  await errors.settle()
  await page.reload()
  await expect(page.locator('.document-attachments__item')).toContainText('Final résumé.txt')
  const current = (await (await request.get(`/api/documents/${document.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  expect(current.revision).toBe(before.revision)
  expect(current.payload.text).toBe(before.payload.text)
  const downloaded = await request.get(`/api/documents/${document.id}/attachments/${attachment.id}?agent_id=${fixture.agent_id}`, { headers })
  expect(await downloaded.text()).toBe('Entirely synthetic attachment')
  await errors.settle()
  await page.goto(`/files?agent_id=${fixture.agent_id}`)
  if (width < 1024) {
    await withSidebarDismissal(page, () => page.getByRole('button', { name: 'Afficher les emplacements', exact: true }).click())
  }
  await page.getByRole('main').getByRole('button', { name: 'Ouvrir Fichiers', exact: true }).click()
  await page.locator('.file-main').getByRole('button', { name: 'Ouvrir Final résumé.txt', exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Renommer', exact: true }).click()
  await page.getByRole('textbox', { name: 'Nom du fichier', exact: true }).fill('Browser report.txt')
  const browserSaved = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/file-share/files/${attachment.id}`))
  await page.getByRole('button', { name: 'Renommer', exact: true }).click()
  expect((await browserSaved).ok()).toBeTruthy()
  await expect(page.locator('.file-main')).toContainText('Browser report.txt')
  // Keep the loaded directory in the SPA, then rename through another authorized surface.
  const elsewhere = await request.patch(`/api/documents/${document.id}/attachments/${attachment.id}?actor_agent_id=${fixture.agent_id}`,
    { headers, data: { name: 'Canonical viewer name.txt' } })
  expect(elsewhere.ok(), await elsewhere.text()).toBeTruthy()
  await page.getByRole('button', { name: 'Ouvrir Browser report.txt', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Canonical viewer name.txt', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('.file-main')).toContainText('Canonical viewer name.txt')
  await errors.settle()
  await page.goto(`/documents?document_id=${document.id}`)
  await expect(page.locator('.document-attachments__item')).toContainText('Canonical viewer name.txt')
  await errors.settle()
  expect(errors()).toEqual([])
})
