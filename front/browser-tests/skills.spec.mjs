import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function skillFixtures(page) {
  await jsonRoute(page, '**/api/skills', [{ id: 1, code: 'sample', label: 'Sample skill', description: 'A useful procedure', system: false, valid: true, available: true, category_id: null, file_count: 1, total_size: 200 }])
  await jsonRoute(page, '**/api/skills/agents', [])
  await jsonRoute(page, '**/api/skills/categories', [])
  await jsonRoute(page, '**/api/skills/learned/status', { enabled: false, mode: 'off' })
}

for (const [device, width] of [['mobile', 390], ['desktop', 1440]]) {
  test(`personal skills stay separate and can be filtered and read on ${device}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await skillFixtures(page)
    const owners = [
      { id: 71, code: 'synthetic-alpha', label: 'Synthetic Alpha', driver: 'internal' },
      { id: 72, code: 'synthetic-beta', label: 'Synthetic Beta', driver: 'internal' },
    ]
    const packages = owners.map((owner, index) => ({ id: index + 11, code: 'shared-guide',
      label: `Private guide ${index + 1}`, owner_agent_id: owner.id, owner_label: owner.label,
      revision: 1, enabled: true, available: true, valid: true, description: 'Synthetic private procedure',
      file_count: 2, updated_at: '2026-10-23T10:00:00Z' }))
    await jsonRoute(page, '**/api/skills/agents', owners)
    await jsonRoute(page, '**/api/agents/selection?scope=management', owners.map(owner => ({
      id: owner.id, label: owner.label, has_avatar: false,
    })))
    let fail = true
    await page.route('**/api/skills/personal?*', route => {
      if (fail) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary outage' } })
      const owner = new URL(route.request().url()).searchParams.get('owner_agent_id')
      const items = packages.filter(item => !owner || item.owner_agent_id === Number(owner))
      return route.fulfill({ json: { items, total: items.length } })
    })
    await jsonRoute(page, '**/api/skills/personal/12', { skill: packages[1], files: [
      { path: 'SKILL.md', name: 'SKILL.md', size: 80, text: true },
      { path: 'references/notes.txt', name: 'notes.txt', size: 40, text: true },
    ] })
    await page.route('**/api/skills/personal/12/content?*', route => route.fulfill({ json: {
      path: new URL(route.request().url()).searchParams.get('path'), size: 40,
      content: new URL(route.request().url()).searchParams.get('path') === 'SKILL.md'
        ? '# Private Beta instructions' : 'Private Beta reference',
    } }))
    await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_ACCESS'] })
    await expect(page.getByRole('tab', { name: 'Self-learning' })).toHaveCount(0)
    await page.getByRole('tab', { name: 'Personal skills', exact: true }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    fail = false
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(page.getByText('Private guide 1', { exact: true })).toBeVisible()
    await expect(page.getByText('Private guide 2', { exact: true })).toBeVisible()
    await page.getByRole('combobox', { name: 'Filter by agent' }).click()
    await page.getByRole('option', { name: 'Synthetic Beta' }).click()
    await expect(page.getByText('Private guide 1', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'View', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Private Beta instructions')).toBeVisible()
    await dialog.getByRole('combobox', { name: 'Choose a file' }).click()
    await page.getByRole('option', { name: 'references/notes.txt' }).click()
    await expect(dialog.getByText('Private Beta reference')).toBeVisible()
    if (device === 'mobile') await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    else await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
    await expect(dialog).toHaveCount(0)
    await page.getByRole('tab', { name: 'Skills', exact: true }).click()
    await expect(page.getByText('Sample skill', { exact: true })).toBeVisible()
    await expect(page.getByText('Private guide 2', { exact: true })).toHaveCount(0)
    await page.getByRole('tab', { name: 'Personal skills', exact: true }).click()
    await expect(page.getByText('Private guide 2', { exact: true })).toBeVisible()
    await page.locator('.q-tab-panel').filter({ has: page.getByText('Private guide 2', { exact: true }) })
      .screenshot({ path: testInfo.outputPath(`personal-panel-${device}.png`) })
    await page.screenshot({ path: testInfo.outputPath(`personal-skills-${device}.png`), fullPage: true })
  })
}
for (const [device, width] of [['mobile', 390], ['desktop', 1440]]) {
  test(`a skill can be authored, previewed and saved on ${device}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await skillFixtures(page)
    await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_EDIT', 'AGENT_MANAGE_ALL'] })
    const saved = []
    await page.route('**/api/skills', route => {
      expect(route.request().method()).toBe('POST')
      saved.push(route.request().postDataJSON())
      return route.fulfill({ json: { id: 2, ...saved.at(-1), system: false, valid: true, available: true, file_count: 1, total_size: 200 } })
    })
    await page.getByRole('button', { name: 'New skill' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    expect(saved).toEqual([])
    await dialog.locator('input').nth(0).fill('review-report')
    await dialog.locator('input').nth(1).fill('Review a report')
    await dialog.getByRole('tab', { name: /preview/i }).click()
    await expect(dialog.locator('.markdown-frontmatter')).toContainText('review-report')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => saved).toHaveLength(1)
    expect(saved[0]).toMatchObject({ code: 'review-report', label: 'Review a report', category_id: null })
    expect(saved[0].markdown).toContain('name: review-report')
    await expect(dialog).toHaveCount(0)
    await expect(page.getByText('Review a report', { exact: true })).toBeVisible()
  })
}

