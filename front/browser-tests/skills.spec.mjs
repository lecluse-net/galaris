import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function skillFixtures(page) {
  await jsonRoute(page, '**/api/skills', [{ id: 1, revision: 1, enabled: true, code: 'sample', label: 'Sample skill', description: 'A useful procedure', system: false, valid: true, available: true, category_id: null, file_count: 1, total_size: 200 }])
  await jsonRoute(page, '**/api/skills/agents', [])
  await jsonRoute(page, '**/api/skills/categories', [])
  await jsonRoute(page, '**/api/skills/learned/status', { enabled: false, mode: 'off' })
}

test('making a library skill personal chooses one owner and retains the operation on retry', async ({ page }) => {
  await skillFixtures(page)
  await jsonRoute(page, '**/api/agents/selection?*', [{ id: 7, label: 'Synthetic owner', has_avatar: false }])
  await jsonRoute(page, '**/api/skills/1', { id: 1, enabled: true, code: 'sample', label: 'Sample skill', revision: 7 })
  const attempts = []
  await page.route('**/api/skills/1/assign-ownership', route => {
    attempts.push(route.request().postDataJSON())
    if (attempts.length === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary outage' } })
    return route.fulfill({ json: { cleanup_pending: attempts.length === 2 } })
  })
  await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_EDIT', 'AGENT_MANAGE_ALL'] })
  await page.getByText('Sample skill', { exact: true }).click({ button: 'right' })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'View', exact: true }).focus()
  await page.keyboard.press('Shift+F10')
  await page.getByRole('menuitem', { name: 'Make personal', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Make personal', exact: true })).toBeDisabled()
  await dialog.getByRole('combobox', { name: 'Owner agent', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic owner', exact: true }).click()
  await dialog.getByLabel('Code', { exact: true }).fill('private-sample')
  await dialog.getByRole('button', { name: 'Make personal', exact: true }).click()
  await expect(dialog).toContainText('Synthetic temporary outage')
  await expect(dialog.getByRole('combobox')).toHaveValue('Synthetic owner')
  await dialog.getByRole('button', { name: 'Make personal', exact: true }).click()
  await expect(dialog).toContainText('Conversion is recorded')
  await expect(dialog.getByLabel('Code', { exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Make personal', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(attempts).toHaveLength(3)
  expect(attempts[1]).toEqual(attempts[0])
  expect(attempts[2]).toEqual(attempts[0])
  expect(attempts[0]).toMatchObject({ owner_agent_id: 7, expected_revision: 7, new_code: 'private-sample' })
  await page.getByRole('button', { name: 'Make personal', exact: true }).click()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(dialog).toHaveCount(0)
  expect(attempts).toHaveLength(3)
  await setPrivileges(page, ['SKILL_EDIT'])
  await expect(page.getByRole('button', { name: 'Make personal', exact: true })).toHaveCount(0)
})

for (const [device, width] of [['mobile', 390], ['desktop', 1440]]) {
  test(`personal skill mutations preserve drafts on conflict and refresh after conversion on ${device}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const skill = { id: 12, code: 'private-guide', label: 'Synthetic private guide', owner_agent_id: 7, owner_label: 'Synthetic owner', revision: 1, enabled: true, available: true, valid: true, description: 'Synthetic instructions', file_count: 1, updated_at: '2026-10-24T10:00:00Z' }
    let source = '# Original private instructions', present = true, conflict = true, releaseAttempts = []
    const transfers = []
    await jsonRoute(page, '**/api/agents/selection?*', [
      { id: 7, label: 'Synthetic owner', has_avatar: false },
      { id: 8, label: 'Synthetic recipient', has_avatar: false },
    ])
    await jsonRoute(page, '**/api/skills/agents', [])
    await page.route('**/api/skills/personal?*', route => route.fulfill({ json: { items: present ? [skill] : [], total: present ? 1 : 0 } }))
    await page.route('**/api/skills/personal/12', route => {
      if (route.request().method() === 'PUT') { expect(route.request().postDataJSON().expected_revision).toBe(skill.revision); skill.label = route.request().postDataJSON().label; skill.revision++ }
      return route.fulfill({ json: { skill, files: [{ path: 'SKILL.md', name: 'SKILL.md', size: source.length, text: true }], revision: skill.revision } })
    })
    await page.route('**/api/skills/personal/12/content*', route => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON()
        if (conflict) return route.fulfill({ status: 409, json: { detail: 'Synthetic revision conflict: reopen to reload' } })
        expect(body.expected_revision).toBe(skill.revision)
        source = body.content; skill.label = body.label; skill.revision++
      }
      return route.fulfill({ json: { path: 'SKILL.md', content: source, size: source.length, revision: skill.revision } })
    })
    await page.route('**/api/skills/personal/12/enabled', route => {
      const body = route.request().postDataJSON()
      expect(body.expected_revision).toBe(skill.revision)
      skill.enabled = body.enabled; skill.revision++
      return route.fulfill({ json: { revision: skill.revision } })
    })
    await page.route('**/api/skills/12/release-ownership', route => {
      const body = route.request().postDataJSON(); releaseAttempts.push(body)
      if (releaseAttempts.length === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary outage' } })
      expect(body.operation_id).toBe(releaseAttempts[0].operation_id)
      expect(body.expected_revision).toBe(skill.revision)
      present = false
      return route.fulfill({ json: { cleanup_pending: false } })
    })
    await page.route('**/api/skills/personal/12/owner', route => {
      const body = route.request().postDataJSON(); transfers.push(body)
      if (transfers.length === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic transfer outage' } })
      expect(body).toEqual(transfers[0])
      expect(body.owner_agent_id).toBe(8)
      expect(body.expected_revision).toBe(skill.revision)
      skill.owner_agent_id = 8; skill.owner_label = 'Synthetic recipient'; skill.revision++
      return route.fulfill({ json: { cleanup_pending: false } })
    })
    await mount(page, 'app/skill/components/PersonalSkillManager.vue', { props: { active: true }, privileges: ['SKILL_EDIT', 'AGENT_MANAGE_ALL'] })
    await page.getByText(skill.label, { exact: true }).click({ button: 'right' })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('menuitem', { name: 'Disable', exact: true }).click()
    await expect(page.getByText('Inactive', { exact: true })).toBeVisible()
    await page.getByText(skill.label, { exact: true }).click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Edit', exact: true }).click()
    let dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Source', { exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).last().click()
    await expect(dialog.getByLabel('Label', { exact: true })).not.toHaveAttribute('readonly')
    await expect(dialog.getByLabel('Source', { exact: true })).toHaveCount(0)
    await dialog.getByLabel('Label', { exact: true }).fill('Renamed private guide')
    await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog.getByLabel('Label', { exact: true })).not.toHaveAttribute('readonly')
    await expect(dialog.getByLabel('Label', { exact: true })).toHaveValue('Renamed private guide')
    await dialog.getByLabel('Source', { exact: true }).fill('# Preserved private draft')
    await page.screenshot({ path: testInfo.outputPath(`personal-code-editor-${device}.png`), fullPage: true, animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('revision conflict')
    await expect(dialog.getByLabel('Source', { exact: true })).toHaveValue('# Preserved private draft')
    await expect(dialog.getByLabel('Label', { exact: true })).toHaveValue('Renamed private guide')
    expect(skill.label).toBe('Synthetic private guide')
    conflict = false
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog.getByText('Preserved private draft', { exact: true })).toBeVisible()
    await expect(dialog.getByText('Renamed private guide', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Label', { exact: true })).not.toHaveAttribute('readonly')
    await dialog.getByLabel('Label', { exact: true }).fill('Final private guide')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog.getByText('Final private guide', { exact: true })).toBeVisible()
    expect(source).toBe('# Preserved private draft')
    await expect(dialog.getByLabel('Source', { exact: true })).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
    await dialog.getByLabel('Label', { exact: true }).fill('Discarded label')
    await dialog.getByLabel('Source', { exact: true }).fill('Discarded content')
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).last().click()
    await expect(dialog.getByLabel('Label', { exact: true })).toHaveValue('Final private guide')
    await expect(dialog.getByText('Preserved private draft', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`personal-edited-${device}.png`), fullPage: true, animations: 'disabled' })
    await dialog.getByRole('combobox', { name: 'Owner agent', exact: true }).click()
    await page.getByRole('option', { name: 'Synthetic recipient', exact: true }).click()
    await dialog.getByRole('button', { name: 'Change owner', exact: true }).click()
    const transfer = page.getByRole('dialog').last()
    await transfer.getByRole('button', { name: 'Change owner', exact: true }).click()
    await expect(transfer.getByRole('alert')).toContainText('Synthetic transfer outage')
    await transfer.getByRole('button', { name: 'Change owner', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByText(skill.label, { exact: true }).click()
    dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('combobox', { name: 'Owner agent', exact: true })).toHaveValue('Synthetic recipient')
    await expect(dialog.getByText('Preserved private draft', { exact: true })).toBeVisible()
    expect(transfers).toHaveLength(2)
    await dialog.getByRole('button', { name: 'Convert to generic skill', exact: true }).click()
    const confirmation = page.getByRole('dialog').last()
    await confirmation.getByLabel('Code', { exact: true }).fill('released-guide')
    await confirmation.getByRole('button', { name: 'Convert to generic skill', exact: true }).click()
    await expect(confirmation.getByRole('alert')).toContainText('temporary outage')
    await confirmation.getByRole('button', { name: 'Convert to generic skill', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByText('No personal skills within this scope.')).toBeVisible()
    expect(releaseAttempts).toHaveLength(2)
  })
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
      revision: 1, enabled: index === 0, available: true, valid: true,
      description: 'Reusable private procedure for checking fictional budget totals, documenting assumptions, and preserving the evidence attached to each conclusion.',
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
    await page.screenshot({ path: testInfo.outputPath(`personal-list-${device}.png`), fullPage: true, animations: 'disabled' })
    if (device === 'desktop') {
      await page.locator('.q-page').evaluate(element => { element.style.maxWidth = '744px' })
      await page.screenshot({ path: testInfo.outputPath('personal-list-narrow.png'), fullPage: true, animations: 'disabled' })
      await page.locator('.q-page').evaluate(element => { element.style.maxWidth = '' })
    }
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath(`personal-list-dark-${device}.png`), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(false))
    await page.getByRole('combobox', { name: 'Filter by agent' }).click()
    await page.getByRole('option', { name: 'Synthetic Beta' }).click()
    await expect(page.getByText('Private guide 1', { exact: true })).toHaveCount(0)
    await page.getByText('Private guide 2', { exact: true }).click({ button: 'right' })
    await expect(page.getByRole('menuitem', { name: 'View', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`personal-menu-${device}.png`), fullPage: true, animations: 'disabled' })
    await expect(page.getByRole('menuitem', { name: 'Edit', exact: true })).toHaveCount(0)
    await page.getByRole('menuitem', { name: 'View', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Private Beta instructions')).toBeVisible()
    await dialog.getByRole('combobox', { name: 'Choose a file' }).click()
    await page.getByRole('option', { name: 'references/notes.txt' }).click()
    await expect(dialog.getByText('Private Beta reference')).toBeVisible()
    if (device === 'mobile') await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    else await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
    await expect(dialog).toHaveCount(0)
    await page.getByText('Private guide 2', { exact: true }).click()
    await expect(page.getByRole('menu')).toHaveCount(0)
    await expect(dialog.getByText('Private Beta instructions')).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await page.getByRole('tab', { name: 'Skills', exact: true }).click()
    await expect(page.getByText('Sample skill', { exact: true })).toBeVisible()
    await expect(page.getByText('Private guide 2', { exact: true })).toHaveCount(0)
    await jsonRoute(page, '**/api/skills/1/files', [{ path: 'SKILL.md', name: 'SKILL.md', size: 50, text: true }])
    await jsonRoute(page, '**/api/skills/1/content?*', { path: 'SKILL.md', content: '# Synthetic library procedure', size: 50 })
    await page.getByText('Sample skill', { exact: true }).click({ button: 'right' })
    await expect(page.getByRole('menuitem', { name: 'View', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`library-menu-${device}.png`), fullPage: true, animations: 'disabled' })
    await page.getByRole('menuitem', { name: 'View', exact: true }).click()
    const libraryViewer = page.getByRole('dialog')
    await expect(libraryViewer.getByRole('heading', { name: 'Synthetic library procedure' })).toBeVisible()
    await expect(libraryViewer.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath(`skill-reading-${device}.png`), fullPage: true, animations: 'disabled' })
    await libraryViewer.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(libraryViewer).toHaveCount(0)
    await page.getByText('Sample skill', { exact: true }).click()
    await expect(page.getByRole('menu')).toHaveCount(0)
    await expect(libraryViewer.getByRole('heading', { name: 'Synthetic library procedure' })).toBeVisible()
    await libraryViewer.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(libraryViewer).toHaveCount(0)
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
      return route.fulfill({ json: { id: 2, revision: 1, enabled: true, ...saved.at(-1), system: false, valid: true, available: true, file_count: 1, total_size: 200 } })
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
  const skill = { id: 1, revision: 1, enabled: true, code: 'sample', label: 'Sample skill', description: 'Read troubleshooting instructions before proceeding with the installation.', system: false, valid: true, available: true, category_id: null, file_count: 1, total_size: 200 }
  await jsonRoute(page, '**/api/skills', [skill])
  await jsonRoute(page, '**/api/skills/categories', [{ id: 3, label: 'Synthetic procedures', skill_count: 0 }])
  const changes = []
  await page.route('**/api/skills/1/category', route => {
    changes.push(route.request().postDataJSON())
    return route.fulfill({ json: { skill: { ...skill, category_id: 3, category_label: 'Synthetic procedures' }, affected_agent_ids: [] } })
  })
  await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_EDIT', 'AGENT_MANAGE_ALL'] })
  // Reserve the space normally occupied by the desktop navigation drawer.
  await page.locator('.q-page').evaluate(element => { element.style.maxWidth = '744px' })
  const description = page.getByText('Read troubleshooting instructions before proceeding with the installation.', { exact: true })
  await expect(description).toBeVisible()
  const table = page.getByRole('table')
  expect(await table.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  await table.getByRole('button').filter({ has: page.locator('.q-icon', { hasText: 'drive_file_move' }) }).click()
  await expect(page.getByRole('button', { name: 'Uncategorized', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.getByText('Sample skill', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Assign a category', exact: true }).press('ArrowRight')
  await page.getByRole('menuitem', { name: 'Synthetic procedures', exact: true }).click()
  await expect(page.getByRole('menu')).toHaveCount(0)
  expect(changes).toEqual([{ category_id: 3 }])
  await page.screenshot({ path: testInfo.outputPath('skills-narrow-desktop.png'), fullPage: true })
})

test('skill authorization descriptions and controls remain usable in a narrow desktop panel', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1024, height: 900 })
  await skillFixtures(page)
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/skills/categories', [{ id: 3, label: 'Procedures', skill_count: 1 }])
  const row = { enabled: true, skill_id: 1, agent_id: 7, agent_label: 'Sample assistant', agent_code: 'sample-assistant', code: 'sample', label: 'Sample skill', description: 'Read troubleshooting instructions before proceeding with the installation.', category_id: 3, category_label: 'Procedures', global_state: 'enabled', category_state: 'disabled', agent_state: 'default', effective: false, available: true, valid: true }
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

for (const width of [390, 1440]) {
  test(`generic activation keeps server state and permissions at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await skillFixtures(page)
    let skill = { id: 1, revision: 1, enabled: true, code: 'sample', label: 'Sample skill',
      system: true, valid: true, available: true, category_id: null, file_count: 1, total_size: 200 }
    await page.route('**/api/skills', route => route.fulfill({ json: [skill] }))
    const changes = []
    await page.route('**/api/skills/1/enabled', route => {
      const data = route.request().postDataJSON()
      changes.push(data)
      if (changes.length === 1) {
        skill = { ...skill, revision: 2 }
        return route.fulfill({ status: 409, json: { detail: 'Synthetic revision conflict' } })
      }
      expect(data.expected_revision).toBe(skill.revision)
      skill = { ...skill, enabled: data.enabled, revision: skill.revision + 1 }
      return route.fulfill({ json: skill })
    })
    await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_EDIT', 'AGENT_MANAGE_ALL'] })
    const disable = page.getByRole('button', { name: 'Disable for everyone', exact: true })
    await disable.click()
    await expect(page.getByText('Synthetic revision conflict', { exact: true })).toBeVisible()
    await expect(disable).toBeEnabled()
    await disable.click()
    await expect(page.getByText('Disabled for everyone', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Enable for everyone', exact: true })).toBeVisible()
    expect(changes).toEqual([{ enabled: false, expected_revision: 1 }, { enabled: false, expected_revision: 2 }])
    await page.screenshot({ path: testInfo.outputPath(`generic-disabled-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: 'Enable for everyone', exact: true }).focus()
    await page.keyboard.press('Shift+F10')
    await page.getByRole('menuitem', { name: 'Enable for everyone', exact: true }).click()
    await expect(disable).toBeVisible()
    expect(changes.at(-1)).toEqual({ enabled: true, expected_revision: 3 })
    await setPrivileges(page, ['SKILL_EDIT'])
    await expect(disable).toHaveCount(0)
    await page.getByText('Sample skill', { exact: true }).click({ button: 'right' })
    await expect(page.getByRole('menuitem', { name: 'Disable for everyone', exact: true })).toHaveCount(0)
  })
}
