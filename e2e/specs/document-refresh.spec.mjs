import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('remote document changes refresh only their folder and visible page without removing rows', async ({ page, request }) => {
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
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const documents = []
  const prefix = `Refresh ${fixture.agent_id}`
  const folderTitle = `${prefix} Folder report`
  const rootTitle = `${prefix} Root report`
  const updatedTitle = `${prefix} Updated folder report`
  const folderName = `Reports ${fixture.agent_id}`
  for (const title of [folderTitle, rootTitle]) {
    const response = await request.post('/api/memory/items', { headers, data: {
      owner_agent_id: fixture.agent_id, title, node_kind: 'document',
      media_type: 'text/html', payload: { text: '<p>Synthetic report</p>' },
    } })
    expect(response.ok(), await response.text()).toBeTruthy()
    documents.push(await response.json())
  }
  const created = await request.post('/api/memory/documents/tags', { headers, data: { name: folderName, parent_id: null } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const folder = await created.json()
  const filed = await request.put(`/api/memory/documents/${documents[0].id}/tags`, { headers, data: { tag_id: folder.id } })
  expect(filed.ok(), await filed.text()).toBeTruthy()
  await pageErrors.settle()
  await page.goto(`/memory/documents?document_id=${documents[1].id}`)
  await page.getByText(folderName, { exact: true }).click()
  const searched = page.waitForResponse(response => new URL(response.url()).pathname === '/api/memory/documents/library'
    && response.request().postDataJSON()?.query === prefix)
  await page.getByRole('textbox', { name: 'Rechercher dans les titres et le contenu des documents', exact: true }).fill(prefix)
  expect((await searched).ok()).toBe(true)
  await pageErrors.settle()
  await page.getByRole('button', { name: 'Filtres', exact: true }).click()
  await page.getByRole('switch', { name: 'Non classés', exact: true }).click()
  await page.keyboard.press('Escape')
  const list = page.getByLabel('Tous les documents', { exact: true })
  const tree = page.getByLabel(`Documents du dossier ${folderName}`, { exact: true })
  await expect(list.getByText(folderTitle, { exact: true })).toBeVisible()
  await expect(tree.getByText(folderTitle, { exact: true })).toBeVisible()
  await expect(list.getByText(rootTitle, { exact: true })).toBeVisible()
  const listRow = await list.getByText(folderTitle, { exact: true }).elementHandle()
  const treeRow = await tree.getByText(folderTitle, { exact: true }).elementHandle()
  const rootRow = await list.getByText(rootTitle, { exact: true }).elementHandle()
  let release
  const gate = new Promise(resolve => { release = resolve })
  const requests = []
  await page.route('**/api/memory/documents/library', async route => {
    requests.push(route.request().postDataJSON().tag_id)
    await gate
    await route.continue()
  })
  const updated = await request.patch(`/api/memory/documents/${documents[0].id}?actor_agent_id=${fixture.agent_id}`, {
    headers, data: { title: updatedTitle, expected_revision: documents[0].revision },
  })
  expect(updated.ok(), await updated.text()).toBeTruthy()
  await expect.poll(() => requests.length).toBe(2)
  expect(new Set(requests)).toEqual(new Set([null, folder.id]))
  await expect(list.getByText(folderTitle, { exact: true })).toBeVisible()
  await expect(tree.getByText(folderTitle, { exact: true })).toBeVisible()
  release()
  await expect(list.getByText(updatedTitle, { exact: true })).toBeVisible()
  await expect(tree.getByText(updatedTitle, { exact: true })).toBeVisible()
  for (const row of [listRow, treeRow, rootRow]) expect(await row.evaluate(element => element.isConnected)).toBe(true)
  expect(pageErrors()).toEqual([])
})
