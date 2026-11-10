import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const people = (kind, count) => Array.from({ length: count }, (_, index) => ({
  kind, id: index + 10, label: `${kind} ${String(index + 1).padStart(3, '0')}`, has_avatar: false,
}))
const me = { kind: 'user', id: 1, label: 'Synthetic current user', is_current_user: true }
const picker = page => page.getByRole('combobox', { name: 'Owner', exact: true })

for (const width of [390, 1440]) for (const dark of [false, true]) {
test(`owner choices group teams then agents and users (${width}px, dark=${dark})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const teams = [{ id: 2, name: 'Research', order: 1 }, { id: 1, name: 'Support', order: 2 }]
  await jsonRoute(page, '**/api/agents/selection?scope=management', [{ id: 7, label: 'Alice', has_avatar: false, teams }])
  await jsonRoute(page, '**/api/teams/human-selection', [{ id: 1, teams: [teams[0]] }, { id: 7, teams }])
  await mount(page, 'app/share/components/OwnerSelect.vue', { dark, props: {
    modelValue: 'user:1', options: [me, { kind: 'user', id: 7, label: 'Human Alice' }, { kind: 'agent', id: 7, label: 'Alice' }, { kind: 'user', id: 9, label: 'No team human' }],
  } })
  await picker(page).click()
  await expect(page.getByText('Research', { exact: true })).toBeVisible()
  await expect(page.getByText('Support', { exact: true })).toBeVisible()
  await expect(page.getByRole('option', { name: 'Alice', exact: true })).toHaveCount(2)
  const research = page.getByRole('group', { name: 'Research', exact: true })
  await expect(research.getByRole('group', { name: 'Agents', exact: true }).getByRole('option', { name: 'Alice', exact: true })).toBeVisible()
  await expect(research.getByRole('group', { name: 'Users', exact: true }).getByRole('option', { name: 'Human Alice', exact: true })).toBeVisible()
  await expect(research.getByRole('option', { name: 'Me', exact: true })).toBeVisible()
  await expect(page.getByRole('group', { name: 'No team', exact: true }).getByRole('option', { name: 'No team human', exact: true })).toBeVisible()
  await testInfo.attach('owner-team-hierarchy', { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
  await page.getByRole('option', { name: 'Alice', exact: true }).last().click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe('agent:7')
  await picker(page).click()
  await page.getByRole('textbox', { name: 'Search owners', exact: true }).fill('Human Alice')
  await expect(page.getByRole('option', { name: 'Alice', exact: true })).toHaveCount(0)
  await page.getByRole('option', { name: 'Human Alice', exact: true }).last().click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe('user:7')
})
}

for (const width of [1440, 390]) {
test(`owners remain reachable across independent pages and searches at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await mount(page, 'app/share/components/OwnerSelect.vue', { props: {
    modelValue: 'user:1', options: [...people('agent', 51), ...people('user', 51), me], clearable: true,
  } })
  await picker(page).focus(); await page.keyboard.press('Enter')
  await expect(page.getByRole('option', { name: 'Me', exact: true })).toBeVisible()
  const users = page.getByRole('group', { name: 'Pagination: No team / Users', exact: true })
  const agents = page.getByRole('group', { name: 'Pagination: No team / Agents', exact: true })
  await users.getByRole('button', { name: '2', exact: true }).click()
  await expect(page.getByRole('option', { name: 'user 051', exact: true })).toBeVisible()
  await expect(page.getByRole('option', { name: 'agent 001', exact: true })).toBeVisible()
  await agents.getByRole('button', { name: '2', exact: true }).click()
  await page.getByRole('option', { name: 'agent 051', exact: true }).click()
  await expect(picker(page)).toContainText('agent 051')
  await picker(page).click()
  await page.getByRole('textbox', { name: 'Search owners', exact: true }).fill('user 051')
  await expect(page.getByRole('group', { name: /Pagination:/ })).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath(`owner-search-${width}.png`), animations: 'disabled' })
  await page.getByRole('option', { name: 'user 051', exact: true }).click()
  await expect(picker(page)).toContainText('user 051')
  await page.getByRole('button', { name: 'Clear owner', exact: true }).click()
  await expect(picker(page)).toHaveText('All owners')
  await picker(page).click(); await page.keyboard.press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  await picker(page).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
})
}

test('owner pagination includes the current user and retains a saved owner outside the catalogue', async ({ page }) => {
  const current = { kind: 'user', id: 1000, label: 'Synthetic saved owner' }
  await mount(page, 'app/share/components/OwnerSelect.vue', { props: {
    modelValue: 'user:1000', current, currentUserId: 1, options: [...people('agent', 50), ...people('user', 50), { ...me, is_current_user: false }],
  } })
  await expect(picker(page)).toContainText(current.label)
  await picker(page).click()
  await expect(page.getByRole('group', { name: /Pagination:/ })).toHaveCount(1)
  // Me is now included in the Users section's 50-person page.
  await expect(page.getByRole('option')).toHaveCount(100)
  await page.getByRole('textbox', { name: 'Search owners', exact: true }).fill('no matching synthetic owner')
  await expect(page.getByText('No owners available.', { exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: 'Search owners', exact: true }).fill('')
  await page.getByRole('option').filter({ hasText: 'Me' }).click()
  await expect(picker(page)).toContainText('Me')
})

test('the default owner renderer loads real user and agent avatars and reuses agent bytes across openings', async ({ page }) => {
  const portrait = color => `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="${color}"/><circle cx="16" cy="11" r="6" fill="white"/><path d="M5 32v-6a11 11 0 0 1 22 0v6" fill="white"/></svg>`
  let reads = 0
  await page.route('**/api/auth/avatars/synthetic-user', route => route.fulfill({ contentType: 'image/svg+xml', body: portrait('#087FF5') }))
  await page.route('**/api/agents/10/avatar', route => { reads++; return route.fulfill({ contentType: 'image/svg+xml', body: portrait('#FF9A00') }) })
  const owners = [
    { ...me, avatar_url: '/api/auth/avatars/synthetic-user' },
    { kind: 'agent', id: 10, label: 'Synthetic pictured agent', has_avatar: true },
  ]
  await mount(page, 'app/share/components/OwnerSelect.vue', { props: { modelValue: 'user:1', options: owners } })
  await expect(picker(page).getByRole('img')).toHaveJSProperty('naturalWidth', 32)
  await picker(page).click()
  const agent = page.getByRole('option', { name: 'Synthetic pictured agent', exact: true })
  await expect(agent.getByRole('img')).toHaveJSProperty('naturalWidth', 32)
  await expect(page.getByRole('option', { name: 'Me', exact: true }).getByRole('img')).toHaveJSProperty('naturalWidth', 32)
  await agent.click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(picker(page).getByRole('img')).toHaveJSProperty('naturalWidth', 32)
  await picker(page).click()
  await expect(page.getByRole('listbox')).toBeVisible()
  await expect(agent.getByRole('img')).toHaveJSProperty('naturalWidth', 32)
  expect(reads).toBe(1)
  await page.screenshot({ path: test.info().outputPath('owner-avatars.png'), animations: 'disabled' })
})
