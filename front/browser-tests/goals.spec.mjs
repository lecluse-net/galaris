import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { agent, goal, result } from './data.mjs'

async function goals(page, status = 'ACTIVE', id = 'goal-a', changes = {}) {
  let current = { ...goal, id, status, ...changes }
  const commands = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await jsonRoute(page, '**/api/goals/settings', { globally_paused: false, schedule_enabled: false, schedule: [], timezone: 'UTC', is_active: true, inactive_reason: null, next_active_at: null })
  await jsonRoute(page, '**/api/goals/runtime-status', { globally_paused: false, schedule_enabled: false, timezone: 'UTC', is_active: true, inactive_reason: null, next_active_at: null })
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

test('a fixed Goal cadence saves with a timezone and survives reopening', async ({ page }) => {
  await goals(page)
  let current = { ...goal, referrer: { type: 'MESSENGER', connection_id: 1,
    user_id: 'user:1', display_name: 'Synthetic supervisor', platform: 'internal' } }
  const writes = []
  await page.route('**/api/goals/goal-a', route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body)
      current = { ...current, ...body, revision: current.revision + 1 }
    }
    return route.fulfill({ json: current })
  })
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
  await page.getByRole('button', { name: 'Goal details', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name: 'Edit', exact: true }).click()
  await dialog.getByRole('radio', { name: 'Fixed dates in the agenda', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Recurrence timezone', exact: true }).click()
  await page.getByRole('option', { name: 'UTC', exact: true }).click()
  await dialog.getByLabel('First passage', { exact: true }).fill('2026-11-17T09:00')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ cycle_delay_seconds: null, parent_goal_id: null,
    recurrence: { frequency: 'DAILY', interval: 1, timezone: 'UTC', start_at: '2026-11-17T09:00:00.000Z' } })
  await dialog.getByRole('tab', { name: 'Edit', exact: true }).click()
  await expect(dialog.getByRole('radio', { name: 'Fixed dates in the agenda', exact: true })).toBeChecked()
  await expect(dialog.getByLabel('First passage', { exact: true })).toHaveValue('2026-11-17T09:00')
})

