import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function skillFixtures(page) {
  await jsonRoute(page, '**/api/skills', [{ id: 1, code: 'sample', label: 'Sample skill', description: 'A useful procedure', system: false, valid: true, available: true, category_id: null, file_count: 1, total_size: 200 }])
  await jsonRoute(page, '**/api/skills/agents', [])
  await jsonRoute(page, '**/api/skills/categories', [])
  await jsonRoute(page, '**/api/skills/learned/status', { enabled: false, mode: 'off' })
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
