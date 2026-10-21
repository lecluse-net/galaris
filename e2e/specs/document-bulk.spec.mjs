import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

async function checked(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test.use({ serviceWorkers: 'allow' })

for (const width of [1440, 390]) test(`folder bulk actions preserve distinct settings in the assembled application at ${width}px`, async ({ page, request }, testInfo) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width, height: 1000 })
  const errors = collectPageErrors(page)
  const seed = await checked(await request.post('/api/__test/seed'))
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(seed.email)
  await page.locator('input[type=password]').fill(seed.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await checked(await authentication)
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const user = await checked(await request.get('/api/auth/me', { headers }))
  const folder = await checked(await request.post('/api/memory/documents/tags', { headers, data: { name: `Synthetic bulk ${seed.agent_id}`, parent_id: null } }))
  const child = await checked(await request.post('/api/memory/documents/tags', { headers, data: { name: 'Synthetic nested reports', parent_id: folder.id } }))
  const docs = []
  for (let index = 0; index < 3; index++) {
    const doc = await checked(await request.post('/api/memory/items', { headers, data: {
      owner_agent_id: seed.agent_id, title: `Synthetic bulk ${seed.agent_id} report ${index}`, node_kind: 'document',
      keywords: [`original-${index}`], media_type: 'text/html', payload: { text: `<h1>Synthetic report ${index}</h1><p>Content retained through bulk operations.</p>` },
    } }))
    docs.push(doc)
    if (index < 2) {
      expect((await request.put(`/api/memory/documents/${doc.id}/tags`, { headers, data: { tag_id: index ? child.id : folder.id } })).ok()).toBe(true)
    }
  }
  await checked(await request.put(`/api/memory/documents/${docs[0].id}/sharing`, { headers, data: {
    kind: 'user', id: user.id, can_write: false, expected_lock_version: docs[0].lock_version,
  } }))
  const state = id => request.get(`/api/memory/documents/${id}/sharing`, { headers }).then(checked)
  const detail = id => request.get(`/api/memory/documents/${id}`, { headers }).then(checked)
  await errors.settle()
  await page.goto('/documents')
  // The mobile drawer is independent of the Documents workspace.
  if (width < 1024) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }))
  await page.getByText(folder.name, { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Afficher en liste', exact: true }).click()
  const list = page.getByRole('region', { name: folder.name, exact: true })
  await expect(list.getByRole('link', { name: docs[0].title, exact: true })).toBeVisible()
  await expect(list.getByRole('link', { name: docs[1].title, exact: true })).toHaveCount(0)
  await list.getByRole('checkbox', { name: 'Inclure les sous-dossiers et sous-documents', exact: true }).check()
  await expect(list.getByRole('link', { name: docs[1].title, exact: true })).toBeVisible()
  async function choose(field, option) {
    await page.getByRole('dialog').getByRole('combobox', { name: field, exact: true }).click()
    await page.getByRole('option', { name: option, exact: true }).click()
  }
  async function action(name) {
    await list.getByRole('checkbox', { name: 'Sélectionner cette page', exact: true }).check()
    await list.getByRole('button', { name: 'Actions sur la sélection', exact: true }).click()
    await choose('Opération', name)
  }
  async function apply() {
    await page.getByRole('dialog').getByRole('button', { name: 'Appliquer', exact: true }).click()
    await expect(list.getByText('2 réussi(s), 0 en échec.', { exact: false })).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await action('Ajouter des mots-clés')
  await page.getByRole('dialog').getByRole('combobox', { name: 'Mots-clés', exact: true }).fill('batch-keyword')
  await page.getByRole('dialog').getByRole('combobox', { name: 'Mots-clés', exact: true }).press('Enter')
  await apply()
  for (let index = 0; index < 2; index++) expect((await detail(docs[index].id)).item.keywords).toEqual([`original-${index}`, 'batch-keyword'])
  expect((await detail(docs[2].id)).item.keywords).toEqual(['original-2'])
  await action('Modifier le partage')
  await choose('Action sur le partage', 'Ajouter / régler en lecture')
  await apply()
  expect((await state(docs[0].id)).grants).toEqual(expect.arrayContaining([expect.objectContaining({ kind: 'user', id: user.id, can_write: false })]))
  for (const doc of docs.slice(0, 2)) expect((await state(doc.id)).level).toBe('public')
  await action('Modifier le partage')
  await choose('Action sur le partage', 'Retirer ce partage')
  await apply()
  for (const doc of docs.slice(0, 2)) expect((await state(doc.id)).level).toBe('private')
  expect((await state(docs[0].id)).grants).toEqual(expect.arrayContaining([expect.objectContaining({ kind: 'user', id: user.id })]))
  await page.screenshot({ path: testInfo.outputPath(`bulk-folder-${width}.png`), animations: 'disabled' })
  await list.getByRole('button', { name: 'Fermer la liste', exact: true }).click()
  await page.getByRole('button', { name: 'Afficher les documents non classés en liste', exact: true }).click()
  const unclassified = page.getByRole('region', { name: 'Documents non classés', exact: true })
  await expect(unclassified.getByRole('link', { name: docs[2].title, exact: true })).toBeVisible()
  await expect(unclassified.getByRole('link', { name: docs[0].title, exact: true })).toHaveCount(0)
  await unclassified.getByRole('checkbox', { name: `Sélectionner ${docs[2].title}`, exact: true }).check()
  await unclassified.getByRole('button', { name: 'Actions sur la sélection', exact: true }).click()
  await choose('Opération', 'Supprimer les documents')
  await page.getByRole('dialog').getByRole('button', { name: 'Supprimer les documents', exact: true }).click()
  await expect(unclassified.getByRole('link', { name: docs[2].title, exact: true })).toHaveCount(0)
  expect([403, 404]).toContain((await request.get(`/api/memory/documents/${docs[2].id}`, { headers })).status())
  await errors.settle()
  expect(errors()).toEqual([])
})