test.describe('Goal schedule timezone', () => {
  test.use({ timezoneId: 'America/New_York' })
  for (const width of [390, 1440]) test(`announced cycles use the schedule timezone at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 950 })
    const nextCycle = '2026-07-20T08:00:00Z'
    await goals(page, 'ACTIVE', 'goal-a', { next_cycle_at: nextCycle })
    const settings = { globally_paused: false, schedule_enabled: true,
      schedule: [{ weekdays: [0, 1, 2, 3, 4], start_time: '09:00', end_time: '17:00' }],
      timezone: 'Europe/Paris', is_active: true, inactive_reason: null, next_active_at: null }
    await jsonRoute(page, '**/api/goals/settings', settings)
    await jsonRoute(page, '**/api/goals/runtime-status', settings)
    await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_ACCESS'] })
    const expected = new Intl.DateTimeFormat('en', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Paris',
    }).format(new Date(nextCycle))
    await expect(page.getByText(expected, { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Goal details', exact: true }).click()
    await expect(page.getByRole('dialog').getByText(expected, { exact: true })).toBeVisible()
    for (const dark of [false, true]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await page.screenshot({ path: testInfo.outputPath(`schedule-timezone-${dark ? 'dark' : 'light'}.png`), fullPage: true })
    }
  })
})

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

test('column sorting keeps categories first and orders agents inside each category', async ({ page }, testInfo) => {
  await goals(page)
  const categories = [{ id: 11, label: 'Zeta' }, { id: 12, label: 'Alpha' }]
  const rows = [
    { ...goal, id: 'alpha-zora', title: 'Alpha Zora objective', agent_name: 'Zora Example', category_id: 12, effective_category_id: 12 },
    { ...goal, id: 'alpha-alice', title: 'Alpha Alice objective', agent_name: 'Alice Example', category_id: 12, effective_category_id: 12 },
    { ...goal, id: 'child', parent_goal_id: 'alpha-zora', title: 'Child with own Zeta category', agent_name: 'Aaron Example', category_id: 11, effective_category_id: 12 },
    { ...goal, id: 'leaf', parent_goal_id: 'child', title: 'Leaf without own category', category_id: null, effective_category_id: 12 },
    { ...goal, id: 'zeta-zora', title: 'Zeta Zora objective', agent_name: 'Zora Example', category_id: 11, effective_category_id: 11 },
    { ...goal, id: 'zeta-alice', title: 'Zeta Alice objective', agent_name: 'Alice Example', category_id: 11, effective_category_id: 11 },
    { ...goal, id: 'none-alice', title: 'Uncategorized objective', category_id: null, effective_category_id: null },
    { ...goal, id: 'none-child', parent_goal_id: 'none-alice', title: 'Child with own Alpha category', category_id: 12, effective_category_id: null },
  ]
  await jsonRoute(page, '**/api/goals/categories', categories)
  await jsonRoute(page, '**/api/goals/tree', { items: [...rows].reverse(), total: rows.length })
  const requests = []
  await page.route('**/api/goals?*', route => {
    const params = new URL(route.request().url()).searchParams
    requests.push(Object.fromEntries(params))
    const ids = params.get('descending') === 'true'
      ? ['alpha-zora', 'child', 'leaf', 'alpha-alice', 'zeta-zora', 'zeta-alice', 'none-alice', 'none-child']
      : ['alpha-alice', 'alpha-zora', 'child', 'leaf', 'zeta-alice', 'zeta-zora', 'none-alice', 'none-child']
    const items = ids.map(id => rows.find(row => row.id === id))
    return route.fulfill({ json: { items, total: items.length, summary: { active: items.length }, tracking_llm_configured: true } })
  })
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_ACCESS'] })
  const dataRows = page.getByRole('row').filter({ has: page.getByRole('button', { name: 'Goal details', exact: true }) })
  const titleColumn = await page.getByRole('columnheader', { name: /^Title/ }).evaluate(header => header.cellIndex)
  const titles = () => dataRows.evaluateAll((elements, data) => elements.map(row => data.titles.find(title => row.cells[data.column].textContent.includes(title))), { titles: rows.map(row => row.title), column: titleColumn })
  await page.getByRole('columnheader', { name: /^Agent/ }).click()
  await expect.poll(() => requests.at(-1)?.sort_by).toBe('agent')
  await expect.poll(titles).toEqual(['Alpha Alice objective', 'Alpha Zora objective', 'Child with own Zeta category', 'Leaf without own category', 'Zeta Alice objective', 'Zeta Zora objective', 'Uncategorized objective', 'Child with own Alpha category'])
  await page.getByRole('columnheader', { name: /^Agent/ }).click()
  await expect.poll(() => requests.at(-1)?.descending).toBe('true')
  await expect.poll(titles).toEqual(['Alpha Zora objective', 'Child with own Zeta category', 'Leaf without own category', 'Alpha Alice objective', 'Zeta Zora objective', 'Zeta Alice objective', 'Uncategorized objective', 'Child with own Alpha category'])
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(['Alpha', 'Zeta', 'Uncategorized'])
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 950 })
    for (const dark of [false, true]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await page.screenshot({ path: testInfo.outputPath(`category-titles-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true })
    }
  }
})

