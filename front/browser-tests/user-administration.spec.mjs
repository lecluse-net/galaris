import { test, expect, mount, setPrivileges } from './fixtures.mjs'

for (const width of [1440, 390]) {
  test(`user row editing respects privileges and keeps deletion separate (${width}px)`, async ({ page }) => {
    const email = 'synthetic.user@example.invalid'
    await page.setViewportSize({ width, height: 900 })
    await page.route('**/api/auth/users?*', route => route.fulfill({
      headers: { 'x-total-count': '1' },
      json: [{ id: 23, email, display_name: 'Synthetic User', is_active: true, created_at: '2026-01-01T00:00:00Z' }],
    }))
    await mount(page, 'core/user/pages/users.vue', {
      route: '/user/users', shell: true, dark: width < 1024, privileges: ['READ_USER', 'UPDATE_USER', 'DELETE_USER'],
    })
    if (width < 1024) {
      await page.locator('.q-drawer__backdrop').click({ position: { x: width - 10, y: 200 } })
    }

    const user = page.getByText(email, { exact: true })
    const dialog = page.getByRole('dialog')
    await user.click()
    await expect(dialog.getByLabel('Email', { exact: true })).toHaveValue(email)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)

    await setPrivileges(page, ['READ_USER', 'DELETE_USER'])
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
  })
}
