import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, goal } from './data.mjs'

async function goals(page, status = 'ACTIVE', id = 'goal-a') {
  let current = { ...goal, id, status }
  const commands = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await jsonRoute(page, '**/api/goals/settings', { globally_paused: false, schedule_enabled: false, schedule: [], timezone: 'UTC', is_active: true, inactive_reason: null, next_active_at: null })
  await jsonRoute(page, '**/api/goals/tree', { items: [current], total: 1 })
  await jsonRoute(page, `**/api/goals/${id}/cycles?*`, { items: [], total: 0, page: 1, page_size: 50 })
  await page.route('**/api/goals?*', route => route.fulfill({ json: { items: [current], total: 1, summary: { active: 1, paused: 0, completed: 0, errors: 0, total_cost: 0 }, tracking_llm_configured: true } }))
  await page.route(`**/api/goals/${id}`, route => route.fulfill({ json: current }))
  await page.route(new RegExp(`/api/goals/${id}/(pause|resume|complete|run-now)$`), route => {
    const command = new URL(route.request().url()).pathname.split('/').at(-1)
    commands.push({ command, payload: route.request().postDataJSON() })
    current = { ...current, revision: current.revision + 1, status: command === 'pause' ? 'PAUSED' : command === 'complete' ? 'COMPLETED' : 'ACTIVE' }
    return route.fulfill({ json: current })
  })
  return commands
}

for (const mode of ['read', 'edit']) test(`a Goal citation opens its original modal and preserves another Goal selection in ${mode} mode`, async ({ page }) => {
  const id = '00000000-0000-0000-0000-000000000003'
  const commands = await goals(page, 'ACTIVE', id)
  const html = `<p><a href="galaris://goal/${id}">Publish report</a></p>`
  await mount(page, `core/util/components/${mode === 'edit' ? 'RichTextEditor' : 'RichText'}.vue`, { props: mode === 'edit' ? { modelValue: html, profile: 'document' } : { content: html, profile: 'document' }, privileges: ['GOAL_EDIT'] })
  await page.evaluate(async goal => {
    const { useGoalStore } = await import('/app/goal/stores/goalStore.ts')
    useGoalStore().currentGoal = { ...goal, id: 'other-goal' }
  }, goal)
  const url = page.url(), popups = []
  page.on('popup', popup => popups.push(popup))
  const open = async () => {
    await page.getByRole('link', { name: 'Publish report', exact: true }).click()
    if (mode === 'edit') await page.keyboard.press('Alt+Enter')
    await expect(page.getByRole('dialog').getByRole('tab', { name: 'Goal', exact: true })).toBeVisible()
    expect(page.url()).toBe(url); expect(popups).toHaveLength(0)
  }
  await open()
  await page.getByRole('dialog').getByRole('button', { name: /^pause$/i }).click()
  await expect.poll(() => commands).toEqual([{ command: 'pause', payload: { expected_revision: 4 } }])
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await open()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await page.evaluate(async () => (await import('/app/goal/stores/goalStore.ts')).useGoalStore().currentGoal.id)).toBe('other-goal')
})

for (const width of [390, 1440]) {
  test(`goal details expose lifecycle actions and editable tabs at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    const commands = await goals(page)
    await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
    const view = page.locator('button').filter({ has: page.locator('.q-icon', { hasText: 'visibility' }) }).first()
    await view.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Publish report')
    await dialog.getByRole('button', { name: /^pause$/i }).click()
    await expect.poll(() => commands).toEqual([{ command: 'pause', payload: { expected_revision: 4 } }])
    await expect(dialog.getByRole('button', { name: /^pause$/i })).toHaveCount(0)
    await dialog.getByRole('button', { name: /resume|restart/i }).click()
    await expect.poll(() => commands.at(-1)).toEqual({ command: 'resume', payload: { expected_revision: 5 } })
    await dialog.getByRole('tab', { name: /edit/i }).click()
    await expect(dialog.locator('input').first()).toBeEditable()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
  })
}

test('read-only goal details never expose mutation actions or an editing tab', async ({ page }) => {
  await goals(page, 'COMPLETED')
  await mount(page, 'app/goal/pages/index.vue')
  await page.locator('button').filter({ has: page.locator('.q-icon', { hasText: 'visibility' }) }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('tab', { name: /edit/i })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: /pause|restart|delete|complete/i })).toHaveCount(0)
})

test('closing a goal form makes its pending referrer lookup obsolete', async ({ page }) => {
  await goals(page)
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/goals/referrers/messenger?*', async route => {
    await pending
    await route.fulfill({ status: 503, json: { detail: 'Obsolete referrer failure' } })
  })
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
  const request = page.waitForRequest('**/api/goals/referrers/messenger?*')
  await page.getByRole('button', { name: 'New Goal', exact: true }).click()
  try {
    await request
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const response = page.waitForResponse('**/api/goals/referrers/messenger?*')
    release()
    await response
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(page.getByText('Obsolete referrer failure', { exact: false })).toHaveCount(0)
  } finally { release() }
})