for (const width of [390, 1440]) {
  test(`a new Goal can create and select a category without losing its draft at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 950 })
    await goals(page)
    await jsonRoute(page, '**/api/goals/referrers/messenger?*', [])
    let attempts = 0
    const categories = []
    await page.route('**/api/goals/categories', route => {
      if (route.request().method() === 'POST') {
        attempts++
        if (attempts === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic category creation failure' } })
        const category = { id: 21, label: route.request().postDataJSON().label }
        categories.push(category)
        return route.fulfill({ status: 201, json: category })
      }
      return route.fulfill({ json: categories })
    })
    await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
    await page.getByRole('button', { name: 'New Goal', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('textbox', { name: 'Title', exact: true }).fill('Synthetic Goal draft')
    await dialog.locator('[data-editor-surface]').fill('Preserve this objective')
    await dialog.getByRole('button', { name: 'New category', exact: true }).click()
    const label = dialog.getByRole('textbox', { name: 'New category', exact: true })
    await label.fill('  Research  ')
    await label.press('Enter')
    await expect(dialog.getByRole('alert').filter({ hasText: 'Synthetic category creation failure' })).toBeVisible()
    await expect(label).toHaveValue('  Research  ')
    await expect(dialog.getByRole('textbox', { name: 'Title', exact: true })).toHaveValue('Synthetic Goal draft')
    await expect(dialog.locator('[data-editor-surface]')).toHaveText('Preserve this objective')
    for (const dark of [false, true]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await label.scrollIntoViewIfNeeded()
      await page.screenshot({ path: testInfo.outputPath(`inline-category-${dark ? 'dark' : 'light'}.png`) })
    }
    await dialog.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(dialog.getByRole('combobox', { name: 'Category', exact: true })).toHaveValue('Research')
    await expect(label).toHaveCount(0)
    await expect(dialog.getByRole('textbox', { name: 'Title', exact: true })).toHaveValue('Synthetic Goal draft')
    expect(categories).toEqual([{ id: 21, label: 'Research' }])
    await dialog.getByRole('button', { name: 'New category', exact: true }).click()
    await label.fill('Discard this category draft')
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).first().click()
    await expect(label).toHaveCount(0)
    await expect(dialog.getByRole('combobox', { name: 'Category', exact: true })).toHaveValue('Research')
    expect(attempts).toBe(2)
  })

  test(`personal Goal categories can be managed, assigned, reopened and filtered at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 950 })
    await goals(page)
    await jsonRoute(page, '**/api/agents/selection?scope=management', [{ id: 7, label: 'Alice Example', has_avatar: true }])
    await page.route('**/api/agents/7/avatar?*', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#087FF5"/><text x="20" y="27" text-anchor="middle" fill="white" font-size="20">A</text></svg>' }))
    let categories = [], failCreate = true
    let current = { ...goal, category_id: null, referrer: { type: 'MESSENGER', connection_id: 1, user_id: 'user:1', display_name: 'Synthetic supervisor', platform: 'internal' } }
    const writes = [], filters = []
    await page.route('**/api/goals/categories', route => {
      if (route.request().method() === 'POST') {
        if (failCreate) { failCreate = false; return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary category failure' } }) }
        const category = { id: 11, label: route.request().postDataJSON().label }
        categories.push(category)
        return route.fulfill({ status: 201, json: category })
      }
      return route.fulfill({ json: categories })
    })
    await page.route('**/api/goals/categories/11', route => {
      if (route.request().method() === 'DELETE') { categories = []; current = { ...current, category_id: null, revision: current.revision + 1 }; return route.fulfill({ status: 204 }) }
      categories[0] = { ...categories[0], ...route.request().postDataJSON() }
      return route.fulfill({ json: categories[0] })
    })
    await page.route('**/api/goals/goal-a', route => {
      if (route.request().method() === 'PUT') { const change = route.request().postDataJSON(); writes.push(change); current = { ...current, ...change, revision: current.revision + 1 } }
      return route.fulfill({ json: current })
    })
    await page.route('**/api/goals?*', route => {
      filters.push(Object.fromEntries(new URL(route.request().url()).searchParams))
      return route.fulfill({ json: { items: [current], total: 1, summary: { active: 1 }, tracking_llm_configured: true } })
    })
    await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
    await expect(page.getByRole('img', { name: goal.agent_name, exact: true }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Manage my categories', exact: true }).click()
    const manager = page.getByRole('dialog')
    await expect(manager).toContainText('You have no categories yet.')
    await manager.getByRole('textbox', { name: 'New category', exact: true }).fill('Research')
    await manager.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(manager.getByRole('alert')).toContainText('Synthetic temporary category failure')
    await expect(manager.getByRole('textbox', { name: 'New category', exact: true })).toHaveValue('Research')
    await manager.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(manager.getByRole('textbox', { name: 'Category', exact: true })).toHaveValue('Research')
    await manager.getByRole('textbox', { name: 'Category', exact: true }).fill('Research projects')
    await manager.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => categories[0]?.label).toBe('Research projects')
    for (const dark of [false, true]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await page.screenshot({ path: testInfo.outputPath(`category-manager-${dark ? 'dark' : 'light'}.png`) })
    }
    await manager.getByRole('button', { name: 'Close', exact: true }).first().click()
    await expect(manager).toHaveCount(0)
    const view = page.locator('button').filter({ has: page.locator('.q-icon', { hasText: 'visibility' }) }).first()
    await view.click()
    const detail = page.getByRole('dialog')
    await detail.getByRole('tab', { name: 'Edit', exact: true }).click()
    await detail.getByRole('combobox', { name: 'Category', exact: true }).click()
    await page.getByRole('option', { name: 'Research projects', exact: true }).click()
    await detail.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.at(-1)?.category_id).toBe(11)
    await detail.getByRole('button', { name: 'Close', exact: true }).click()
    await view.click()
    await detail.getByRole('tab', { name: 'Edit', exact: true }).click()
    await expect(detail.getByRole('combobox', { name: 'Category', exact: true })).toHaveValue('Research projects')
    await detail.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(detail).toHaveCount(0)
    await page.getByRole('combobox', { name: 'Category', exact: true }).click()
    await page.getByRole('option', { name: 'Research projects', exact: true }).click()
    await expect.poll(() => filters.at(-1)?.category_id).toBe('11')
    await expect(page.getByRole('option', { name: 'Research projects', exact: true })).toHaveCount(0)
    for (const dark of [false, true]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await page.screenshot({ path: testInfo.outputPath(`goal-categories-${dark ? 'dark' : 'light'}.png`), fullPage: true })
    }
    await page.getByRole('button', { name: 'Manage my categories', exact: true }).click()
    await manager.getByRole('button', { name: 'Delete', exact: true }).click()
    const confirmation = page.getByRole('dialog').filter({ hasText: 'Delete category' })
    await expect(confirmation).toContainText('Goals will be retained')
    await confirmation.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(confirmation).toHaveCount(0)
    await expect(manager).toContainText('You have no categories yet.')
    await expect.poll(() => filters.at(-1)?.category_id).toBeUndefined()
    await manager.getByRole('button', { name: 'Close', exact: true }).first().click()
    await expect(manager).toHaveCount(0)
    await page.getByRole('combobox', { name: 'Category', exact: true }).click()
    await page.getByRole('option', { name: 'Uncategorized', exact: true }).click()
    await expect.poll(() => filters.at(-1)?.uncategorized).toBe('true')
  })

  test(`Goal frequencies save and reopen without changing their duration at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 950 })
    await goals(page)
    let current = { ...goal, referrer: { type: 'MESSENGER', connection_id: 1,
      user_id: 'user:1', display_name: 'Synthetic supervisor', platform: 'internal' } }
    const writes = []
    await page.route('**/api/goals/goal-a', route => {
      if (route.request().method() === 'PUT') {
        const change = route.request().postDataJSON()
        writes.push(change)
        current = { ...current, ...change, revision: current.revision + 1 }
      }
      return route.fulfill({ json: current })
    })
    await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
    const view = page.locator('button').filter({ has: page.locator('.q-icon', { hasText: 'visibility' }) }).first()
    const dialog = page.getByRole('dialog')
    const edit = async () => {
      await view.click()
      await dialog.getByRole('tab', { name: 'Edit', exact: true }).click()
    }
    for (const [unit, value, seconds] of [
      ['seconds', 90, 90], ['days', 3, 259200], ['weeks', 2, 1209600],
      ['months', 2, 5184000], ['years', 2, 63072000],
    ]) {
      await edit()
      await dialog.getByRole('combobox', { name: 'Frequency unit', exact: true }).click()
      await page.getByRole('option', { name: unit, exact: true }).click()
      await dialog.getByRole('spinbutton', { name: 'Frequency', exact: true }).fill(String(value))
      const count = writes.length
      await dialog.getByRole('button', { name: 'Save', exact: true }).click()
      await expect.poll(() => writes.length).toBe(count + 1)
      expect(writes.at(-1).cycle_delay_seconds).toBe(seconds)
      await expect(dialog.getByRole('tab', { name: 'Goal', exact: true })).toHaveAttribute('aria-selected', 'true')
      await expect(dialog).toContainText(`${value} ${unit}`)
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).toHaveCount(0)
      await edit()
      await expect(dialog.getByRole('combobox', { name: 'Frequency unit', exact: true })).toHaveValue(unit)
      await expect(dialog.getByRole('spinbutton', { name: 'Frequency', exact: true })).toHaveValue(String(value))
      if (unit === 'years') for (const dark of [false, true]) {
        await page.evaluate(dark => window.testApp.dark(dark), dark)
        await dialog.getByRole('spinbutton', { name: 'Frequency', exact: true }).scrollIntoViewIfNeeded()
        await page.screenshot({ path: testInfo.outputPath(`frequency-${dark ? 'dark' : 'light'}.png`) })
      }
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).toHaveCount(0)
    }
  })

  test(`goal details expose lifecycle actions and editable tabs at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    const commands = await goals(page)
    await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
    const view = page.locator('button').filter({ has: page.locator('.q-icon', { hasText: 'visibility' }) }).first()
    await view.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Publish report')
    await expect(dialog.getByRole('button', { name: /^pause$/i })).toBeVisible()
    // Finish the dialog's slide transition before targeting its moving action row.
    await dialog.evaluate(async element => {
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      await Promise.all(element.getAnimations({ subtree: true })
        .filter(animation => animation.effect?.getTiming().iterations !== Infinity)
        .map(animation => animation.finished.catch(() => {})))
    })
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
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_ACCESS'] })
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

for (const mode of ['create', 'edit']) test(`a late category creation cannot select a category after cancelling the ${mode} draft`, async ({ page }) => {
  await goals(page)
  await jsonRoute(page, '**/api/goals/referrers/messenger?*', [])
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/goals/categories', async route => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: [] })
    await pending
    return route.fulfill({ status: 201, json: { id: 21, label: 'Research' } })
  })
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
  const dialog = page.getByRole('dialog')
  if (mode === 'create') {
    await page.getByRole('button', { name: 'New Goal', exact: true }).click()
  } else {
    await page.getByRole('button', { name: 'Goal details', exact: true }).first().click()
    await dialog.getByRole('tab', { name: 'Edit', exact: true }).click()
  }
  await dialog.getByRole('button', { name: 'New category', exact: true }).click()
  await dialog.getByRole('textbox', { name: 'New category', exact: true }).fill('Research')
  const request = page.waitForRequest(request => request.url().endsWith('/api/goals/categories') && request.method() === 'POST')
  await dialog.getByRole('button', { name: 'Add', exact: true }).click()
  try {
    await request
    if (mode === 'create') {
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).toHaveCount(0)
      await page.getByRole('button', { name: 'New Goal', exact: true }).click()
    } else {
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).last().click()
      await dialog.getByRole('tab', { name: 'Edit', exact: true }).click()
    }
    await dialog.getByRole('textbox', { name: 'Title', exact: true }).fill('Next synthetic Goal')
    const response = page.waitForResponse(response => response.url().endsWith('/api/goals/categories') && response.request().method() === 'POST')
    release()
    await (await response).finished()
    await dialog.getByRole('combobox', { name: 'Category', exact: true }).click()
    await expect(page.getByRole('option', { name: 'Research', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog.getByRole('combobox', { name: 'Category', exact: true })).toHaveValue('')
    await expect(dialog.getByRole('textbox', { name: 'Title', exact: true })).toHaveValue('Next synthetic Goal')
  } finally { release() }
})