test('dismissing a new skill creates nothing and read-only users cannot create one', async ({ page }) => {
  await skillFixtures(page)
  await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_EDIT', 'AGENT_MANAGE_ALL'] })
  await page.getByRole('button', { name: 'New skill' }).click()
  await page.getByRole('dialog').locator('input').first().fill('discarded-draft')
  // The default fixture rejects every unexpected mutation request.
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('discarded-draft', { exact: true })).toHaveCount(0)
  await setPrivileges(page, [])
  await expect(page.getByRole('button', { name: 'New skill' })).toHaveCount(0)
})

test('skill descriptions remain readable and actions usable in a narrow desktop panel', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1024, height: 900 })
  await skillFixtures(page)
  await jsonRoute(page, '**/api/skills', [{ id: 1, code: 'sample', label: 'Sample skill', description: 'Read troubleshooting instructions before proceeding with the installation.', system: false, valid: true, available: true, category_id: null, file_count: 1, total_size: 200 }])
  await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_EDIT', 'AGENT_MANAGE_ALL'] })
  // Reserve the space normally occupied by the desktop navigation drawer.
  await page.locator('.q-page').evaluate(element => { element.style.maxWidth = '744px' })
  const description = page.getByText('Read troubleshooting instructions before proceeding with the installation.', { exact: true })
  await expect(description).toBeVisible()
  const table = page.getByRole('table')
  expect(await table.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  await table.getByRole('button').filter({ has: page.locator('.q-icon', { hasText: 'drive_file_move' }) }).click()
  await expect(page.getByRole('menu')).toContainText('Uncategorized')
  await page.keyboard.press('Escape')
  await page.screenshot({ path: testInfo.outputPath('skills-narrow-desktop.png'), fullPage: true })
})

test('skill authorization descriptions and controls remain usable in a narrow desktop panel', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1024, height: 900 })
  await skillFixtures(page)
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/skills/categories', [{ id: 3, label: 'Procedures', skill_count: 1 }])
  const row = { skill_id: 1, agent_id: 7, agent_label: 'Sample assistant', agent_code: 'sample-assistant', code: 'sample', label: 'Sample skill', description: 'Read troubleshooting instructions before proceeding with the installation.', category_id: 3, category_label: 'Procedures', global_state: 'enabled', category_state: 'disabled', agent_state: 'default', effective: false, available: true, valid: true }
  await jsonRoute(page, '**/api/skills/authorizations', { authorizations: [row] })
  const changes = []
  await page.route('**/api/skills/1/authorization/agents/7', route => {
    changes.push(route.request().postDataJSON())
    return route.fulfill({ json: { ...row, agent_state: 'enabled', effective: true, affected_agent_ids: [7] } })
  })
  await mount(page, 'app/skill/components/SkillAuthorizationManager.vue', { privileges: ['SKILL_ASSIGN', 'AGENT_MANAGE_ALL'] })
  const table = page.getByRole('table')
  await expect(table).toBeVisible()
  await table.evaluate(element => { element.closest('.q-table__container').style.maxWidth = '712px' })
  const description = page.getByText(row.description, { exact: true })
  await expect(description).toBeVisible()
  const global = table.getByRole('group', { name: 'Global (all): Sample skill' })
  const category = table.getByRole('group', { name: 'Category: Sample skill' })
  const agent = table.getByRole('group', { name: 'This agent: Sample skill' })
  await expect(global.getByRole('button', { pressed: true })).toHaveCount(0)
  await expect(category.getByRole('button', { name: 'Blocked', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(agent.getByRole('button', { pressed: true })).toHaveCount(0)
  await table.getByRole('button', { name: 'Active', exact: true }).last().click()
  await expect.poll(() => changes).toEqual([{ state: 'enabled' }])
  await expect(global.getByRole('button', { pressed: true })).toHaveCount(0)
  await expect(category.getByRole('button', { pressed: true })).toHaveCount(0)
  await expect(agent.getByRole('button', { name: 'Active', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.screenshot({ path: testInfo.outputPath('authorizations-narrow-desktop.png'), fullPage: true })
})
