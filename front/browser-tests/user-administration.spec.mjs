import { test, expect, jsonRoute, mount, setPrivileges } from './fixtures.mjs'

test('the user directory combines text, role, team and status on the server', async ({ page }) => {
  await jsonRoute(page, '**/api/authorize/role-options', [{ id: 11, code: 'SYNTHETIC_READER', display_name: 'Reader' }])
  await jsonRoute(page, '**/api/teams', [{ id: 21, name: 'Research' }])
  const requests = []
  await page.route('**/api/auth/users?*', route => {
    const filters = Object.fromEntries(new URL(route.request().url()).searchParams)
    requests.push(filters)
    const match = filters.search === 'archived' && filters.role_id === '11'
      && filters.team_id === '21' && filters.is_active === 'false'
    return route.fulfill({
      headers: { 'x-total-count': match ? '1' : '0' },
      json: match ? [{ id: 23, email: 'archived@example.invalid', display_name: 'Archived user',
        is_active: false, created_at: '2026-01-01T00:00:00Z' }] : [],
    })
  })
  await mount(page, 'core/user/pages/users.vue', {
    route: '/users', privileges: ['READ_USER', 'READ_ASSIGNMENT', 'TEAM_ACCESS'],
  })
  await expect(page.getByRole('tab', { name: 'Assignments', exact: true })).toHaveCount(0)
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill('archived')
  for (const [field, value] of [['Role', 'Reader'], ['Team', 'Research'], ['Status', 'Inactive']]) {
    await page.getByRole('combobox', { name: field, exact: true }).click()
    await page.getByRole('option', { name: value, exact: true }).click()
  }
  await expect(page.getByText('archived@example.invalid', { exact: true })).toBeVisible()
  expect(requests.at(-1)).toMatchObject({ search: 'archived', role_id: '11', team_id: '21', is_active: 'false', skip: '0' })
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill('')
  await expect(page.getByText('archived@example.invalid', { exact: true })).toHaveCount(0)
  expect(requests.at(-1)).not.toHaveProperty('search')
})

async function stubUserModels(page, userId) {
  await jsonRoute(page, '**/api/llm/me/options?include_native_voices=false', {
    profiles: [{ id: 17, label: 'Research profile' }], current_profile_id: null, voices: [],
  })
  await jsonRoute(page, '**/api/llm/me/native-voices', { native_voices: [] })
  await jsonRoute(page, `**/api/llm/users/${userId}/preferences`, { profile_id: null, voice_llm_id: null, voice_mode: 'tts', voice_code: null })
}

for (const width of [1440, 390]) {
  test(`user row editing respects privileges and keeps deletion separate (${width}px)`, async ({ page }, testInfo) => {
    const email = 'synthetic.user@example.invalid'
    await page.setViewportSize({ width, height: 900 })
    await stubUserModels(page, 23)
    await jsonRoute(page, '**/api/authorize/role-options', [])
    await jsonRoute(page, '**/api/teams', [])
    await jsonRoute(page, '**/api/teams?user_id=23', [])
    await page.route('**/api/auth/users?*', route => {
      const memberships = new URL(route.request().url()).searchParams.get('include_access') === 'true'
        ? { assignments: [{ id: 11, code: 'synthetic-reader', display_name: 'Reader' }], teams: [] }
        : {}
      return route.fulfill({
        headers: { 'x-total-count': '1' },
        json: [{ id: 23, email, display_name: 'Synthetic User', is_active: true, created_at: '2026-01-01T00:00:00Z',
          ...memberships }],
      })
    })
    await mount(page, 'core/user/pages/users.vue', {
      route: '/users', shell: true, dark: width < 1024,
      privileges: ['READ_USER', 'UPDATE_USER', 'DELETE_USER', 'READ_ASSIGNMENT', 'TEAM_ACCESS'],
    })
    if (width < 1024) {
      await page.locator('.q-drawer__backdrop').click({ position: { x: width - 10, y: 200 } })
    }

    const user = page.getByText(email, { exact: true })
    const dialog = page.getByRole('dialog')
    await expect(page.getByText('Reader', { exact: true })).toBeVisible()
    await expect(page.getByText('No teams', { exact: true })).toBeVisible()
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('users-list.png') })
    await user.click()
    await expect(dialog.getByLabel('Email', { exact: true })).toHaveValue(email)
    await expect(dialog.getByLabel('LLM profile', { exact: true })).toBeEnabled()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)

    await setPrivileges(page, ['READ_USER', 'DELETE_USER'])
    await expect(page.getByText('Reader', { exact: true })).toHaveCount(0)
    await expect(page.getByText('No teams', { exact: true })).toHaveCount(0)
    await user.click()
    await expect(dialog).toHaveCount(0)
    await setPrivileges(page, ['READ_USER', 'UPDATE_USER', 'DELETE_USER'])

    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(dialog.getByText('Confirm deletion', { exact: true })).toBeVisible()
    await expect(dialog).toHaveCount(1)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)

    await page.getByRole('button', { name: 'Edit', exact: true }).press('Enter')
    await expect(dialog.getByLabel('Email', { exact: true })).toHaveValue(email)
    await expect(dialog.getByLabel('LLM profile', { exact: true })).toBeEnabled()
  })
}

