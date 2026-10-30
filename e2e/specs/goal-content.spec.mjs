import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('Goal descriptions save inline while tracking remains editable and personally classified', async ({ page, request }) => {
  const errors = collectPageErrors(page)
  const checked = async response => {
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const fixture = await checked(await request.post('/api/__test/seed'))
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
  let goal = await checked(await request.post('/api/goals', { headers, data: {
    agent_id: fixture.agent_id, title: 'Synthetic editorial Goal', description: '<p>Initial objective</p>',
    referrer: { type: 'MESSENGER', connection_id: referrer.connection_id,
      user_id: referrer.user_id, display_name: referrer.display_name }, active: false,
  } }))
  expect(goal).not.toHaveProperty('description_document_id')
  const trackingId = goal.tracking_document_id
  const tracking = (await checked(await request.get(`/api/documents/${trackingId}`, { headers }))).item
  const library = await checked(await request.post('/api/documents/library', {
    headers, data: { classification: 'unclassified', limit: 50 },
  }))
  expect(library.entries.map(entry => entry.item.id)).toContain(trackingId)
  expect(library.entries.filter(entry => entry.item.metadata.goal_id === goal.id).map(entry => entry.item.id)).toEqual([trackingId])

  await page.goto(`/goal?goal_id=${goal.id}`)
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.goal-description')).toContainText('Initial objective')
  await dialog.getByRole('tab', { name: /^(Modification|Edit)$/ }).click()
  await dialog.locator('[data-editor-surface]').fill('Revised objective — preserved after reopening')
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/goals/${goal.id}`
    && response.request().method() === 'PUT')
  await dialog.getByRole('button', { name: /^(Enregistrer|Save)$/ }).click()
  goal = await checked(await saved)
  expect(goal.description).toContain('Revised objective')
  expect(goal.tracking_document_id).toBe(trackingId)
  await page.reload()
  await expect(dialog.locator('.goal-description')).toContainText('Revised objective')

  await checked(await request.patch(`/api/documents/${trackingId}?actor_agent_id=${fixture.agent_id}`, { headers, data: {
    expected_revision: tracking.revision, payload: { text: '<p>Independent tracking evidence</p>' },
  } }))
  await page.reload()
  await dialog.getByRole('tab', { name: /^(Suivi|Tracking)$/ }).click()
  await expect(dialog.locator('[data-editor-surface]')).toContainText('Independent tracking evidence')
  await page.keyboard.press('Escape')

  const folder = await checked(await request.post('/api/documents/tags', { headers, data: {
    name: 'Synthetic personal projects', parent_id: null,
  } }))
  await page.goto('/documents')
  const list = page.getByRole('list', { name: /^(Documents non classés|Unclassified documents)$/ })
  const tree = page.getByRole('tree')
  await expect(list.getByText(tracking.title, { exact: true })).toBeVisible()
  await expect(tree.getByText(tracking.title, { exact: true })).toHaveCount(0)
  const moved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/documents/${trackingId}/tags`
    && response.request().method() === 'PUT')
  await list.getByText(tracking.title, { exact: true }).dragTo(tree.getByText(folder.name, { exact: true }))
  expect((await moved).ok()).toBeTruthy()
  goal = await checked(await request.get(`/api/goals/${goal.id}`, { headers }))
  await checked(await request.put(`/api/goals/${goal.id}`, { headers, data: {
    expected_revision: goal.revision, title: 'Renamed synthetic Goal',
  } }))
  await page.reload()
  await tree.getByText(folder.name, { exact: true }).click()
  await expect(tree.getByText('Renamed synthetic Goal — Suivi', { exact: true })).toBeVisible()
  await expect(list.getByText('Renamed synthetic Goal — Suivi', { exact: true })).toHaveCount(0)
  expect(errors()).toEqual([])
})