test('Goal history loads on demand, recovers from an error and stays lazy after reopening', async ({ page }, testInfo) => {
  await goals(page)
  const reviewId = '00000000-0000-0000-0000-000000000173'
  const cycle = { id: 'synthetic-reviewed-cycle', goal_id: 'goal-a', sequence: 2, trigger_kind: 'TEMPORAL',
    task_id: null, review_task_id: reviewId, review_task_uri: `galaris://task/${reviewId}`,
    task_label: null, task_status: 'SUCCESS', task_cost: 0, status: 'DECIDED', verdict: 'CONTINUE',
    reason: 'Synthetic evidence was inspected.', progress_summary: 'Synthetic milestone verified.',
    evidence: ['Synthetic acceptance checks passed.'], task_finished_at: '2026-09-01T12:00:00Z',
    judge_cost: 0, judge_attempt_count: 1, error: null, created_at: '2026-09-01T11:00:00Z' }
  const review = { id: reviewId, label: 'Synthetic cycle review', objective: '<p>Check synthetic evidence.</p>',
    status: 'SUCCESS', paused: false, agent_id: null, tree_parent_id: null, parent_id: null,
    directly_linked: true, topic_id: null, data: {}, execution_result: result, revision: 1,
    created_at: '2026-09-01T12:00:00Z', updated_at: null, effort: 'standard', ai: true, cost: 0, messages: [] }
  await jsonRoute(page, `**/api/tasks/${reviewId}/full`, review)
  await jsonRoute(page, `**/api/tasks/${reviewId}`, review)
  await jsonRoute(page, `**/api/tasks/${reviewId}/children`, [])
  await jsonRoute(page, `**/api/tasks/${reviewId}/budget`, { enabled: false, scope: 'task_tree',
    provider_hard_cap: false, recorded_tokens: 0, recorded_cost: 0, active_phases: 0,
    reserved_tokens: 0, reserved_cost: 0, remaining_tokens: null, remaining_cost: null, remaining_seconds: null })
  await jsonRoute(page, '**/api/tasks/activity', [])
  await jsonRoute(page, '**/api/topics?*', [])
  let reads = 0
  await page.route('**/api/goals/goal-a/cycles?*', route => {
    reads++
    return reads === 1
      ? route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable history' } })
      : route.fulfill({ json: { items: [cycle], total: 1, page: 1, page_size: 50 } })
  })
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_ACCESS'] })
  const open = () => page.getByRole('button', { name: 'Goal details', exact: true }).first().click()
  await open()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Prepare the report')
  expect(reads).toBe(0)
  await dialog.getByRole('tab', { name: 'Cycles', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Could not load cycles.')
  await expect(dialog).not.toContainText('No cycles yet')
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 950 })
    for (const dark of [false, true]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await page.screenshot({ path: testInfo.outputPath(`history-retry-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true, animations: 'disabled' })
    }
  }
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  expect(reads).toBe(2)
  await expect(dialog).toContainText('Synthetic acceptance checks passed.')
  await expect(dialog.getByRole('button', { name: 'Open review', exact: true })).toHaveCount(0)
  await setPrivileges(page, ['GOAL_ACCESS', 'TASK_ACCESS'])
  const originalUrl = page.url()
  await dialog.getByRole('button', { name: 'Open review', exact: true }).click()
  const reviewDialog = page.getByRole('dialog').last()
  await expect(reviewDialog.getByText('Synthetic cycle review', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(originalUrl)
  await reviewDialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(1)
  await expect(dialog).toContainText('Synthetic acceptance checks passed.')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await open()
  await expect(dialog).toContainText('Prepare the report')
  expect(reads).toBe(2)
  await dialog.getByRole('tab', { name: 'Cycles', exact: true }).click()
  await expect.poll(() => reads).toBe(3)
})

test('a failed Goal list can retry without hiding existing data', async ({ page }) => {
  await goals(page)
  let fail = true
  await page.route('**/api/goals?*', route => fail
    ? route.fulfill({ status: 503, json: { detail: 'Synthetic list failure' } })
    : route.fulfill({ json: { items: [goal], total: 1, summary: {}, tracking_llm_configured: true } }))
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_ACCESS'] })
  const error = page.getByRole('alert').filter({ hasText: 'Could not load Goals.' })
  await expect(error).toBeVisible()
  fail = false
  await error.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Goal details', exact: true })).toBeVisible()
  fail = true
  await page.getByPlaceholder('Search a Goal, agent, or referrer').fill('Synthetic filter')
  await expect(error).toBeVisible()
  await expect(page.getByRole('button', { name: 'Goal details', exact: true })).toBeVisible()
  fail = false
  await error.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(error).toHaveCount(0)
})

test('live Goal updates preserve the editing revision and a conflict preserves the draft', async ({ page }) => {
  await goals(page)
  const current = { ...goal, cycle_delay_seconds: 3600, referrer: {
    type: 'MESSENGER', connection_id: 1, user_id: 'user:1', display_name: 'Synthetic supervisor', platform: 'internal',
  } }
  const writes = []
  await page.route('**/api/goals/goal-a', route => {
    if (route.request().method() === 'PUT') {
      writes.push(route.request().postDataJSON())
      return route.fulfill({ status: 409, json: { detail: 'Synthetic concurrent Goal change' } })
    }
    return route.fulfill({ json: current })
  })
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
  await page.getByRole('button', { name: 'Goal details', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name: 'Edit', exact: true }).click()
  await dialog.getByRole('textbox', { name: 'Title', exact: true }).fill('Synthetic local draft')
  await page.evaluate(updated => window.testApp.emitSocket('goal.update', { data: updated }), {
    ...current, revision: current.revision + 1, title: 'Synthetic concurrent title',
  })
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/goals/goal-a') && response.request().method() === 'GET')
  await page.evaluate(() => window.testApp.emitSocket('task.update', { data: { goal_id: 'goal-a' } }))
  await (await refresh).finished()
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(dialog.getByRole('textbox', { name: 'Title', exact: true })).toBeFocused()
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].expected_revision).toBe(4)
  await expect(dialog.getByRole('textbox', { name: 'Title', exact: true })).toHaveValue('Synthetic local draft')
  await expect(page.getByText('Synthetic concurrent Goal change', { exact: false })).toBeVisible()
})

test('closing a saving Goal keeps the next Goal selected when the save completes', async ({ page }) => {
  await goals(page)
  const first = { ...goal, cycle_delay_seconds: 3600, referrer: {
    type: 'MESSENGER', connection_id: 1, user_id: 'user:1', display_name: 'Synthetic supervisor', platform: 'internal',
  } }
  const second = { ...first, id: 'goal-b', title: 'Synthetic second Goal' }
  await jsonRoute(page, '**/api/goals?*', { items: [first, second], total: 2, summary: {}, tracking_llm_configured: true })
  await jsonRoute(page, '**/api/goals/tree', { items: [first, second], total: 2 })
  await jsonRoute(page, '**/api/goals/goal-b', second)
  let release
  const saved = new Promise(resolve => { release = resolve })
  await page.route('**/api/goals/goal-a', async route => {
    if (route.request().method() === 'PUT') {
      await saved
      return route.fulfill({ json: { ...first, revision: 5 } })
    }
    return route.fulfill({ json: first })
  })
  await mount(page, 'app/goal/pages/index.vue', { privileges: ['GOAL_EDIT'] })
  const details = page.getByRole('button', { name: 'Goal details', exact: true })
  await details.first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name: 'Edit', exact: true }).click()
  const request = page.waitForRequest(request => request.url().endsWith('/api/goals/goal-a') && request.method() === 'PUT')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  try {
    await request
    await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
    await expect(dialog).toHaveCount(0)
    await details.nth(1).click()
    await expect(dialog).toContainText('Synthetic second Goal')
    const response = page.waitForResponse(response => response.url().endsWith('/api/goals/goal-a') && response.request().method() === 'PUT')
    release()
    await (await response).finished()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect.poll(() => page.evaluate(async () => {
      const { useGoalStore } = await import('/app/goal/stores/goalStore.ts')
      return useGoalStore(window.testApp.pinia).currentGoal?.id
    })).toBe('goal-b')
    await expect(dialog).toContainText('Synthetic second Goal')
  } finally { release() }
})
