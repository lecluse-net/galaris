import { test, expect } from '@playwright/test'
import { createDocument } from '../documents.mjs'
import { collectPageErrors } from '../page-errors.mjs'

test.use({ serviceWorkers: 'allow' })

test('Documents and Datasets keep resources at the tree root across folder moves and reloads', async ({ page, request }, testInfo) => {
  const errors = collectPageErrors(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login'); await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  for (const domain of ['documents', 'datasets']) {
    const isDocument = domain === 'documents'
    const response = isDocument ? await createDocument(request, { headers, data: {
      owner_agent_id: fixture.agent_id, title: 'Synthetic root document', payload: { text: '<p>Root content</p>' },
    } }) : await request.post('/api/datasets', { headers, data: { title: 'Synthetic root Dataset', content: '{"root":true}' } })
    expect(response.ok(), await response.text()).toBeTruthy()
    const item = await response.json()
    const untouchedTitle = `Synthetic unclassified ${domain}`
    const untouchedResponse = isDocument ? await createDocument(request, { headers, data: { owner_agent_id: fixture.agent_id, title: untouchedTitle } })
      : await request.post('/api/datasets', { headers, data: { title: untouchedTitle, content: '{}' } })
    expect(untouchedResponse.ok(), await untouchedResponse.text()).toBeTruthy()
    const untouched = await untouchedResponse.json()
    const createdFolder = await request.post(`/api/${domain}/tags`, { headers, data: { name: `Synthetic ${domain} folder`, parent_id: null } })
    expect(createdFolder.ok(), await createdFolder.text()).toBeTruthy()
    const folder = await createdFolder.json()
    await errors.settle()
    await page.goto(isDocument ? '/documents' : '/dataset')
    const tree = page.getByRole('tree')
    const row = tree.getByText(item.title, { exact: true })
    const list = page.getByRole('list', { name: isDocument ? /^(Unclassified documents|Documents non classés)$/ : /^(Unclassified Datasets|Jeux de données non classés)$/, exact: true })
    const root = page.getByRole('group', { name: /^(Root|Racine)$/, exact: true })
    await expect(list.getByText(item.title, { exact: true })).toBeVisible()
    await expect(row).toHaveCount(0)
    await expect(tree.getByText(untouched.title, { exact: true })).toHaveCount(0)
    const moveResponse = () => page.waitForResponse(response => new URL(response.url()).pathname === (isDocument ? `/api/documents/${item.id}/tags` : '/api/datasets/library/move')
      && response.request().method() === (isDocument ? 'PUT' : 'POST'))
    const pinned = moveResponse()
    await list.getByText(item.title, { exact: true }).dragTo(root)
    expect((await pinned).ok()).toBeTruthy()
    await expect(root.getByRole('button').first()).toBeEnabled()
    await expect(row).toBeVisible()
    await expect(list.getByText(item.title, { exact: true })).toHaveCount(0)
    const placed = moveResponse()
    await row.dragTo(tree.getByText(folder.name, { exact: true }))
    expect((await placed).ok()).toBeTruthy()
    await expect(root.getByRole('button').first()).toBeEnabled()
    if (!isDocument) await tree.getByText(folder.name, { exact: true }).click()
    await expect(row).toHaveCount(1)
    await expect(row).toBeVisible()
    const moved = moveResponse()
    await row.dragTo(root)
    expect((await moved).ok()).toBeTruthy()
    await page.reload()
    // Folders start closed, so this resource can only be reached at the root.
    await expect(row).toBeVisible()
    await row.click()
    await expect(page.getByRole('textbox', { name: /^(Title|Titre)$/, exact: true })).toHaveValue(item.title)
    await page.screenshot({ path: testInfo.outputPath(`${domain}-root.png`), animations: 'disabled' })
    const read = isDocument ? await request.post('/api/documents/library', { headers, data: { classification: 'root', limit: 50 } })
      : await request.get('/api/datasets?classification=root&page_size=50', { headers })
    expect(read.ok(), await read.text()).toBeTruthy()
    const result = await read.json()
    expect((isDocument ? result.entries.map(entry => entry.item.id) : result.items.map(item => item.id))).toContain(item.id)
    expect((isDocument ? result.entries.map(entry => entry.item.id) : result.items.map(item => item.id))).not.toContain(untouched.id)
    await expect(tree.getByText(untouched.title, { exact: true })).toHaveCount(0)
    await root.getByRole('button').first().click()
    const dialog = page.getByRole('dialog')
    const createdTitle = `Synthetic created at root ${domain}`
    await dialog.getByRole('textbox', { name: /^(Title|Titre)$/, exact: true }).fill(createdTitle)
    await dialog.getByRole('button', { name: /^(Create|Créer)$/, exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(tree.getByText(createdTitle, { exact: true })).toBeVisible()
  }
  expect(errors()).toEqual([])
})
