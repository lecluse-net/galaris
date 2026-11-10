import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('Goal descriptions and private categories persist while tracking stays independently classified', async ({ page, request }) => {
  const errors = collectPageErrors(page)
  const checked = async response => {
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const fixture = await checked(await request.post('/api/__test/seed'))
  const renamedTitle = `Renamed synthetic Goal ${fixture.agent_id}`
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const referrers = await checked(await request.get(`/api/goals/referrers/messenger?agent_id=${fixture.agent_id}`, { headers }))
  const referrer = referrers.find(item => item.is_current_user)
  expect(referrer).toBeTruthy()
  const agents = await checked(await request.get('/api/agents/selection?scope=management', { headers }))
  const selectedAgent = agents.find(item => item.id === fixture.agent_id)
  expect(selectedAgent).toBeTruthy()
  await page.goto('/goal')
  await page.getByRole('button', { name: /^(Nouvel objectif|New Goal)$/ }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: selectedAgent.label, exact: true }).click()
  await dialog.getByRole('textbox', { name: /^(Titre|Title)$/ }).fill(`Synthetic editorial Goal ${fixture.agent_id}`)
  await dialog.locator('[data-editor-surface]').fill('Initial objective')
  await dialog.getByRole('button', { name: /^(Nouvelle catégorie|New category)$/ }).click()
  await dialog.getByRole('textbox', { name: /^(Nouvelle catégorie|New category)$/ }).fill(`Synthetic Goal projects ${fixture.agent_id}`)
  const categoryCreated = page.waitForResponse(response => new URL(response.url()).pathname === '/api/goals/categories'
    && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: /^(Ajouter|Add)$/ }).click()
  const category = await checked(await categoryCreated)
  await expect(dialog.getByRole('combobox', { name: /^(Catégorie|Category)$/ })).toHaveValue(category.label)
  await expect(dialog.getByRole('textbox', { name: /^(Titre|Title)$/ })).toHaveValue(`Synthetic editorial Goal ${fixture.agent_id}`)
  await dialog.getByRole('switch', { name: /^(Activer immédiatement|Activate immediately)$/ }).uncheck()
  const goalCreated = page.waitForResponse(response => new URL(response.url()).pathname === '/api/goals'
    && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: /^(Créer|Create)$/ }).click()
  let goal = await checked(await goalCreated)
  expect(goal.category_id).toBe(category.id)
  expect(goal).not.toHaveProperty('description_document_id')
  const child = await checked(await request.post('/api/goals', { headers, data: {
    agent_id: fixture.agent_id, title: `Synthetic sub-goal ${fixture.agent_id}`, description: '<p>Child objective</p>',
    referrer: { type: 'MESSENGER', connection_id: referrer.connection_id,
      user_id: referrer.user_id, display_name: referrer.display_name }, active: false,
    parent_goal_id: goal.id, cycle_delay_seconds: null,
  } }))
  const trackingId = goal.tracking_document_id
  const tracking = (await checked(await request.get(`/api/documents/${trackingId}`, { headers }))).item
  const library = await checked(await request.post('/api/documents/library', {
    headers, data: { classification: 'unclassified', limit: 50 },
  }))
  expect(library.entries.map(entry => entry.item.id)).toContain(trackingId)
  expect(library.entries.filter(entry => entry.item.metadata.goal_id === goal.id).map(entry => entry.item.id)).toEqual([trackingId])

  await page.goto(`/goal?goal_id=${goal.id}`)
  await expect(dialog.locator('.goal-description')).toContainText('Initial objective')
  await dialog.getByRole('tab', { name: /^(Modification|Edit)$/ }).click()
  await dialog.getByRole('combobox', { name: /^(Catégorie|Category)$/ }).click()
  await page.getByRole('option', { name: category.label, exact: true }).click()
  await dialog.locator('[data-editor-surface]').fill('Revised objective — preserved after reopening')
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/goals/${goal.id}`
    && response.request().method() === 'PUT')
  await dialog.getByRole('button', { name: /^(Enregistrer|Save)$/ }).click()
  goal = await checked(await saved)
  expect(goal.description).toContain('Revised objective')
  expect(goal.tracking_document_id).toBe(trackingId)
  expect(goal.category_id).toBe(category.id)
  await expect(dialog.locator('.goal-description')).toContainText('Revised objective')
  await errors.settle()
  await page.reload()
  await expect(dialog.locator('.goal-description')).toContainText('Revised objective')
  await dialog.getByRole('tab', { name: /^(Modification|Edit)$/ }).click()
  await expect(dialog.getByRole('combobox', { name: /^(Catégorie|Category)$/ })).toHaveValue(category.label)
  await dialog.getByRole('button', { name: /^(Annuler|Cancel)$/ }).click()

  await checked(await request.patch(`/api/documents/${trackingId}?actor_agent_id=${fixture.agent_id}`, { headers, data: {
    expected_revision: tracking.revision, payload: { text: '<p>Independent tracking evidence</p>' },
  } }))
  await dialog.getByRole('tab', { name: /^(Suivi|Tracking)$/ }).click()
  await expect(dialog.locator('[data-editor-surface]')).toContainText('Independent tracking evidence')
  await errors.settle()
  await page.reload()
  await dialog.getByRole('tab', { name: /^(Suivi|Tracking)$/ }).click()
  await expect(dialog.locator('[data-editor-surface]')).toContainText('Independent tracking evidence')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.getByRole('combobox', { name: /^(Catégorie|Category)$/ }).click()
  await page.getByRole('option', { name: category.label, exact: true }).click()
  await expect(page.getByText(goal.title, { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: child.title })).toBeVisible()
  const classified = await checked(await request.get(`/api/goals?category_id=${category.id}`, { headers }))
  expect(classified.items.map(item => item.id)).toEqual([goal.id, child.id])
  expect(classified.items[1].category_id).toBeNull()
  expect(classified.items[1].effective_category_id).toBe(category.id)
  await page.getByRole('button', { name: /^(Gérer mes catégories|Manage my categories)$/ }).click()
  await expect(dialog.getByRole('textbox', { name: /^(Catégorie|Category)$/ })).toHaveValue(category.label)
  await dialog.getByRole('button', { name: /^(Supprimer|Delete)$/, exact: true }).click()
  const confirmation = page.getByRole('dialog').filter({ hasText: /^(Supprimer la catégorie|Delete category)/ })
  await confirmation.getByRole('button', { name: /^(Supprimer|Delete)$/ }).click()
  await expect(confirmation).toHaveCount(0)
  await expect(dialog).toContainText(/(Vous n’avez pas encore de catégorie|You have no categories yet)/)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  goal = await checked(await request.get(`/api/goals/${goal.id}`, { headers }))
  expect(goal.category_id).toBeNull()
  expect(goal.tracking_document_id).toBe(trackingId)

  const folder = await checked(await request.post('/api/documents/tags', { headers, data: {
    name: `Synthetic personal projects ${fixture.agent_id}`, parent_id: null,
  } }))
  await errors.settle()
  await page.goto('/documents')
  const list = page.getByRole('list', { name: /^(Documents non classés|Unclassified documents)$/ })
  const tree = page.getByRole('tree')
  await expect(list.getByText(tracking.title, { exact: true })).toBeVisible()
  await expect(tree.getByText(tracking.title, { exact: true })).toHaveCount(0)
  const moved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/documents/${trackingId}/tags`
    && response.request().method() === 'PUT')
  await list.getByText(tracking.title, { exact: true }).dragTo(tree.getByText(folder.name, { exact: true }))
  expect((await moved).ok()).toBeTruthy()
  await errors.settle()
  await expect(tree.getByText(tracking.title, { exact: true })).toBeVisible()
  await expect(list.getByText(tracking.title, { exact: true })).toHaveCount(0)
  goal = await checked(await request.get(`/api/goals/${goal.id}`, { headers }))
  await checked(await request.put(`/api/goals/${goal.id}`, { headers, data: {
    expected_revision: goal.revision, title: renamedTitle,
  } }))
  await expect(tree.getByText(`${renamedTitle} — Suivi`, { exact: true })).toBeVisible()
  await errors.settle()
  await page.reload()
  await tree.getByText(folder.name, { exact: true }).click()
  await expect(tree.getByText(`${renamedTitle} — Suivi`, { exact: true })).toBeVisible()
  await expect(list.getByText(`${renamedTitle} — Suivi`, { exact: true })).toHaveCount(0)
  await errors.settle()
  expect(errors()).toEqual([])
})
