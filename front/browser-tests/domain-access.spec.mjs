import { test, expect, mount, setPrivileges, jsonRoute } from './fixtures.mjs'

test('Skill assignment alone opens its catalogue without exposing the learned-skill reader', async ({ page }) => {
  await jsonRoute(page, '**/api/skills', [])
  await jsonRoute(page, '**/api/skills/agents', [])
  await jsonRoute(page, '**/api/skills/categories', [])
  await mount(page, 'app/skill/pages/index.vue', { privileges: ['SKILL_ASSIGN'] })
  await expect(page.getByRole('tab', { name: 'Self-learning', exact: true })).toHaveCount(0)
  await setPrivileges(page, ['SKILL_ACCESS'])
  await expect(page.getByRole('tab', { name: 'Self-learning', exact: true })).toHaveCount(1)
  await setPrivileges(page, ['SKILL_ASSIGN'])
  await expect(page.getByRole('tab', { name: 'Self-learning', exact: true })).toHaveCount(0)
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
  await page.evaluate(() => window.testApp.emitSocket('chat.message', { data: {} }))
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

test('authorization tabs load only the permitted domain and follow role changes', async ({ page }) => {
  await jsonRoute(page, '**/api/authorize/privileges', [])
  await jsonRoute(page, '**/api/authorize/privilege-lists', [])
  await jsonRoute(page, '**/api/authorize/roles', [])
  await jsonRoute(page, '**/api/authorize/role-options', [])
  await jsonRoute(page, '**/api/authorize/assignments?*', { items: [], total: 0 })
  await mount(page, 'core/authorize/pages/index.vue', { privileges: ['READ_PRIVILEGE'] })
  await expect(page.getByRole('tab', { name: 'Privileges', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab')).toHaveCount(1)
  await setPrivileges(page, ['READ_ASSIGNMENT'])
  await expect(page.getByRole('tab', { name: 'Assignments', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab')).toHaveCount(1)
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
  await mount(page, 'app/task/pages/index.vue', { route: '/task?tab=tasks', privileges: ['CONVERSATION_ACCESS'] })
  await expect(page.getByRole('tab')).toHaveCount(1)
  await expect(page.getByRole('tab')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('combobox').first()).toBeVisible()
  await setPrivileges(page, [])
  await expect(page.getByRole('tab')).toHaveCount(0)
})

test('permission-only roles read policy metadata without loading Tool or Connection configuration', async ({ page }) => {
  await jsonRoute(page, '**/api/connections/permission-options?*', [])
  await mount(page, 'app/tools/pages/index.vue', { route: '/tools', privileges: ['PERMISSION_ACCESS'] })
  await expect(page.getByRole('tab')).toHaveCount(1)
  await expect(page.getByRole('tab')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('combobox').first()).toBeVisible()
})