test('creates a user with assignments and teams, then manages their saved access', async ({ page }, testInfo) => {
  const roles = [
    { id: 11, code: 'synthetic-reader', display_name: 'Reader' },
    { id: 12, code: 'synthetic-editor', display_name: 'Editor' },
  ]
  const teams = [{ id: 21, name: 'Research' }, { id: 22, name: 'Support' }]
  const user = { id: 23, email: 'synthetic.member@example.invalid', is_active: true, created_at: '2026-01-01T00:00:00Z' }
  await stubUserModels(page, user.id)
  let created = false
  let createAttempts = 0
  let assignments = []
  let teamIds = []
  await jsonRoute(page, '**/api/authorize/role-options', roles)
  await page.route('**/api/teams', route => route.fulfill({ json: teams }))
  await page.route('**/api/teams?user_id=23', route => route.fulfill({ json: teams.filter(team => teamIds.includes(team.id)) }))
  await page.route('**/api/teams/*/humans/23', route => {
    const teamId = Number(new URL(route.request().url()).pathname.split('/')[3])
    const { present } = route.request().postDataJSON()
    teamIds = present ? [...teamIds, teamId] : teamIds.filter(id => id !== teamId)
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/authorize/users/23/assignments', route => route.fulfill({ json: assignments }))
  await page.route('**/api/authorize/assignments/111/default', route => {
    assignments = assignments.map(entry => ({ ...entry, is_default: entry.id === 111 }))
    return route.fulfill({ json: assignments[0] })
  })
  await page.route('**/api/auth/users?*', route => route.fulfill({
    headers: { 'x-total-count': created ? '1' : '0' },
    json: created ? [{
      ...user, assignments: assignments.map(entry => entry.role), teams: teams.filter(team => teamIds.includes(team.id)),
    }] : [],
  }))
  await page.route('**/api/auth/users', route => {
    const data = route.request().postDataJSON()
    expect(data).toMatchObject({ email: user.email, role_ids: [11, 12], default_role_id: 12, team_ids: [21],
      settings: { models: { profile_id: 17 } } })
    if (++createAttempts === 1) return route.fulfill({ status: 400, json: { detail: 'Creation refused. Try again.' } })
    assignments = data.role_ids.map(roleId => ({
      id: 100 + roleId, user_id: user.id, role_id: roleId, role: roles.find(role => role.id === roleId),
      is_default: roleId === data.default_role_id, user,
    }))
    teamIds = data.team_ids
    created = true
    return route.fulfill({ status: 201, json: user })
  })

  await mount(page, 'core/user/pages/users.vue', {
    route: '/users', shell: true,
    privileges: ['READ_USER', 'CREATE_USER', 'UPDATE_USER', 'MANAGE_ASSIGNMENT', 'TEAM_ACCESS', 'TEAM_MEMBERS_EDIT'],
  })
  const dialog = page.getByRole('dialog')
  const addOption = async (option, action) => {
    await dialog.getByRole('button', { name: action, exact: true }).click()
    await page.getByRole('menuitem', { name: option, exact: true }).click()
  }
  await page.getByRole('button', { name: 'New User', exact: true }).click()
  await dialog.getByLabel('Email', { exact: true }).fill(user.email)
  await dialog.getByLabel('Password', { exact: true }).fill('synthetic-password-123')
  await dialog.getByLabel('LLM profile', { exact: true }).click()
  await page.getByRole('option', { name: 'Research profile', exact: true }).click()
  const addAssignment = dialog.getByRole('button', { name: 'Add assignment', exact: true })
  const assignmentMenu = page.getByRole('menu', { name: 'Add assignment', exact: true })
  await addAssignment.press('Enter')
  await expect(assignmentMenu).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(assignmentMenu).toHaveCount(0)
  await expect(addAssignment).toBeFocused()
  await addOption('Reader (synthetic-reader)', 'Add assignment')
  await addOption('Editor (synthetic-editor)', 'Add assignment')
  const editorDefault = dialog.getByRole('radio', { name: 'Set Editor (synthetic-editor) as default' })
  await editorDefault.press('Space')
  await expect(editorDefault).toBeChecked()
  await addOption('Research', 'Add team')
  await expect(dialog.getByRole('cell', { name: 'Research', exact: true })).toBeVisible()
  await dialog.screenshot({ path: testInfo.outputPath('user-create-light.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.testApp.dark(true))
  await dialog.getByRole('cell', { name: 'Research', exact: true }).scrollIntoViewIfNeeded()
  await dialog.screenshot({ path: testInfo.outputPath('user-create-mobile-dark.png') })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.evaluate(() => window.testApp.dark(false))
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByText('Creation refused. Try again.')).toBeVisible()
  await expect(editorDefault).toBeChecked()
  await expect(dialog.getByRole('cell', { name: 'Research', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Reader', { exact: true })).toBeVisible()
  await expect(page.getByText('Editor', { exact: true })).toBeVisible()
  await expect(page.getByText('Research', { exact: true })).toBeVisible()

  const reopen = async () => {
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog.getByLabel('Email', { exact: true })).toHaveValue(user.email)
  }
  await reopen()
  await expect(editorDefault).toBeChecked()
  await expect(dialog.getByLabel('LLM profile', { exact: true })).toBeEnabled()
  await dialog.screenshot({ animations: 'disabled', path: testInfo.outputPath('user-edit-light.png') })
  const readerDefault = dialog.getByRole('radio', { name: 'Set Reader (synthetic-reader) as default' })
  await readerDefault.click()
  await expect(readerDefault).toBeChecked()
  await expect(editorDefault).not.toBeChecked()
  await dialog.getByRole('button', { name: 'Remove from team Research' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'OK', exact: true }).click()
  await expect(dialog.getByRole('cell', { name: 'Research', exact: true })).toHaveCount(0)
  await addOption('Support', 'Add team')
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Support', { exact: true })).toBeVisible()
  await expect(page.getByText('Research', { exact: true })).toHaveCount(0)
  await reopen()
  await expect(readerDefault).toBeChecked()
  await expect(dialog.getByRole('cell', { name: 'Support', exact: true })).toBeVisible()
  await expect(dialog.getByRole('cell', { name: 'Research', exact: true })).toHaveCount(0)
})
