import { test, expect, mount, setPrivileges, jsonRoute } from './fixtures.mjs'

test('the Laboratory menu follows access to its entries', async ({ page }) => {
  await page.route('**/api/auth/users?*', route => route.fulfill({ headers: { 'x-total-count': '0' }, json: [] }))
  await mount(page, 'core/user/pages/users.vue', {
    route: '/users', shell: true, privileges: ['READ_USER'],
  })
  const laboratory = page.getByRole('link', { name: 'Laboratory', exact: true })
  await expect(laboratory).toHaveCount(0)

  await setPrivileges(page, ['READ_USER', 'PLANNER_EVALUATION_ACCESS'])
  await expect(laboratory).toBeVisible()
  await expect(page.locator('a[href="/lab/planner"]')).toHaveCount(1)
  await expect(page.locator('a[href="/lab/processes"]')).toHaveCount(0)

  await setPrivileges(page, ['READ_USER'])
  await expect(laboratory).toHaveCount(0)
})

test('Services deep links select their permitted tab after delayed authorization and follow navigation', async ({ page }) => {
  for (const path of ['mail/approvers', 'services', 'services/capabilities', 'file-share/bridges', 'messenger/bridges']) await jsonRoute(page, `**/api/${path}`, [])
  await jsonRoute(page, '**/api/connections/overview?*', [])
  await jsonRoute(page, '**/api/connections/service-options', [])
  await jsonRoute(page, '**/api/connections/permission-options?*', [])
  await mount(page, 'app/index/pages/services.vue', { route: '/services?tab=connections', privileges: [] })
  await expect(page.getByRole('tab')).toHaveCount(0)
  await setPrivileges(page, ['SERVICE_ACCESS', 'CONNECTION_ACCESS', 'PERMISSION_ACCESS'])
  await expect(page.getByRole('tab', { name: 'Connections', exact: true })).toHaveAttribute('aria-selected', 'true')
  await page.evaluate(() => window.testApp.router.push('/services?tab=authorizations'))
  await expect(page.getByRole('tab', { name: 'Authorizations', exact: true })).toHaveAttribute('aria-selected', 'true')
  await setPrivileges(page, ['SERVICE_ACCESS'])
  await expect(page.getByRole('tab', { name: 'Services', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Authorizations', exact: true })).toHaveCount(0)
})

test('Skill assignment opens its catalogue and assignment controls without editing the catalogue', async ({ page }) => {
  await jsonRoute(page, '**/api/skills', [])
  await jsonRoute(page, '**/api/skills/agents', [])
  await jsonRoute(page, '**/api/skills/categories', [])
  await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_ASSIGN'] })
  await expect(page.getByRole('tab', { name: 'Authorizations', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Import a skill', exact: true })).toHaveCount(0)
  await setPrivileges(page, ['SKILL_ACCESS'])
  await expect(page.getByRole('tab', { name: 'Authorizations', exact: true })).toHaveCount(0)
  await setPrivileges(page, ['SKILL_ASSIGN'])
  await expect(page.getByRole('tab', { name: 'Authorizations', exact: true })).toBeVisible()
})

test('shell notifications wait for Chat access and stop when the role loses it', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('access_token', 'synthetic-notification-session'))
  let summaries = 0
  await page.route('**/api/chat/inbox', route => {
    summaries++
    return route.fulfill({ json: { unread_count: 0 } })
  })
  await jsonRoute(page, '**/api/chat/push/configuration', { available: false, public_key: null })
  await mount(page, 'app/chat/components/ChatNotificationBootstrap.vue', { privileges: ['CONTACT_EDIT'] })
  expect(summaries).toBe(0)
  await setPrivileges(page, ['CHAT_ACCESS'])
  await expect.poll(() => summaries).toBeGreaterThan(0)
  await setPrivileges(page, ['CONTACT_EDIT'])
  const stopped = summaries
  await page.evaluate(() => window.testApp.emitSocket('chat.personal_message', { data: {} }))
  expect(summaries).toBe(stopped)
})

test('Contacts-only operators select an agent without requesting Agent administration', async ({ page }) => {
  const forbidden = []
  await page.route('**/api/agents?*', route => {
    forbidden.push(route.request().url())
    return route.fulfill({ status: 403, json: { detail: 'Synthetic Agent administration denial' } })
  })
  await jsonRoute(page, '**/api/contacts?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/contacts/defaults', { country: '' })
  await mount(page, 'app/memory/pages/contacts.vue', { privileges: ['CONTACT_EDIT'] })
  await expect(page.getByRole('button', { name: 'Add contact', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Add contact', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(forbidden).toEqual([])
})

test('user and authorization tabs load only the permitted domain and follow role changes', async ({ page }) => {
  await page.route('**/api/auth/users?*', route => route.fulfill({ headers: { 'x-total-count': '0' }, json: [] }))
  await jsonRoute(page, '**/api/authorize/privileges', [])
  await jsonRoute(page, '**/api/authorize/privilege-lists', [])
  await jsonRoute(page, '**/api/authorize/roles', [])
  await mount(page, 'core/user/pages/users.vue', { route: '/users?tab=roles', privileges: ['READ_USER', 'READ_PRIVILEGE'] })
  await expect(page.getByRole('heading', { name: 'Users & Permissions', exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Users', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab')).toHaveCount(1)
  await setPrivileges(page, ['READ_ASSIGNMENT'])
  await expect(page.getByRole('tab')).toHaveCount(0)
  await setPrivileges(page, ['READ_ROLE'])
  await expect(page.getByRole('tab', { name: 'Roles', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('button', { name: 'New role', exact: true })).toHaveCount(0)
})

test('model-only and profile-only roles open their allowed tab without loading provider administration', async ({ page }) => {
  await jsonRoute(page, '**/api/llm-providers', [])
  await jsonRoute(page, '**/api/llm-providers/catalog', { items: [], users: [], active_user_count: 0 })
  await jsonRoute(page, '**/api/llm-providers/llms', [])
  await jsonRoute(page, '**/api/llm-profiles', { profiles: [], current_profile_id: null })
  await mount(page, 'app/llm/pages/index.vue', { route: '/llm?tab=providers', privileges: ['LLM_MODEL_ACCESS'] })
  await expect(page.getByRole('tab', { name: 'Available models', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab')).toHaveCount(1)
  await setPrivileges(page, ['LLM_PROFILE_EDIT'])
  await expect(page.getByRole('tab')).toHaveCount(1)
  await expect(page.getByRole('tab')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Available models', exact: true })).toHaveCount(0)
})

test('the requested Models tab survives an empty authorization state and subsequent loading', async ({ page }) => {
  await jsonRoute(page, '**/api/llm-providers', [])
  await jsonRoute(page, '**/api/llm-providers/catalog', { items: [], users: [], active_user_count: 0 })
  await jsonRoute(page, '**/api/llm-providers/llms', [])
  await jsonRoute(page, '**/api/llm-profiles', { profiles: [], current_profile_id: null })
  await mount(page, 'app/llm/pages/index.vue', { route: '/llm?tab=models', privileges: [] })
  await expect(page.getByRole('tab')).toHaveCount(0)
  await setPrivileges(page, ['LLM_PROVIDER_ACCESS', 'LLM_MODEL_ACCESS', 'LLM_PROFILE_ACCESS'])
  await expect(page.getByRole('tab', { name: 'Available models', exact: true })).toHaveAttribute('aria-selected', 'true')
  await setPrivileges(page, [])
  await expect(page.getByRole('tab')).toHaveCount(0)
  await setPrivileges(page, ['LLM_PROVIDER_ACCESS', 'LLM_MODEL_ACCESS', 'LLM_PROFILE_ACCESS'])
  await expect(page.getByRole('tab', { name: 'Available models', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.query.tab)).toBe('models')
})

for (const width of [1440, 390]) test(`indexing preferences can be delegated without Files or Dream access at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const writes = []
  await page.route('**/api/file-share/indexing*', route => {
    if (route.request().method() === 'POST') {
      writes.push(route.request().postDataJSON())
      return route.fulfill({ json: { id: 'synthetic-run', status: 'queued' } })
    }
    return route.fulfill({ json: { runs: [], total: 0, pending_repairs: 0, failed_repairs: 0 } })
  })
  await mount(page, 'core/params/pages/index.vue', { route: '/params', privileges: ['FILE_INDEX_ACCESS'] })
  const files = page.getByRole('link', { name: /Files/ })
  await files.press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/params/files')
  await mount(page, 'app/file_share/pages/settings.vue', { route: '/params/files?agent_id=7', privileges: ['FILE_INDEX_ACCESS'] })
  await expect(page.getByText('No traversal for this agent.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Index now', exact: true })).toHaveCount(0)
  await setPrivileges(page, ['FILE_INDEX_RUN'])
  await page.getByRole('textbox', { name: 'Source root (URI)', exact: true }).fill('console://reports/')
  await page.getByRole('button', { name: 'Index now', exact: true }).click()
  await expect.poll(() => writes).toEqual([{ agent_id: 7, root_uri: 'console://reports/' }])
  await expect(page.getByRole('button', { name: 'Index now', exact: true })).toBeEnabled()
  await page.screenshot({ path: testInfo.outputPath('file-preferences.png'), animations: 'disabled' })
  await setPrivileges(page, [])
  await expect(page.getByRole('button', { name: 'Index now', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Agent', { exact: true })).toHaveCount(0)
})

test('text history access mounts only its own activity and no Agent or Topic administration', async ({ page }) => {
  await jsonRoute(page, '**/api/conversations/messages?*', { items: [], total: 0, page: 1, page_size: 50,
    summary: { idle: 0, ready: 0, running: 0, waiting_approval: 0, paused: 0, errors: 0 } })
  await mount(page, 'app/index/pages/task.vue', { route: '/task?tab=tasks', privileges: ['CONVERSATION_ACCESS'] })
  await expect(page.getByRole('tab')).toHaveCount(1)
  await expect(page.getByRole('tab')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('combobox').first()).toBeVisible()
  await setPrivileges(page, [])
  await expect(page.getByRole('tab')).toHaveCount(0)
})

test('permission-only roles read policy metadata without loading Tool or Connection configuration', async ({ page }) => {
  await jsonRoute(page, '**/api/connections/permission-options?*', [])
  await mount(page, 'app/index/pages/services.vue', { route: '/services', privileges: ['PERMISSION_ACCESS'] })
  await expect(page.getByRole('tab')).toHaveCount(1)
  await expect(page.getByRole('tab')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('combobox').first()).toBeVisible()
})
