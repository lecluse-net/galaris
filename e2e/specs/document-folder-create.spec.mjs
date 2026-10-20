import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

// Playwright's worker blocker reads navigator.serviceWorker in opaque frames.
// Keep the document sandbox intact and avoid injecting that failing script.
test.use({ serviceWorkers: 'allow' })

test('creating documents in folders and under documents persists the personal hierarchy', async ({ page, request }, testInfo) => {
  const pageErrors = collectPageErrors(page)
  const seed = await request.post('/api/__test/seed')
  expect(seed.ok()).toBeTruthy()
  const fixture = await seed.json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authenticated = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authenticated).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const parentResponse = await request.post('/api/memory/documents/tags', { headers, data: { name: 'Synthetic reports', parent_id: null, icon: 'folder:green' } })
  expect(parentResponse.ok()).toBeTruthy()
  const parent = await parentResponse.json()
  const childResponse = await request.post('/api/memory/documents/tags', { headers, data: { name: 'Synthetic drafts', parent_id: parent.id } })
  expect(childResponse.ok()).toBeTruthy()
  const child = await childResponse.json()
  expect(child.icon).toBe(parent.icon)

  await pageErrors.settle()
  await page.goto('/memory/documents')
  await page.getByText(parent.name, { exact: true }).click()
  await page.getByText(child.name, { exact: true }).click({ button: 'right' })
  const folderMenu = page.getByRole('menu', { name: `Actions du dossier ${child.name}`, exact: true })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: `Actions du dossier ${child.name}`, exact: true }).click()
  await folderMenu.screenshot({ path: testInfo.outputPath('folder-context-menu.png'), animations: 'disabled' })
  await folderMenu.getByRole('menuitem', { name: `Nouveau document dans ${child.name}`, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Titre', { exact: true }).fill('Synthetic folder notes')
  const createdResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/memory/documents'
    && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  const created = await createdResponse
  expect(created.ok(), await created.text()).toBeTruthy()
  const document = await created.json()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('[data-editor-surface]')).toBeVisible()
  const folder = page.getByLabel(`Documents du dossier ${child.name}`, { exact: true })
  await expect(folder.getByText(document.title, { exact: true })).toBeVisible()
  await expect(page.getByLabel('Documents non classés', { exact: true }).getByText(document.title, { exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('document-created-in-folder.png'), animations: 'disabled' })

  await page.getByRole('button', { name: `Nouveau sous-document de ${document.title}`, exact: true }).click()
  await dialog.getByLabel('Titre', { exact: true }).fill('Synthetic child notes')
  const childCreatedResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/memory/documents'
    && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  const childCreated = await childCreatedResponse
  expect(childCreated.ok(), await childCreated.text()).toBeTruthy()
  const subdocument = await childCreated.json()
  await expect(dialog).toHaveCount(0)
  const subdocuments = page.getByLabel(`Sous-documents de ${document.title}`, { exact: true })
  await expect(subdocuments.getByText(subdocument.title, { exact: true })).toBeVisible()
  const nested = await request.post('/api/memory/documents/library', { headers, data: {
    parent_document_id: document.id, include_descendants: false, limit: 50,
  } })
  expect(nested.ok()).toBeTruthy()
  expect((await nested.json()).entries.map(entry => [entry.item.id, entry.parent_document_id])).toEqual([[subdocument.id, document.id]])
  await page.screenshot({ path: testInfo.outputPath('sub-document-created.png'), animations: 'disabled' })

  // Read persisted membership through the real API, then reopen the assembled library.
  const membership = await request.post('/api/memory/documents/library', {
    headers, data: { tag_id: child.id, classification: 'all', limit: 50, offset: 0 },
  })
  expect(membership.ok()).toBeTruthy()
  expect((await membership.json()).entries.map(entry => entry.item.id)).toContain(document.id)
  await pageErrors.settle()
  await page.reload()
  await page.getByText(parent.name, { exact: true }).click()
  await page.getByText(child.name, { exact: true }).click()
  await expect(folder.getByText(document.title, { exact: true })).toBeVisible()
  await page.getByRole('treeitem').filter({ has: page.getByText(document.title, { exact: true }) }).press('Space')
  await expect(subdocuments.getByText(subdocument.title, { exact: true })).toBeVisible()
  await subdocuments.getByText(subdocument.title, { exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`document_id=${subdocument.id}`))
  expect(pageErrors()).toEqual([])
})
